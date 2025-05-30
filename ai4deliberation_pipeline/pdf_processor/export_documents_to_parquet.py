#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export non-law_draft documents from the database to a parquet file.

This script queries the database for all documents that are not law_drafts,
extracts their information, and exports them to a parquet file that can be
processed by the GlossAPI pipeline.
"""

import os
import sys
import pandas as pd
import sqlite3
import logging
from pathlib import Path

# Create directory if it doesn't exist
os.makedirs('/mnt/data/AI4Deliberation/pdf_pipeline', exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/mnt/data/AI4Deliberation/pdf_pipeline/export_log.txt')
    ]
)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)
try:
    from complete_scraper.db_models import init_db, Document, Consultation
    from master_pipeline.utils import load_config
except ImportError:
    logger.error("Failed to import database models. Make sure the parent directory is in the path.")
    sys.exit(1)

# Constants
config = load_config()
DATABASE_PATH = config['database']['default_path']  # Using path from config
WORKSPACE_DIR = '/mnt/data/AI4Deliberation/pdf_pipeline/workspace'
OUTPUT_PARQUET = os.path.join(WORKSPACE_DIR, 'documents.parquet')

# Create workspace directory if it doesn't exist
os.makedirs(WORKSPACE_DIR, exist_ok=True)

def export_non_law_draft_documents():
    """
    Export all non-law_draft documents from the database to a parquet file.
    Only exports documents that don't already have content or have bad extraction quality.
    
    NOTE: law_draft documents are intentionally excluded because they contain laws
    that are already extracted from HTML sources and do not need PDF processing.
    We only process 'analysis', 'other', and other document types that contain
    unique content not available elsewhere.
    """
    # Check if we should use SQLAlchemy or direct SQLite connection
    use_sqlalchemy = True
    try:
        # Try SQLAlchemy approach first
        engine, Session = init_db(f'sqlite:///{DATABASE_PATH}')
        session = Session()
    except Exception as e:
        logger.warning(f"Failed to initialize database with SQLAlchemy: {e}")
        logger.info("Falling back to direct SQLite connection")
        use_sqlalchemy = False
    
    documents = []
    
    try:
        if use_sqlalchemy:
            # Use SQLAlchemy query
            query = session.query(
                Document.id, Document.url, Document.type, Document.consultation_id, 
                Document.extraction_quality, Document.content
            ).filter(Document.type != 'law_draft')
            
            for doc in query:
                # Include documents that don't have extraction_quality
                if doc.extraction_quality is None:
                    documents.append({
                        'document_id': doc.id,
                        'initial_url': doc.url,
                        'type': doc.type,
                        'consultation_id': doc.consultation_id
                    })
            
            session.close()
        else:
            # Use direct SQLite connection
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            # Find if content and extraction_quality columns exist
            cursor.execute("PRAGMA table_info(documents)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'content' in columns and 'extraction_quality' in columns:
                # Query for documents that don't have extraction_quality
                cursor.execute("""
                    SELECT id, url, type, consultation_id, extraction_quality, content
                    FROM documents
                    WHERE type != 'law_draft'
                """)
                
                for row in cursor.fetchall():
                    doc_id, url, doc_type, cons_id, quality, content = row
                    # Include documents that don't have extraction_quality
                    if quality is None:
                        documents.append({
                            'document_id': doc_id,
                            'initial_url': url,
                            'type': doc_type,
                            'consultation_id': cons_id
                        })
            else:
                # If columns don't exist, just get all non-law_draft documents
                cursor.execute("""
                    SELECT id, url, type, consultation_id
                    FROM documents
                    WHERE type != 'law_draft'
                """)
                
                for row in cursor.fetchall():
                    doc_id, url, doc_type, cons_id = row
                    documents.append({
                        'document_id': doc_id,
                        'initial_url': url,
                        'type': doc_type,
                        'consultation_id': cons_id
                    })
            
            conn.close()
        
        # Create DataFrame and export to parquet
        if documents:
            df = pd.DataFrame(documents)
            logger.info(f"Found {len(df)} non-law_draft documents to process")
            
            # Count by type for logging
            type_counts = df['type'].value_counts().to_dict()
            for doc_type, count in type_counts.items():
                logger.info(f"  {doc_type}: {count} documents ({count/len(df)*100:.1f}%)")
            
            # Export to parquet
            df.to_parquet(OUTPUT_PARQUET, index=False)
            logger.info(f"Successfully exported {len(df)} documents to {OUTPUT_PARQUET}")
            return df
        else:
            logger.warning("No documents found to process")
            return None
    except Exception as e:
        logger.error(f"Error exporting documents: {e}")
        if use_sqlalchemy and 'session' in locals():
            session.close()
        return None

def main():
    """Main entry point"""
    logger.info("Starting document export process")
    df = export_non_law_draft_documents()
    
    if df is not None and not df.empty:
        logger.info("Export complete")
        logger.info(f"Next steps: Run the URL redirect handler to resolve the URLs in {OUTPUT_PARQUET}")
    else:
        logger.error("Export failed or no documents to process")

if __name__ == "__main__":
    main()
