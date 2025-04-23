#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Update the AI4Deliberation database with content extracted from PDF files.

This script reads the GlossAPI extraction results, matches documents by ID,
and updates the database with both the content and extraction quality metrics.
"""

import os
import sys
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
        logging.FileHandler('/mnt/data/AI4Deliberation/pdf_pipeline/update_log.txt')
    ]
)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)
try:
    from complete_scraper.db_models import init_db, Document
except ImportError:
    logger.warning("Failed to import database models. Will use direct SQLite connection.")

# Constants
DATABASE_PATH = os.path.join(parent_dir, 'deliberation_data_gr_test.db')  # Using test database
WORKSPACE_DIR = '/mnt/data/AI4Deliberation/pdf_pipeline/workspace'
DOWNLOAD_RESULTS = os.path.join(WORKSPACE_DIR, 'download_results', 'download_results.parquet')
ID_MAPPING = os.path.join(WORKSPACE_DIR, 'document_id_mapping.parquet')
MARKDOWN_DIR = os.path.join(WORKSPACE_DIR, 'markdown')

# Create workspace directory if it doesn't exist
os.makedirs(WORKSPACE_DIR, exist_ok=True)

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
    
    # Check if required files exist
    if not os.path.exists(DOWNLOAD_RESULTS):
        logger.error(f"Download results file not found: {DOWNLOAD_RESULTS}")
        logger.info("Please run process_pdfs_with_glossapi.py first")
        return False
        
    if not os.path.exists(ID_MAPPING):
        logger.error(f"Document ID mapping file not found: {ID_MAPPING}")
        logger.info("Please run process_pdfs_with_glossapi.py first")
        return False
        
    if not os.path.exists(MARKDOWN_DIR):
        logger.error(f"Markdown directory not found: {MARKDOWN_DIR}")
        logger.info("Please run process_pdfs_with_glossapi.py first")
        return False
        
    if not os.path.exists(DATABASE_PATH):
        logger.error(f"Database file not found: {DATABASE_PATH}")
        return False
    
    # Connect to the database
    try:
        # Try SQLAlchemy approach first
        use_sqlalchemy = True
        try:
            engine, Session = init_db(f'sqlite:///{DATABASE_PATH}')
            session = Session()
            logger.info("Connected to database using SQLAlchemy")
        except Exception as e:
            logger.warning(f"Failed to initialize database with SQLAlchemy: {e}")
            logger.info("Falling back to direct SQLite connection")
            use_sqlalchemy = False
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            logger.info("Connected to database using SQLite")
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        return False
    
    try:
        # Read the download results and ID mapping
        results_df = pd.read_parquet(DOWNLOAD_RESULTS)
        mapping_df = pd.read_parquet(ID_MAPPING)
        logger.info(f"Read {len(results_df)} download results and {len(mapping_df)} document mappings")
        
        # Print column names for debugging
        logger.info(f"Results DataFrame columns: {results_df.columns.tolist()}")
        logger.info(f"Mapping DataFrame columns: {mapping_df.columns.tolist()}")
        
        # Ensure column names align before merging
        # GlossAPI might have renamed redirected_url to url in its output
        results_url_col = 'url' if 'url' in results_df.columns else 'redirected_url'
        mapping_url_col = 'redirected_url' if 'redirected_url' in mapping_df.columns else 'url'
        
        # Print sample data for debugging
        logger.info(f"Results DataFrame sample (first row): {results_df.iloc[0].to_dict() if not results_df.empty else 'Empty'}")
        logger.info(f"Mapping DataFrame sample (first row): {mapping_df.iloc[0].to_dict() if not mapping_df.empty else 'Empty'}")
        
        # Merge the results with document IDs using the correct column names
        merged_df = results_df.merge(mapping_df, left_on=results_url_col, right_on=mapping_url_col, how='left')
        logger.info(f"Merged dataframes, got {len(merged_df)} records")
        logger.info(f"Merged DataFrame columns: {merged_df.columns.tolist()}")
        
        # Rename the document_id column from mapping dataframe to avoid confusion
        # Both dataframes have document_id, so in the merged df they become document_id_x and document_id_y
        # We want to use document_id_y from mapping_df as our document_id
        merged_df['document_id'] = merged_df['document_id_y']
        logger.info(f"After renaming, columns: {merged_df.columns.tolist()}")
        
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
        
        # Process each row in the merged dataframe
        for index, row in merged_df.iterrows():
            if pd.isna(row['document_id']):
                logger.warning(f"No document ID found for URL: {row['redirected_url']}")
                continue
                
            document_id = int(row['document_id'])  # Now using the renamed document_id column
            filename = row['filename'] if 'filename' in row and not pd.isna(row['filename']) else ''
            
            # Skip if filename is empty
            if not filename:
                logger.warning(f"No filename for document ID {document_id}")
                continue
            
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
                        if use_sqlalchemy:
                            document = session.query(Document).filter(Document.id == document_id).first()
                            if document:
                                document.content = content
                                document.extraction_quality = extraction_quality
                                update_count += 1
                                if update_count % 50 == 0:
                                    logger.info(f"Updated {update_count} documents so far")
                                    session.commit()  # Commit in batches
                            else:
                                logger.warning(f"No document found with ID {document_id}")
                        else:
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
                    if row['extraction'] == 'unknown' and (
                        'download_error' in row and not pd.isna(row['download_error'])
                    ):
                        if use_sqlalchemy:
                            document = session.query(Document).filter(Document.id == document_id).first()
                            if document:
                                document.extraction_quality = extraction_quality
                                error_message_count += 1
                        else:
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
        if use_sqlalchemy:
            session.commit()
        else:
            conn.commit()
        
        # Log summary
        logger.info(f"Update complete: Successfully updated {update_count} documents with content and extraction quality")
        logger.info(f"Documents with error messages only (no content): {error_message_count}")
        logger.info(f"Errors encountered: {error_count}")
        
        # Close connection
        if use_sqlalchemy:
            session.close()
        else:
            conn.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Error updating documents: {e}")
        logger.error(f"Error details: {str(e.__class__.__name__)} - {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        if use_sqlalchemy and 'session' in locals():
            session.close()
        elif 'conn' in locals():
            conn.close()
        return False

def verify_updates():
    """Verify that documents were successfully updated with content."""
    
    try:
        # Connect to the database
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Check if content and extraction_quality columns exist
        cursor.execute("PRAGMA table_info(documents)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'content' not in columns or 'extraction_quality' not in columns:
            logger.error("Database schema missing content or extraction_quality columns")
            conn.close()
            return False
        
        # Count documents with content
        cursor.execute("SELECT COUNT(*) FROM documents WHERE content IS NOT NULL AND content != ''")
        content_count = cursor.fetchone()[0]
        
        # Count documents with extraction quality
        cursor.execute("SELECT COUNT(*) FROM documents WHERE extraction_quality IS NOT NULL")
        quality_count = cursor.fetchone()[0]
        
        # Count documents by extraction quality
        cursor.execute("SELECT extraction_quality, COUNT(*) FROM documents WHERE extraction_quality IS NOT NULL GROUP BY extraction_quality")
        quality_counts = cursor.fetchall()
        
        # Count total documents
        cursor.execute("SELECT COUNT(*) FROM documents")
        total_count = cursor.fetchone()[0]
        
        # Log statistics
        logger.info("\nDatabase statistics after update:")
        logger.info(f"Total documents: {total_count}")
        logger.info(f"Documents with content: {content_count} ({content_count/total_count*100:.1f}%)")
        logger.info(f"Documents with extraction quality: {quality_count} ({quality_count/total_count*100:.1f}%)")
        
        logger.info("Extraction quality breakdown:")
        for quality, count in quality_counts:
            logger.info(f"  {quality}: {count} ({count/quality_count*100:.1f}%)")
        
        # Sample a few documents with content
        cursor.execute("""
            SELECT id, type, extraction_quality, LENGTH(content) AS content_length 
            FROM documents 
            WHERE content IS NOT NULL AND content != '' 
            ORDER BY RANDOM() 
            LIMIT 5
        """)
        samples = cursor.fetchall()
        
        if samples:
            logger.info("\nSample documents with content:")
            for doc_id, doc_type, quality, length in samples:
                logger.info(f"  Document ID: {doc_id}, Type: {doc_type}, Quality: {quality}, Content Length: {length} chars")
        
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error verifying updates: {e}")
        if 'conn' in locals():
            conn.close()
        return False

def main():
    """Main entry point"""
    logger.info("Starting database update process")
    
    success = update_documents_with_content()
    
    if success:
        logger.info("Database update successful")
        verify_updates()
    else:
        logger.error("Database update failed")

if __name__ == "__main__":
    main()
