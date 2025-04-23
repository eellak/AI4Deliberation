#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reset test data for a single consultation by clearing content and extraction_quality
for its documents in the test database.
"""

import os
import sqlite3
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Use the test database
DATABASE_PATH = '/mnt/data/AI4Deliberation/deliberation_data_gr_test.db'

def reset_test_data_for_consultation(consultation_id):
    """
    Clear content and extraction_quality for all documents in a specific consultation.
    """
    # Connect to the database
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Get document details before clearing
    cursor.execute("""
        SELECT id, type, url, extraction_quality, LENGTH(content) as content_length
        FROM documents
        WHERE consultation_id = ? AND type != 'law_draft' AND content IS NOT NULL AND content != ''
    """, (consultation_id,))
    
    documents = cursor.fetchall()
    if not documents:
        logger.warning(f"No suitable documents found for consultation {consultation_id}")
        conn.close()
        return False
    
    logger.info(f"Found {len(documents)} documents to clear for consultation {consultation_id}")
    
    # Log document details
    for i, (doc_id, doc_type, url, quality, length) in enumerate(documents):
        logger.info(f"{i+1}. Document ID: {doc_id}, Type: {doc_type}, Quality: {quality}, Length: {length}")
    
    # Clear content and extraction_quality
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
    
    # Commit changes
    conn.commit()
    
    # Clean up workspace directory if it exists
    workspace_dir = '/mnt/data/AI4Deliberation/pdf_pipeline/workspace'
    if os.path.exists(workspace_dir):
        import shutil
        shutil.rmtree(workspace_dir)
        logger.info(f"Removed existing workspace directory: {workspace_dir}")
    
    # Store document IDs for later verification
    with open('/mnt/data/AI4Deliberation/pdf_pipeline/test_document_ids.txt', 'w') as f:
        f.write(f"Document IDs cleared for testing (Consultation {consultation_id}):\n")
        for doc_id, doc_type, _, _, _ in documents:
            f.write(f"ID: {doc_id}, Type: {doc_type}\n")
    
    logger.info(f"Cleared {len(documents)} documents for testing")
    logger.info("Document IDs saved to /mnt/data/AI4Deliberation/pdf_pipeline/test_document_ids.txt")
    
    # Close connection
    conn.close()
    return True

if __name__ == "__main__":
    # Use consultation ID 553 which we found earlier had documents with content
    CONSULTATION_ID = 553
    logger.info(f"Resetting test data for consultation ID {CONSULTATION_ID}")
    success = reset_test_data_for_consultation(CONSULTATION_ID)
    if success:
        logger.info("Test data reset complete")
    else:
        logger.error("Failed to reset test data")
