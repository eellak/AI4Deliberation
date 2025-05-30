#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Process PDFs using GlossAPI for the AI4Deliberation project.

This script uses the GlossAPI Corpus class to:
1. Download PDFs from redirected URLs
2. Extract text content from the PDFs
3. Assess extraction quality
4. Generate metadata for database updating
"""

import os
import sys
import time
import logging
import argparse
import pandas as pd
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/mnt/data/AI4Deliberation/pdf_pipeline/glossapi_log.txt')
    ]
)
logger = logging.getLogger(__name__)

# Add GlossAPI to path if needed
try:
    from glossapi.corpus import Corpus
except ImportError:
    logger.warning("GlossAPI not found in current environment. Attempting to add to path...")
    # Add glossapi to path if installed in a specific location
    glossapi_path = "/mnt/data/glossapi"
    if os.path.exists(glossapi_path):
        sys.path.append(glossapi_path)
        try:
            from glossapi.corpus import Corpus
            logger.info("Successfully imported GlossAPI from custom path")
        except ImportError:
            logger.error("Failed to import GlossAPI from custom path")
            sys.exit(1)
    else:
        logger.error("GlossAPI not found. Please install it or update PYTHONPATH")
        sys.exit(1)

# Constants
WORKSPACE_DIR = '/mnt/data/AI4Deliberation/pdf_pipeline/workspace'
PARQUET_FILE = os.path.join(WORKSPACE_DIR, 'documents.parquet')

# Create workspace directory if it doesn't exist
os.makedirs(WORKSPACE_DIR, exist_ok=True)

def process_pdfs(num_threads=15, disable_sectioning=False):
    """
    Use GlossAPI to download PDFs, extract text, and generate metadata.
    
    Args:
        num_threads: Number of threads to use for PDF extraction (default: 15)
        disable_sectioning: Whether to skip the document sectioning step (default: False)
    """
    logger.info("Starting PDF processing with GlossAPI")
    
    # Check if input parquet exists
    if not os.path.exists(PARQUET_FILE):
        logger.error(f"Input parquet file not found: {PARQUET_FILE}")
        logger.info("Please run export_documents_to_parquet.py and process_document_redirects.py first")
        return
    
    try:
        # Read input parquet
        df = pd.read_parquet(PARQUET_FILE)
        logger.info(f"Loaded {len(df)} documents from {PARQUET_FILE}")
        
        # Save the document IDs mapping file in the same workspace for later use
        id_mapping_file = os.path.join(WORKSPACE_DIR, 'document_id_mapping.parquet')
        id_mapping_df = df[['document_id', 'redirected_url']]
        id_mapping_df.to_parquet(id_mapping_file, index=False)
        logger.info(f"Saved document ID mapping to {id_mapping_file}")
        
        # Create GlossAPI Corpus object
        logger.info("Creating GlossAPI Corpus object")
        corpus = Corpus(
            input_dir=WORKSPACE_DIR,
            output_dir=WORKSPACE_DIR,
            verbose=True  # Enable detailed logging
        )
        
        # Download PDFs
        start_time = time.time()
        logger.info("Starting PDF download")
        corpus.download(url_column='redirected_url', verbose=True)
        logger.info(f"Download completed in {time.time() - start_time:.1f} seconds")
        
        # Extract text from PDFs
        logger.info(f"Starting text extraction with {num_threads} threads")
        extract_start = time.time()
        corpus.extract(num_threads=num_threads)
        logger.info(f"Extraction completed in {time.time() - extract_start:.1f} seconds")
        
        # Optional: Section the documents (if not disabled)
        if not disable_sectioning:
            try:
                logger.info("Starting document sectioning")
                section_start = time.time()
                corpus.section()
                logger.info(f"Sectioning completed in {time.time() - section_start:.1f} seconds")
            except Exception as e:
                logger.warning(f"Sectioning failed: {e}")
        else:
            logger.info("Document sectioning disabled - skipping this step")
        
        # Check results
        download_results_file = os.path.join(WORKSPACE_DIR, 'download_results', 'download_results.parquet')
        if os.path.exists(download_results_file):
            results_df = pd.read_parquet(download_results_file)
            logger.info(f"Downloaded {len(results_df)} documents")
            
            # Log statistics about download results
            success_count = results_df[results_df['extraction'] == 'good'].shape[0]
            bad_count = results_df[results_df['extraction'] == 'bad'].shape[0]
            error_count = results_df[results_df['extraction'] == 'unknown'].shape[0]
            
            logger.info(f"Extraction statistics:")
            logger.info(f"  Good: {success_count} ({success_count/len(results_df)*100:.1f}%)")
            logger.info(f"  Bad: {bad_count} ({bad_count/len(results_df)*100:.1f}%)")
            logger.info(f"  Errors: {error_count} ({error_count/len(results_df)*100:.1f}%)")
            
            # Check markdown directory
            markdown_dir = os.path.join(WORKSPACE_DIR, 'markdown')
            if os.path.exists(markdown_dir):
                markdown_files = [f for f in os.listdir(markdown_dir) if f.endswith('.md')]
                logger.info(f"Found {len(markdown_files)} markdown files")
            else:
                logger.warning("Markdown directory not found")
        else:
            logger.warning("Download results file not found")
        
        logger.info("PDF processing with GlossAPI complete")
        logger.info(f"Files are available in {WORKSPACE_DIR}")
        logger.info("Next step: Run update_database_with_content.py to update the database")
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing PDFs: {e}")
        return False

def main():
    """Main entry point"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Process PDFs with GlossAPI')
    parser.add_argument('--threads', type=int, default=15, 
                       help='Number of threads to use for PDF extraction (default: 15)')
    parser.add_argument('--disable-sectioning', action='store_true',
                       help='Disable document sectioning step')
    args = parser.parse_args()
    
    # Run the PDF processing with parsed arguments
    success = process_pdfs(num_threads=args.threads, disable_sectioning=args.disable_sectioning)
    
    if success:
        logger.info("PDF processing completed successfully")
    else:
        logger.error("PDF processing failed")

if __name__ == "__main__":
    main()
