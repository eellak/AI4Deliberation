#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Set up test data for the PDF processing pipeline by:
1. Finding consultations with non-law_draft documents that have content
2. Clearing the content and extraction_quality for these documents
3. Outputting the document IDs for verification
"""

import os
import sqlite3
import logging
import random

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Use the test database
DATABASE_PATH = '/mnt/data/AI4Deliberation/deliberation_data_gr_test.db'

def setup_test_data():
    """
    Find consultations with documents, select 2 consultations,
    and clear content and extraction_quality for their documents.
    """
    # Connect to the database
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Check if content and extraction_quality columns exist
    cursor.execute("PRAGMA table_info(documents)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'content' not in columns or 'extraction_quality' not in columns:
        logger.error("Database schema missing content or extraction_quality columns")
        conn.close()
        return
    
    # Find consultations with non-law_draft documents that have content
    cursor.execute("""
        SELECT DISTINCT c.id, c.title, COUNT(d.id) as doc_count
        FROM consultations c
        JOIN documents d ON c.id = d.consultation_id
        WHERE d.type != 'law_draft' 
        AND d.content IS NOT NULL 
        AND d.content != ''
        GROUP BY c.id
        HAVING doc_count > 0
        ORDER BY doc_count DESC
        LIMIT 10
    """)
    
    consultations = cursor.fetchall()
    if not consultations:
        logger.error("No consultations found with non-law_draft documents that have content")
        conn.close()
        return
    
    logger.info(f"Found {len(consultations)} candidate consultations")
    for i, (cons_id, title, doc_count) in enumerate(consultations):
        logger.info(f"{i+1}. Consultation ID: {cons_id}, Documents: {doc_count}, Title: {title[:50]}...")
    
    # Randomly select 2 consultations for testing
    if len(consultations) >= 2:
        selected_consultations = random.sample(consultations, 2)
    else:
        selected_consultations = consultations
    
    affected_docs = []
    
    # Clear content and extraction_quality for documents in the selected consultations
    for cons_id, title, _ in selected_consultations:
        logger.info(f"\nClearing document content for consultation ID {cons_id}: {title[:50]}...")
        
        # Get document details before clearing
        cursor.execute("""
            SELECT id, type, url, extraction_quality, LENGTH(content) as content_length
            FROM documents
            WHERE consultation_id = ? AND type != 'law_draft' AND content IS NOT NULL AND content != ''
        """, (cons_id,))
        
        documents = cursor.fetchall()
        if not documents:
            logger.warning(f"No suitable documents found for consultation {cons_id}")
            continue
        
        logger.info(f"Found {len(documents)} documents to clear for consultation {cons_id}")
        
        # Clear content and extraction_quality for these documents
        affected_ids = [doc[0] for doc in documents]
        cursor.execute("""
            UPDATE documents
            SET content = NULL, extraction_quality = NULL
            WHERE id IN ({})
        """.format(','.join('?' for _ in affected_ids)), affected_ids)
        
        logger.info(f"Cleared content and extraction_quality for {cursor.rowcount} documents")
        
        # Verify the clearing
        cursor.execute("""
            SELECT COUNT(*)
            FROM documents
            WHERE id IN ({}) AND (content IS NOT NULL OR extraction_quality IS NOT NULL)
        """.format(','.join('?' for _ in affected_ids)), affected_ids)
        
        remaining = cursor.fetchone()[0]
        if remaining > 0:
            logger.warning(f"{remaining} documents still have content or extraction_quality")
        else:
            logger.info("All documents successfully cleared")
        
        # Store details for later verification
        for doc in documents:
            doc_id, doc_type, url, quality, length = doc
            affected_docs.append({
                'consultation_id': cons_id,
                'document_id': doc_id,
                'type': doc_type,
                'url': url,
                'original_quality': quality,
                'original_length': length
            })
    
    # Commit changes
    conn.commit()
    
    # Print summary of affected documents
    logger.info("\nSummary of cleared documents:")
    for i, doc in enumerate(affected_docs):
        logger.info(f"{i+1}. Document ID: {doc['document_id']}, Type: {doc['type']}, Original Length: {doc['original_length']}")
    
    # Store document IDs for later verification
    with open('/mnt/data/AI4Deliberation/pdf_pipeline/test_document_ids.txt', 'w') as f:
        f.write("Document IDs cleared for testing:\n")
        for doc in affected_docs:
            f.write(f"ID: {doc['document_id']}, Consultation: {doc['consultation_id']}, Type: {doc['type']}\n")
    
    logger.info(f"\nCleared {len(affected_docs)} documents for testing")
    logger.info("Document IDs saved to /mnt/data/AI4Deliberation/pdf_pipeline/test_document_ids.txt")
    
    # Close connection
    conn.close()

if __name__ == "__main__":
    logger.info("Setting up test data for PDF processing pipeline")
    setup_test_data()
    logger.info("Test data setup complete")
