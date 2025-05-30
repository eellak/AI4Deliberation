#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to display extracted document contents from the AI4Deliberation pipeline
and save them to structured text files.
"""

import sqlite3
import textwrap
import os
import re # For sanitizing filenames
import shutil # For creating/deleting output directory
import argparse # Import argparse

def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Sanitize a string to be a valid filename and truncate if too long."""
    # Remove invalid characters
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', name)
    # Replace multiple spaces/underscores with a single underscore
    name = re.sub(r'[\s_]+', '_', name).strip('_')
    # Truncate if necessary (leaving space for extension if any)
    if len(name) > max_length:
        name = name[:max_length]
    return name

def write_content_to_file(filepath: str, content_dict: dict):
    """Write a dictionary of content sections to a file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        for title, text in content_dict.items():
            f.write(f"========== {title.upper()} ==========\n")
            if isinstance(text, dict): # For nested metadata
                for key, value in text.items():
                    f.write(f"{key}: {value}\n")
            elif isinstance(text, list): # For lists like comments
                 for item in text:
                    if isinstance(item, dict): # e.g. list of comment dicts
                        for k, v in item.items():
                            f.write(f"  {k}: {v}\n")
                        f.write("  ---\n")
                    else:
                        f.write(f"{str(item)}\n")
            elif text is None or str(text).strip() == "":
                f.write("None\n")
            else:
                f.write(f"{str(text)}\n")
            f.write("\n\n")

def show_and_save_contents(db_path: str, consultation_id_to_fetch: int = 1):
    """
    Display extracted document contents from the database and save them to files.
    Creates a folder named 'consultation_results/{consultation_id}_{sanitized_title}'.
    """
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # db_path = os.path.join(script_dir, 'test_pipeline_from_scratch.db') # Comment out or remove hardcoded path
    base_output_dir = os.path.join(script_dir, 'consultation_results')

    print(f"🔍 Reading data for consultation ID {consultation_id_to_fetch} from: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"❌ ERROR: Database not found at {db_path}")
        print("Please run the test_pipeline.py script first to generate the database.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row # Access columns by name
    cursor = conn.cursor()
    
    # Get Consultation Details
    cursor.execute("SELECT * FROM consultations WHERE id = ?", (consultation_id_to_fetch,))
    consultation = cursor.fetchone()

    if not consultation:
        print(f"❌ ERROR: Consultation with ID {consultation_id_to_fetch} not found in the database.")
        conn.close()
        return

    consultation_title_original = consultation['title']
    # Truncate the sanitized title for the directory name to avoid path too long errors
    consultation_title_for_dir = sanitize_filename(consultation_title_original, max_length=100) 
    output_dir = os.path.join(base_output_dir, f"consultation_{consultation['id']}_{consultation_title_for_dir}")
    
    # Create/Recreate output directory
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"💾 Saving output to: {output_dir}")

    # 1. Consultation Metadata File
    consultation_metadata = dict(consultation)
    consultation_metadata['title_original_for_reference'] = consultation_title_original # Keep original for clarity if needed
    consultation_file_path = os.path.join(output_dir, "consultation_metadata.txt")
    write_content_to_file(consultation_file_path, {"Consultation Metadata": consultation_metadata})
    print(f"  📄 Saved consultation metadata to {consultation_file_path}")

    # 2. Article Files
    cursor.execute("SELECT * FROM articles WHERE consultation_id = ? ORDER BY id", (consultation['id'],))
    articles = cursor.fetchall()
    
    print(f"\n📑 Processing {len(articles)} articles...")
    for article in articles:
        article_title_sanitized = sanitize_filename(article['title'], max_length=50)
        article_filename = f"article_{article['id']}_{article_title_sanitized}.txt"
        article_filepath = os.path.join(output_dir, article_filename)
        
        article_content = {
            "Article Metadata": dict(article),
            "Original HTML Content": article['raw_html'],
            "Cleaned Markdown Content": article['content_cleaned']
        }
        
        # Get Comments for this article
        cursor.execute("SELECT * FROM comments WHERE article_id = ? ORDER BY date", (article['id'],))
        comments_data = cursor.fetchall()
        comments_list = [dict(comment) for comment in comments_data]
        article_content["Comments"] = comments_list
        
        write_content_to_file(article_filepath, article_content)
        print(f"    📝 Saved article {article['id']} to {article_filename}")

    # 3. Document Files
    try:
        cursor.execute("""
            SELECT 
                d.id, d.url, d.type, d.title, d.publication_date, 
                d.content, d.content_cleaned, d.extraction_method,
                d.badness_score, d.greek_percentage, d.english_percentage,
                GROUP_CONCAT(DISTINCT dm.key || ': ' || dm.value) as metadata
            FROM documents d
            LEFT JOIN document_metadata dm ON d.id = dm.document_id
            WHERE d.consultation_id = ?
            GROUP BY d.id
            ORDER BY d.id
        """, (consultation['id'],))
        documents = cursor.fetchall()
        # Store the original error 'e' from the try block to check it in the 'with open' block later
        original_error_for_metadata_check = None 
    except sqlite3.OperationalError as e:
        original_error_for_metadata_check = e # Store the error
        if "no such table: document_metadata" in str(e):
            print("   ⚠️ Warning: `document_metadata` table not found. Proceeding without document metadata.")
            cursor.execute("""
                SELECT 
                    d.id, d.url, d.type, d.title, 
                    d.content, d.content_cleaned, d.extraction_method,
                    d.badness_score, d.greek_percentage, d.english_percentage
                FROM documents d
                WHERE d.consultation_id = ?
                GROUP BY d.id
                ORDER BY d.id
            """, (consultation['id'],))
            documents = cursor.fetchall()
        else:
            raise # Re-raise other operational errors

    if not documents:
        print(f"  No documents found for consultation {consultation['id']}.")
    else:
        print(f"  📄 Found {len(documents)} documents:")
        for doc_row in documents:
            doc = dict(doc_row) # Convert row to dict for easier access
            doc_title_for_file = sanitize_filename(doc.get('title') or f"document_{doc['id']}", max_length=100)
            doc_filename = f"document_{doc['id']}_{doc_title_for_file}.txt"
            doc_filepath = os.path.join(output_dir, doc_filename)

            with open(doc_filepath, 'w', encoding='utf-8') as f:
                f.write(f"DOCUMENT ID: {doc['id']}\\n")
                f.write(f"TITLE: {doc.get('title', 'N/A')}\\n")
                f.write(f"URL: {doc.get('url', 'N/A')}\\n")
                f.write(f"TYPE: {doc.get('type', 'N/A')}\\n")
                # Safely try to access publication_date, as it might not exist in all schemas
                if 'publication_date' in doc.keys():
                    f.write(f"PUBLICATION DATE: {doc.get('publication_date', 'N/A')}\\n")
                f.write(f"EXTRACTION METHOD: {doc.get('extraction_method', 'N/A')}\\n")
                f.write(f"BADNESS SCORE: {doc.get('badness_score', 'N/A')}\\n")
                f.write(f"GREEK PERCENTAGE: {doc.get('greek_percentage', 'N/A')}%\\n")
                f.write(f"ENGLISH PERCENTAGE: {doc.get('english_percentage', 'N/A')}%\\n")
                
                # Safely access metadata
                doc_metadata = doc.get('metadata')
                if doc_metadata:
                    f.write("\\n--- METADATA ---\\n")
                    f.write(doc_metadata.replace(',', '\\n')) # Basic formatting for metadata
                # Check if the original error was due to the missing table before deciding to print 'table missing'
                elif original_error_for_metadata_check and "no such table: document_metadata" in str(original_error_for_metadata_check):
                    f.write("\\n--- METADATA ---\\nNo metadata available (table missing).\\n")
                
                f.write("\\n\\n--- ORIGINAL CONTENT ---\\n")
                f.write(textwrap.fill(doc.get('content') or "N/A", width=100))
                f.write("\n\n--- CLEANED CONTENT (Pipeline) ---\n")
                f.write(textwrap.fill(doc.get('content_cleaned') or "N/A", width=100))

            print(f"    📝 Saved document {doc['id']}: {doc.get('title', 'N/A')[:50]}... to {doc_filepath}")
            print(f"       Badness: {doc.get('badness_score', 'N/A')}, Greek %: {doc.get('greek_percentage', 'N/A')}, English %: {doc.get('english_percentage', 'N/A')}")

    conn.close()
    print(f"\n\n✅ All requested data saved to folder: {output_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Display and save consultation contents from the database.")
    parser.add_argument("--db_path", type=str, required=True, help="Path to the SQLite database file.")
    parser.add_argument("--consultation_id", type=int, required=True, help="ID of the consultation to fetch.")
    
    args = parser.parse_args()
    
    show_and_save_contents(db_path=args.db_path, consultation_id_to_fetch=args.consultation_id)