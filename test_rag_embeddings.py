#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import sqlite3
import torch
import torch.nn.functional as F # Added for multilingual-e5-large
from transformers import AutoTokenizer, AutoModel
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import re
import logging
from typing import List, Dict, Any, Tuple

# --- Logger Setup (Minimal for this test script) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Constants ---
DB_PATH = "/mnt/data/AI4Deliberation/new_html_extraction/custom_deliberations.db"
MODEL_ID = "intfloat/multilingual-e5-large" # Changed model
OUTPUT_CONTEXT_FILE = "test_rag_context_e5_docs_from_article_title.txt" # Changed output file

# --- Dynamically add article_parser_utils to path and import ---
# Not strictly needed for this version as we're doing simple document chunking,
# but keeping it in case it's useful for other tests or if article parsing is re-introduced.
ARTICLE_PARSER_UTILS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), 'new_html_extraction', 'article_extraction_analysis'))
if ARTICLE_PARSER_UTILS_PATH not in sys.path:
    sys.path.append(ARTICLE_PARSER_UTILS_PATH)

try:
    import article_parser_utils # Will be used if get_chunks_for_article is reinstated
    logger.info(f"Successfully imported article_parser_utils from: {ARTICLE_PARSER_UTILS_PATH}")
except ImportError as e:
    logger.warning(f"Failed to import article_parser_utils: {e}. This is okay if not using advanced article chunking.")
except Exception as e:
    logger.error(f"An unexpected error occurred during article_parser_utils import: {e}")
    # sys.exit(1) # Don't exit if it's just a warning for this script's purpose

# --- Model Loading ---
def load_model_and_tokenizer(model_id: str):
    logger.info(f"Loading tokenizer for {model_id}...")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    logger.info(f"Loading model {model_id}...")
    try:
        # multilingual-e5-large typically doesn't need specific torch_dtype for basic loading
        # and device_map="auto" is good for flexibility.
        model = AutoModel.from_pretrained(model_id, device_map="auto")
    except Exception as e:
        logger.error(f"Failed to load model {model_id}: {e}. Trying with float16.")
        try:
            model = AutoModel.from_pretrained(model_id, torch_dtype=torch.float16, device_map="auto")
        except Exception as e2:
            logger.error(f"Failed to load model {model_id} with float16: {e2}. Giving up.")
            raise e2


    logger.info(f"Model {model_id} loaded successfully.")
    model.eval()
    return tokenizer, model

# --- Embedding Generation for multilingual-e5-large ---
def average_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    last_hidden = last_hidden_states.masked_fill(~attention_mask[..., None].bool(), 0.0)
    return last_hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]

def get_embeddings_e5(texts: List[str], tokenizer, model) -> np.ndarray:
    """
    Generates embeddings for a list of texts using multilingual-e5-large.
    Input texts should already be prefixed with "query: " or "passage: ".
    """
    if not texts:
        logger.warning("Attempted to embed an empty list of texts.")
        return np.array([])

    batch_dict = tokenizer(texts, max_length=512, padding=True, truncation=True, return_tensors='pt')
    # Move batch_dict to the same device as the model
    batch_dict = {key: val.to(model.device) for key, val in batch_dict.items()}

    with torch.no_grad():
        outputs = model(**batch_dict)
    
    embeddings = average_pool(outputs.last_hidden_state, batch_dict['attention_mask'])
    # Normalize embeddings
    embeddings = F.normalize(embeddings, p=2, dim=1)
    return embeddings.cpu().numpy()


# --- Document Chunking ---
def chunk_plain_text(text_content: str, min_chunk_chars: int = 200, max_chunk_chars: int = 1500) -> List[str]:
    """
    Chunks plain text, preferring paragraph breaks, then sentences.
    Tries to keep chunks within min_chunk_chars and max_chunk_chars.
    """
    if not text_content or not text_content.strip():
        return []

    chunks = []
    # Split by double line breaks (paragraphs)
    raw_paragraphs = re.split(r'\\n\\s*\\n+', text_content.strip())
    
    current_chunk = ""
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 1 < max_chunk_chars:
            current_chunk += (" " + para if current_chunk else para)
        else:
            # If current_chunk is too small, try to extend with sentences from this paragraph
            if len(current_chunk) < min_chunk_chars and current_chunk:
                sentences = re.split(r'(?<=[.!?])\\s+', para) # Basic sentence split
                for sent in sentences:
                    sent = sent.strip()
                    if not sent: continue
                    if len(current_chunk) + len(sent) + 1 < max_chunk_chars:
                        current_chunk += (" " + sent)
                    else:
                        if current_chunk and len(current_chunk) >= min_chunk_chars: chunks.append(current_chunk)
                        current_chunk = sent if len(sent) < max_chunk_chars else sent[:max_chunk_chars] # start new or take truncated
                if current_chunk and len(current_chunk) >= min_chunk_chars : chunks.append(current_chunk) # last part of paragraph
                current_chunk = ""


            else: # Current chunk is good sized or paragraph itself is too large
                 if current_chunk and len(current_chunk) >= min_chunk_chars: chunks.append(current_chunk)
                 # Handle the new paragraph that didn't fit
                 if len(para) >= min_chunk_chars:
                     # If paragraph itself is too long, split it further
                     if len(para) > max_chunk_chars:
                         sentences = re.split(r'(?<=[.!?])\\s+', para)
                         temp_sub_chunk = ""
                         for sent in sentences:
                             sent = sent.strip()
                             if not sent: continue
                             if len(temp_sub_chunk) + len(sent) + 1 < max_chunk_chars:
                                 temp_sub_chunk += (" " + sent if temp_sub_chunk else sent)
                             else:
                                 if temp_sub_chunk and len(temp_sub_chunk) >= min_chunk_chars: chunks.append(temp_sub_chunk)
                                 temp_sub_chunk = sent
                         if temp_sub_chunk and len(temp_sub_chunk) >= min_chunk_chars: chunks.append(temp_sub_chunk) # last sentence group
                         current_chunk = ""
                     else:
                         chunks.append(para)
                         current_chunk = ""
                 else: # Paragraph is too small to be its own chunk
                     current_chunk = para # Start new chunk with this small para


    if current_chunk and len(current_chunk) >= min_chunk_chars: # Add any remaining chunk
        chunks.append(current_chunk)
    
    # Fallback: if no chunks produced and there was content, use fixed size (very basic)
    if not chunks and text_content.strip():
        logger.warning("Paragraph/sentence chunking produced no results, falling back to fixed size window.")
        content_len = len(text_content)
        step = (min_chunk_chars + max_chunk_chars) // 2
        for i in range(0, content_len, step):
            chunk = text_content[i:i+max_chunk_chars].strip()
            if len(chunk) >= min_chunk_chars:
                chunks.append(chunk)
    
    logger.info(f"Chunked document into {len(chunks)} segments.")
    return [c for c in chunks if c] # Ensure no empty strings

# --- Database Interaction ---
def fetch_sample_article_with_consultation_id(db_path: str) -> Dict[str, Any] | None:
    logger.info(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, content_cleaned, consultation_id
        FROM articles 
        WHERE content_cleaned IS NOT NULL AND content_cleaned != '' AND consultation_id IS NOT NULL
        ORDER BY id ASC 
        LIMIT 1
    """)
    article_row = cursor.fetchone()
    conn.close()
    
    if article_row:
        logger.info(f"Fetched article ID: {article_row[0]}, Title: {article_row[1][:60]}..., Consultation ID: {article_row[3]}")
        return {"id": article_row[0], "title": article_row[1], "content_cleaned": article_row[2], "consultation_id": article_row[3]}
    else:
        logger.warning("No suitable article with a consultation_id found in the database.")
        return None

def fetch_consultation_documents(consultation_id: int, db_path: str) -> List[Dict[str, Any]]:
    logger.info(f"Fetching documents for consultation ID: {consultation_id} from {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Fetch documents that have cleaned content
    cursor.execute("""
        SELECT id, title, content_cleaned, type, url
        FROM documents
        WHERE consultation_id = ? AND content_cleaned IS NOT NULL AND content_cleaned != ''
    """, (consultation_id,))
    docs_data = cursor.fetchall()
    conn.close()
    
    documents = []
    for row in docs_data:
        documents.append({
            "id": row[0],
            "title": row[1],
            "content_cleaned": row[2],
            "type": row[3],
            "url": row[4]
        })
    logger.info(f"Fetched {len(documents)} documents for consultation ID {consultation_id}.")
    return documents

# --- Main Test Logic ---
def main():
    logger.info(f"Starting RAG embedding test with {MODEL_ID}...")

    tokenizer, model = load_model_and_tokenizer(MODEL_ID)

    # 1. Fetch a sample article to use its title as the query basis
    article_data = fetch_sample_article_with_consultation_id(DB_PATH)
    if not article_data:
        logger.error("Could not fetch a sample article with consultation_id. Exiting.")
        return

    article_id = article_data["id"]
    article_title = article_data["title"]
    consultation_id = article_data["consultation_id"]

    logger.info(f"Using Article ID: {article_id} (Consultation ID: {consultation_id}) - Title: '{article_title}' as query basis.")

    # 2. Fetch all (relevant) documents for this article's consultation
    consultation_documents = fetch_consultation_documents(consultation_id, DB_PATH)
    if not consultation_documents:
        logger.warning(f"No supporting documents found for consultation ID {consultation_id}. Test might be limited.")
        # We can still proceed to see if the query alone gets embedded, or exit if that's preferred.
        # For now, let's allow it to proceed and potentially find no relevant passages.
    
    # 3. Chunk the content of these documents to create "passages"
    all_passage_chunks_with_meta = []
    for doc in consultation_documents:
        doc_content = doc["content_cleaned"]
        doc_id = doc["id"]
        doc_title = doc["title"]
        doc_type = doc["type"]
        doc_url = doc["url"]
        
        chunks = chunk_plain_text(doc_content) # Using the new generic chunker
        for i, chunk_text in enumerate(chunks):
            all_passage_chunks_with_meta.append({
                "text": chunk_text,
                "doc_id": doc_id,
                "doc_title": doc_title,
                "doc_type": doc_type,
                "doc_url": doc_url,
                "chunk_order_in_doc": i
            })
    
    if not all_passage_chunks_with_meta:
        logger.error(f"No passage chunks could be generated from documents for consultation {consultation_id}. Cannot proceed with similarity search.")
        # Write an empty context file for clarity
        with open(OUTPUT_CONTEXT_FILE, 'w', encoding='utf-8') as f:
            f.write(f"Test RAG Context Building with Model: {MODEL_ID}\\n")
            f.write(f"Source Article ID for Query: {article_id}\\n")
            f.write(f"Article Title (used as query basis): {article_title}\\n")
            f.write(f"Consultation ID: {consultation_id}\\n")
            f.write("="*80 + "\\n")
            f.write(f"NO DOCUMENT CHUNKS FOUND OR GENERATED FOR CONSULTATION ID {consultation_id}.\\n")
        logger.info(f"Empty context file written to {OUTPUT_CONTEXT_FILE}.")
        return

    logger.info(f"Generated a total of {len(all_passage_chunks_with_meta)} passage chunks from {len(consultation_documents)} documents.")

    # 4. Prepare texts for embedding (query + all passages)
    query_text_e5 = f"query: {article_title}"
    passage_texts_e5 = [f"passage: {item['text']}" for item in all_passage_chunks_with_meta]
    
    all_texts_to_embed = [query_text_e5] + passage_texts_e5
    logger.info(f"Total texts to embed: {len(all_texts_to_embed)} (1 query, {len(passage_texts_e5)} passages)")

    # 5. Generate embeddings
    all_embeddings = get_embeddings_e5(all_texts_to_embed, tokenizer, model)
    
    query_embedding = all_embeddings[0].reshape(1, -1) # First embedding is the query
    passage_embeddings = all_embeddings[1:]          # The rest are passages
    
    logger.info(f"Embeddings generated. Query shape: {query_embedding.shape}, Passages shape: {passage_embeddings.shape if passage_embeddings.ndim > 1 else 'N/A or 0 passages'}")

    if passage_embeddings.ndim == 1 and passage_embeddings.shape[0] == 0 : # No passage embeddings
         logger.warning("No passage embeddings were generated. Cannot compute similarity.")
         # This case should be caught by the earlier check for all_passage_chunks_with_meta, but as a safeguard:
         with open(OUTPUT_CONTEXT_FILE, 'w', encoding='utf-8') as f:
            f.write(f"Test RAG Context Building with Model: {MODEL_ID}\\n")
            f.write(f"Source Article ID for Query: {article_id}\\n")
            f.write(f"Article Title (used as query basis): {article_title}\\n")
            f.write(f"Consultation ID: {consultation_id}\\n")
            f.write(f"Query Text for E5: {query_text_e5}\\n")
            f.write("="*80 + "\\n")
            f.write("Query was embedded, but NO PASSAGE CHUNKS from documents were available or embeddable.\\n")
         logger.info(f"Context file (no passages) written to {OUTPUT_CONTEXT_FILE}.")
         return


    # 6. Calculate cosine similarity
    similarities = cosine_similarity(query_embedding, passage_embeddings)
    similarities_flat = similarities[0]

    # 7. Identify top N relevant passage chunks
    top_n = 5 # Number of top relevant document chunks to retrieve
    sorted_passage_indices = np.argsort(similarities_flat)[::-1]
    
    relevant_passages_info = []
    logger.info(f"Top {top_n} relevant document chunks for article title query \'{article_title}\':")
    for i in range(min(top_n, len(sorted_passage_indices))):
        idx = sorted_passage_indices[i]
        similarity_score = similarities_flat[idx]
        passage_meta = all_passage_chunks_with_meta[idx] # Get the corresponding metadata
        
        logger.info(f"  Rank {i+1}: Doc.Chunk Original Index {idx}, Similarity: {similarity_score:.4f}")
        logger.info(f"    Source Doc ID: {passage_meta['doc_id']}, Title: {passage_meta['doc_title'][:50]}...")
        logger.info(f"    Chunk Text: {passage_meta['text'][:150]}...")
        relevant_passages_info.append({
            "rank": i + 1,
            "original_passage_index": idx,
            "similarity": similarity_score,
            "text": passage_meta['text'],
            "doc_id": passage_meta['doc_id'],
            "doc_title": passage_meta['doc_title'],
            "doc_type": passage_meta['doc_type'],
            "doc_url": passage_meta['doc_url']
        })

    # 8. Write the query and relevant document chunks to a .txt file
    logger.info(f"Writing context to {OUTPUT_CONTEXT_FILE}...")
    with open(OUTPUT_CONTEXT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"Test RAG Context Building with Model: {MODEL_ID}\\n")
        f.write(f"Source Article ID for Query: {article_id}\\n")
        f.write(f"Article Title (used as query basis): {article_title}\\n")
        f.write(f"Consultation ID: {consultation_id}\\n")
        f.write(f"Query Text for E5: {query_text_e5}\\n")
        f.write("="*80 + "\\n\\n")
        f.write(f"TOP {top_n} RELEVANT DOCUMENT CHUNKS (Passages) for the Article Title:\\n\\n")
        
        if not relevant_passages_info:
            f.write("No relevant document chunks found meeting similarity criteria or available.\n")
        else:
            for info in relevant_passages_info:
                f.write(f"--- Rank {info['rank']} | Similarity: {info['similarity']:.4f} | Original Passage Index: {info['original_passage_index']} ---\\n")
                f.write(f"Source Document ID: {info['doc_id']}\\n")
                f.write(f"Document Title: {info['doc_title']}\\n")
                f.write(f"Document Type: {info['doc_type']}\\n")
                f.write(f"Document URL: {info['doc_url']}\\n")
                f.write("Passage Text:\\n")
                f.write(info['text'] + "\\n")
                f.write("-"*(len(f"--- Rank {info['rank']}...")) + "\\n\\n")
            
    logger.info(f"Context written to {OUTPUT_CONTEXT_FILE}. Test complete.")

if __name__ == "__main__":
    main() 