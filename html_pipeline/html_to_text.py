#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract text from HTML content in the articles table using docling.

This script reads articles with raw_html content from the database,
extracts them to text format using docling's batch conversion,
and updates the content field in the database.
"""

import os
import sys
import logging
import argparse
import sqlite3
import tempfile
from pathlib import Path
from tqdm import tqdm
import shutil # Import shutil for file copying

# Docling imports (moved to top level)
try:
    from docling.datamodel.base_models import InputFormat, ConversionStatus
    from docling.document_converter import DocumentConverter, HTMLFormatOption
    DOCLING_AVAILABLE = True
except ImportError as e:
    DOCLING_AVAILABLE = False
    # Log the import error but allow script to potentially run without docling if handled later
    logging.error(f"Failed to import docling components: {e}. Docling functionality will be unavailable.")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('html_extraction.log')
    ]
)
logger = logging.getLogger(__name__)

def extract_articles_from_db(db_path, output_dir, batch_size=100, limit=None):
    """
    Extract articles with HTML content from the database and save to files.
    
    Args:
        db_path: Path to the SQLite database
        output_dir: Directory to save HTML files
        batch_size: Number of articles to process at once
        limit: Maximum number of articles to extract (None for all)
        
    Returns:
        Dict mapping article IDs to HTML file paths
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get count of articles with HTML content
    if limit:
        cursor.execute("SELECT COUNT(*) FROM articles WHERE raw_html IS NOT NULL LIMIT ?", (limit,))
    else:
        cursor.execute("SELECT COUNT(*) FROM articles WHERE raw_html IS NOT NULL")
    total_count = cursor.fetchone()[0]
    logger.info(f"Found {total_count} articles with HTML content")
    
    # Extract articles in batches
    offset = 0
    article_files = {}
    
    while True:
        # Get a batch of articles
        if limit is not None:
            actual_limit = min(batch_size, limit - offset)
            cursor.execute("""
                SELECT id, raw_html 
                FROM articles 
                WHERE raw_html IS NOT NULL 
                LIMIT ? OFFSET ?
            """, (actual_limit, offset))
        else:
            cursor.execute("""
                SELECT id, raw_html 
                FROM articles 
                WHERE raw_html IS NOT NULL 
                LIMIT ? OFFSET ?
            """, (batch_size, offset))
        
        articles = cursor.fetchall()
        if not articles:
            break
            
        logger.info(f"Extracting batch of {len(articles)} articles (offset: {offset})")
        
        # Save each article to a file
        for article_id, raw_html in articles:
            if raw_html:
                file_path = os.path.join(output_dir, f"article_{article_id}.html")
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(raw_html)
                    article_files[article_id] = file_path
                except Exception as e:
                    logger.error(f"Error saving article {article_id}: {e}")
        
        # Update offset for next batch
        offset += len(articles)
        if limit is not None and offset >= limit:
            break
    
    conn.close()
    logger.info(f"Extracted {len(article_files)} HTML files to {output_dir}")
    return article_files

def update_db_with_extracted_content(db_path, article_id_to_text):
    """
    Update the database with extracted text content.
    
    Args:
        db_path: Path to the SQLite database
        article_id_to_text: Dict mapping article IDs to extracted text content
        
    Returns:
        Number of articles updated
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    updated_count = 0
    for article_id, text_content in tqdm(article_id_to_text.items(), desc="Updating database"):
        try:
            cursor.execute(
                "UPDATE articles SET content = ? WHERE id = ?",
                (text_content, article_id)
            )
            updated_count += 1
        except Exception as e:
            logger.error(f"Error updating article {article_id} in database: {e}")
    
    conn.commit()
    conn.close()
    
    logger.info(f"Updated {updated_count} articles in the database")
    return updated_count

def main():
    parser = argparse.ArgumentParser(description="Extract text from HTML content in articles table")
    parser.add_argument("--db-path", default="/mnt/data/AI4Deliberation/deliberation_data_gr_updated_backup.db",
                        help="Path to the SQLite database")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit the number of articles to process")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Number of articles to process in each batch")
    parser.add_argument("--threads", type=int, default=4,
                        help="Number of threads to use for conversion (Note: Currently unused as conversion is serial)")
    parser.add_argument("--quality-check-dir", type=str, default=None,
                        help="Optional directory to save original HTML and extracted text for quality checking.")
    args = parser.parse_args()
    
    # Prepare quality check directory if specified
    quality_check_path = None
    if args.quality_check_dir:
        quality_check_path = Path(args.quality_check_dir)
        try:
            quality_check_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Quality check files will be saved to: {quality_check_path}")
        except OSError as e:
            logger.error(f"Could not create quality check directory {quality_check_path}: {e}. Disabling quality check.")
            quality_check_path = None # Disable if creation fails
            
    # Create a temporary directory for HTML files and conversion output
    with tempfile.TemporaryDirectory() as temp_dir:
        html_dir = os.path.join(temp_dir, "html")
        output_dir = os.path.join(temp_dir, "text")
        
        # Extract HTML files from database
        article_files = extract_articles_from_db(
            args.db_path, 
            html_dir, 
            batch_size=args.batch_size,
            limit=args.limit
        )
        
        if not article_files:
            logger.error("No articles found or extracted. Exiting.")
            return
        
        # Create input and output paths for docling
        input_dir = Path(html_dir)
        output_dir = Path(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info(f"Running docling batch conversion with {args.threads} threads")
        
        # Check if docling was imported successfully
        if not DOCLING_AVAILABLE:
            logger.error("Docling could not be imported. Please check the installation and dependencies.")
            # Optionally, exit or fall back to another method here
            sys.exit(1) # Exit if docling is required

        # Create a document converter with HTML format options
        # Removed specific pipeline_cls, using defaults like gloss_extract.py might
        converter = DocumentConverter(
            allowed_formats=[InputFormat.HTML],
            format_options={
                InputFormat.HTML: HTMLFormatOption() # Simpler instantiation
            }
        )
        logger.info("Created docling DocumentConverter with HTML options")
        
        # Process each HTML file
        for article_id, html_path in tqdm(article_files.items(), desc="Converting HTML to text"):
            try:
                # Output path for this file
                output_path = os.path.join(output_dir, f"article_{article_id}.txt")
                
                # Convert using docling's convert_all method
                # It expects a list of paths and returns a list of ConversionResult objects
                input_path_list = [Path(html_path)]
                conv_results = converter.convert_all(
                    input_path_list,
                    raises_on_error=False # Handle errors based on result status
                )
                
                # Process the result (convert_all returns a generator)
                # Get the single result (or None if the generator is empty)
                result = next(iter(conv_results), None) 
                
                if result:
                    # Now process the single ConversionResult object
                    if result.status == ConversionStatus.SUCCESS:
                        # Extract text content using export_to_markdown()
                        if hasattr(result, 'document') and result.document:
                            try:
                                # Get content as markdown string
                                text_content = result.document.export_to_markdown()
                                if text_content:
                                    # Save to temp text file
                                    with open(output_path, 'w', encoding='utf-8') as f:
                                        f.write(text_content)
                                    logger.debug(f"Successfully converted and saved article {article_id}")
                                    
                                    # --- Quality Check Output --- 
                                    if quality_check_path:
                                        try:
                                            # Define paths in quality check dir
                                            qc_html_path = quality_check_path / f"article_{article_id}_original.html"
                                            qc_text_path = quality_check_path / f"article_{article_id}_extracted.txt"
                                            # Copy original HTML
                                            shutil.copy2(html_path, qc_html_path) 
                                            # Copy extracted text
                                            shutil.copy2(output_path, qc_text_path)
                                        except Exception as qc_err:
                                            logger.error(f"Failed to save quality check files for article {article_id}: {qc_err}")
                                    # --- End Quality Check --- 
                                    
                                else:
                                    logger.warning(f"Conversion successful for article {article_id}, but markdown export was empty.")
                            except Exception as write_err:
                                logger.error(f"Error writing text file for article {article_id}: {write_err}")
                        else:
                            logger.warning(f"Conversion successful for article {article_id}, but no 'document' attribute found in result.")
                    elif result.status == ConversionStatus.PARTIAL_SUCCESS:
                         logger.warning(f"Partial success converting article {article_id}: {result.error_message}")
                         # Decide if partial success text should be saved
                         if hasattr(result, 'document') and result.document:
                             try:
                                 # Get partial content as markdown string
                                 text_content = result.document.export_to_markdown()
                                 if text_content:
                                     # Save partial text to temp file
                                     with open(output_path, 'w', encoding='utf-8') as f:
                                         f.write(text_content)
                                     logger.info(f"Saved partially successful text for article {article_id}")
                                     
                                     # --- Quality Check Output (Partial) --- 
                                     if quality_check_path:
                                         try:
                                             # Define paths in quality check dir
                                             qc_html_path = quality_check_path / f"article_{article_id}_original.html"
                                             qc_text_path = quality_check_path / f"article_{article_id}_partial_extracted.txt" # Note suffix
                                             # Copy original HTML
                                             shutil.copy2(html_path, qc_html_path)
                                             # Copy extracted partial text
                                             shutil.copy2(output_path, qc_text_path)
                                         except Exception as qc_err:
                                             logger.error(f"Failed to save partial quality check files for article {article_id}: {qc_err}")
                                     # --- End Quality Check --- 
                                     
                                 else:
                                      logger.warning(f"Partial conversion for article {article_id}, but markdown export was empty.")
                             except Exception as write_err:
                                 logger.error(f"Error writing partial text file for article {article_id}: {write_err}")
                         else:
                             logger.warning(f"Partial conversion for article {article_id}, but no 'document' attribute found in result.")
                    else: # ConversionStatus.FAILURE
                        logger.error(f"Failed to convert article {article_id}: {result.error_message}")
                else:
                    logger.error(f"No conversion result returned for article {article_id}")
                    
            except Exception as e:
                # Catch any unexpected errors during the conversion call itself
                logger.error(f"Unexpected error converting article {article_id}: {e}")
        
        logger.info("Docling conversion completed")
        
        # Map article IDs to extracted text content
        article_id_to_text = {}
        for article_id, html_path in article_files.items():
            # Get the corresponding text file path
            html_filename = os.path.basename(html_path)
            text_filename = os.path.splitext(html_filename)[0] + ".txt"
            text_path = os.path.join(output_dir, text_filename)
            
            # Read the text content if the file exists
            if os.path.exists(text_path):
                try:
                    with open(text_path, 'r', encoding='utf-8') as f:
                        text_content = f.read()
                    article_id_to_text[article_id] = text_content
                except Exception as e:
                    logger.error(f"Error reading text file {text_path}: {e}")
        
        # Update the database with extracted text
        updated_count = update_db_with_extracted_content(args.db_path, article_id_to_text)
        logger.info(f"Completed extraction and database update for {updated_count} articles")
        
if __name__ == "__main__":
    main()
