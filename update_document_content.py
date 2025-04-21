#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to update the AI4Deliberation database with content from extracted PDF files.

This script reads content from markdown files and updates the corresponding
documents in the database with both the content and extraction quality metrics.
"""

import os
import pandas as pd
import sqlite3
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('document_content_update.log')
    ]
)
logger = logging.getLogger(__name__)

# Paths
DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deliberation_data_gr_updated.db')
PARQUET_PATH = '/mnt/data/glossapi_pdf_download_sample/download_results/download_results.parquet'
MARKDOWN_DIR = '/mnt/data/glossapi_pdf_download_sample/markdown'

def read_markdown_content(filepath):
    """Read content from a markdown file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except Exception as e:
        logger.error(f"Error reading file {filepath}: {e}")
        return None

def get_extraction_quality(row):
    """
    Get extraction quality string from parquet row.
    Returns a string value ('good', 'bad', or the download_error) based on the extraction field.
    """
    if row['extraction'] == 'good':
        return 'good'
    elif row['extraction'] == 'bad':
        return 'bad'
    else:
        # If extraction is unknown, use the download_error value
        if pd.isna(row['download_error']) or row['download_error'] == '':
            return 'unknown'
        else:
            return str(row['download_error'])  # Return the actual error message

def update_documents_with_content():
    """Update document records with content from markdown files and extraction quality."""
    
    # Connect to the database
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Read the parquet file
    try:
        df = pd.read_parquet(PARQUET_PATH)
        logger.info(f"Read {len(df)} records from parquet file")
    except Exception as e:
        logger.error(f"Error reading parquet file: {e}")
        return
    
    # Get list of markdown files
    markdown_files = [f for f in os.listdir(MARKDOWN_DIR) if f.endswith('.md')]
    logger.info(f"Found {len(markdown_files)} markdown files")
    
    # Create a mapping of filenames (without extension) to their full paths
    markdown_map = {
        Path(f).stem: os.path.join(MARKDOWN_DIR, f) for f in markdown_files
    }
    
    # Count successful updates
    update_count = 0
    error_count = 0
    error_message_count = 0  # Count of documents updated with error messages but no content
    
    # Process each row in the parquet file
    for index, row in df.iterrows():
        document_id = row['document_id']
        filename = row['filename']
        
        # Remove file extension to get base name
        base_filename = Path(filename).stem
        extraction_quality = get_extraction_quality(row)
        
        try:
            # Check if we have a corresponding markdown file
            if base_filename in markdown_map:
                markdown_path = markdown_map[base_filename]
                
                # Read the content from the markdown file
                content = read_markdown_content(markdown_path)
                
                if content is not None:
                    # Update the document in the database with content and quality
                    cursor.execute(
                        "UPDATE documents SET content = ?, extraction_quality = ? WHERE id = ?",
                        (content, extraction_quality, document_id)
                    )
                    
                    if cursor.rowcount > 0:
                        update_count += 1
                        if update_count % 50 == 0:
                            logger.info(f"Updated {update_count} documents so far")
                            conn.commit()  # Commit in batches
                    else:
                        logger.warning(f"No document found with ID {document_id}")
            else:
                # Even if we don't have a markdown file, update extraction_quality for documents with errors
                if row['extraction'] == 'unknown' and not pd.isna(row['download_error']):
                    cursor.execute(
                        "UPDATE documents SET extraction_quality = ? WHERE id = ?",
                        (extraction_quality, document_id)
                    )
                    
                    if cursor.rowcount > 0:
                        error_message_count += 1
                    
                logger.warning(f"No markdown file found for {filename} (document_id: {document_id})")
        except Exception as e:
            logger.error(f"Error updating document {document_id}: {e}")
            error_count += 1
    
    # Commit final changes
    conn.commit()
    
    # Log summary
    logger.info(f"Update complete: Successfully updated {update_count} documents with content and extraction quality")
    logger.info(f"Documents with error messages only (no content): {error_message_count}")
    logger.info(f"Errors encountered: {error_count}")
    
    # Close connection
    conn.close()

def verify_updates():
    """Verify that documents were successfully updated with content."""
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Get counts before update
    cursor.execute("SELECT COUNT(*) FROM documents")
    total_documents = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM documents WHERE content IS NOT NULL")
    documents_with_content = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM documents WHERE extraction_quality IS NOT NULL")
    documents_with_quality = cursor.fetchone()[0]
    
    # Get statistics on extraction quality
    cursor.execute("SELECT COUNT(DISTINCT extraction_quality) FROM documents WHERE extraction_quality IS NOT NULL")
    distinct_qualities = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM documents WHERE extraction_quality = 'good'")
    good_quality = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM documents WHERE extraction_quality = 'bad'")
    bad_quality = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM documents WHERE extraction_quality = 'unknown'")
    unknown_quality = cursor.fetchone()[0]
    
    # Get top error messages (excluding standard values)
    cursor.execute("""
        SELECT extraction_quality, COUNT(*) as count 
        FROM documents 
        WHERE extraction_quality NOT IN ('good', 'bad', 'unknown') 
        GROUP BY extraction_quality 
        ORDER BY count DESC 
        LIMIT 5
    """)
    error_messages = cursor.fetchall()
    
    # Print summary
    print("\n=== Update Verification ===")
    print(f"Total documents: {total_documents}")
    print(f"Documents with content: {documents_with_content} ({documents_with_content/total_documents*100:.1f}%)")
    print(f"Documents with extraction quality: {documents_with_quality} ({documents_with_quality/total_documents*100:.1f}%)")
    print("\nExtraction Quality Statistics:")
    print(f"Distinct quality values: {distinct_qualities}")
    print(f"Good quality: {good_quality} documents")
    print(f"Bad quality: {bad_quality} documents")
    print(f"Unknown quality: {unknown_quality} documents")
    
    # Display top error messages if any
    if error_messages:
        print("\nTop error messages:")
        for msg, count in error_messages:
            # Truncate very long error messages
            display_msg = msg if len(msg) < 80 else msg[:77] + '...'
            print(f"  - {display_msg}: {count} documents")
    
    # Sample content preview
    if documents_with_content > 0:
        cursor.execute("SELECT id, title, LENGTH(content), extraction_quality FROM documents WHERE content IS NOT NULL LIMIT 5")
        samples = cursor.fetchall()
        
        print("\nSample documents with content:")
        for sample in samples:
            print(f"ID: {sample[0]}, Title: {sample[1]}, Content Length: {sample[2]} chars, Quality: {sample[3]}")
    
    conn.close()

def main():
    """Main function to update documents with content and verify results."""
    try:
        print("Starting document content update process...")
        update_documents_with_content()
        verify_updates()
        print("Process completed successfully!")
    except Exception as e:
        logger.error(f"Error in main process: {e}")
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
