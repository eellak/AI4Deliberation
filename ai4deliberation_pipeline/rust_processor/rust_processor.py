#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rust Cleaner Pipeline Processor - Configuration-Integrated Interface

This module provides a configuration-integrated interface to the Rust text cleaner,
processing markdown files extracted from PDFs and updating the database with
cleaned content, badness scores, and language percentages.
"""

import os
import sys
import time
import logging
import tempfile
import pandas as pd
import sqlite3
from pathlib import Path
import argparse
from datetime import datetime # For updated_at

# Import configuration utilities
from config.config_manager import load_config

# Import the Rust text cleaner module
try:
    import text_cleaner_rs
except ImportError as e:
    print(f"Error importing text_cleaner_rs: {e}")
    print("Make sure the Rust module is properly installed in the virtual environment")
    sys.exit(1)


class RustProcessor:
    """
    Configuration-integrated Rust processor for document cleaning and analysis.
    """
    
    def __init__(self, db_path_override: str = None):
        """Initialize Rust processor with configuration."""
        self.config = load_config()
        self.logger = self._setup_logging()
        
        # Get database path from config or override
        if db_path_override:
            self.database_path = db_path_override
            self.logger.info(f"Using overridden database path: {self.database_path}")
        else:
            self.database_path = self.config['database']['default_path']
            self.logger.info(f"Using database path from config: {self.database_path}")
        
        # Rust cleaner settings from config
        rust_config = self.config.get('rust_cleaner', {})
        self.threads = rust_config.get('threads', 4)
        self.scripts = rust_config.get('scripts', 'lat,grc')
        self.batch_size = rust_config.get('batch_size', 100)
        
        # Directory paths
        self.temp_processing = self.config['directories']['temp_processing']
        self.pdf_workspace = os.path.join(self.temp_processing, 'pdf_pipeline_workspace')
        self.markdown_dir = os.path.join(self.pdf_workspace, 'markdown')
        self.cleaned_dir = os.path.join(self.temp_processing, 'cleaned')
        
        # Create directories
        os.makedirs(self.cleaned_dir, exist_ok=True)
        
    def _setup_logging(self):
        """Setup logging for Rust processor."""
        logger = logging.getLogger('rust_processor')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            # Create formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
            
            # File handler
            log_dir = self.config['directories']['logs']
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.FileHandler(
                os.path.join(log_dir, 'rust_processor.log')
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        return logger
    
    def get_documents_needing_cleaning(self):
        """
        Get documents that have processed_text but need Rust cleaning.
        
        Returns:
            list: List of document dictionaries with content that needs cleaning
        """
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Query for documents with processed_text but no/empty content_cleaned
            query = """
            SELECT id, type, processed_text
            FROM documents
            WHERE processed_text IS NOT NULL 
            AND processed_text != ''
            AND (content_cleaned IS NULL OR content_cleaned = '')
            ORDER BY id
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            conn.close()
            
            documents = []
            for row in rows:
                doc_id, doc_type, source_text = row
                documents.append({
                    'id': doc_id,
                    'type': doc_type,
                    'source_text': source_text,
                })
            
            self.logger.info(f"Found {len(documents)} documents with 'processed_text' needing cleaning.")
            return documents
            
        except Exception as e:
            self.logger.error(f"Error getting documents needing cleaning: {e}")
            return []
    
    def process_documents_with_rust(self, documents):
        """
        Process documents through the Rust text cleaner.
        
        Args:
            documents: List of document dictionaries to process (expecting 'id' and 'source_text')
            
        Returns:
            dict: Results with cleaned content and metrics
        """
        if not documents:
            self.logger.info("No documents to process")
            return {}
        
        self.logger.info(f"Processing {len(documents)} documents with Rust text cleaner")
        
        # Create temporary directory for processing
        with tempfile.TemporaryDirectory(prefix='rust_cleaning_') as temp_dir:
            temp_input_dir = os.path.join(temp_dir, 'input')
            temp_output_dir = os.path.join(temp_dir, 'output')
            temp_csv_path = os.path.join(temp_dir, 'analysis.csv')
            
            os.makedirs(temp_input_dir, exist_ok=True)
            os.makedirs(temp_output_dir, exist_ok=True)
            
            # Write documents to temporary markdown files
            for doc in documents:
                filename = f"doc_{doc['id']}.md"
                filepath = os.path.join(temp_input_dir, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(doc['source_text'])
            
            self.logger.info(f"Created {len(documents)} temporary markdown files in {temp_input_dir}")
            
            # Run Rust text cleaner
            try:
                start_time = time.time()
                
                # Parse scripts for Rust
                user_scripts_from_config = [s.strip() for s in self.scripts.split(',') if s.strip()]
                
                mapped_scripts = []
                for s_config in user_scripts_from_config:
                    if s_config.lower() == 'lat':
                        mapped_scripts.append('latin')
                    elif s_config.lower() == 'grc':
                        mapped_scripts.append('greek')
                    else:
                        mapped_scripts.append(s_config.lower())

                final_scripts_to_pass = list(set(mapped_scripts + ["punctuation", "numbers", "common_symbols"]))
                self.logger.info(f"Running Rust cleaner with {self.threads} threads, scripts_to_keep: {final_scripts_to_pass}")

                text_cleaner_rs.generate_analysis_report_for_directory(
                    temp_input_dir,
                    temp_csv_path,
                    temp_output_dir,
                    final_scripts_to_pass,
                    self.threads
                )
                
                elapsed = time.time() - start_time
                self.logger.info(f"Rust processing completed in {elapsed:.2f} seconds")
                
            except Exception as e:
                self.logger.error(f"Error running Rust text cleaner: {e}", exc_info=True)
                return {}
            
            # Read the analysis results
            results = {}
            try:
                if os.path.exists(temp_csv_path):
                    df = pd.read_csv(temp_csv_path)
                    self.logger.info(f"Read analysis results for {len(df)} files from {temp_csv_path}")
                    
                    for _, row in df.iterrows():
                        filename = row.get('File Name')
                        if not filename:
                            self.logger.warning(f"Skipping row with missing 'File Name' in CSV: {row.to_dict()}")
                            continue

                        if filename.startswith('doc_') and filename.endswith('.md'):
                            try:
                                doc_id = int(filename[4:-3])
                            except ValueError:
                                self.logger.warning(f"Could not parse doc_id from filename: {filename}. Skipping.")
                                continue
                            
                            cleaned_filepath = os.path.join(temp_output_dir, filename)
                            cleaned_content = None
                            if os.path.exists(cleaned_filepath):
                                with open(cleaned_filepath, 'r', encoding='utf-8') as f:
                                    cleaned_content = f.read()
                            else:
                                self.logger.warning(f"Cleaned file not found for {filename} at {cleaned_filepath}")
                            
                            greek_pct_str = str(row.get('Greek Percentage', '0')).replace('%', '')
                            latin_pct_str = str(row.get('Latin Percentage', '0')).replace('%', '')
                            badness_score_val = row.get('Badness Score')
                            if badness_score_val is None:
                                badness_score_val = row.get('Badness')

                            results[doc_id] = {
                                'cleaned_content': cleaned_content,
                                'badness_score': float(badness_score_val) if badness_score_val is not None else 1.0,
                                'greek_percentage': float(greek_pct_str) if greek_pct_str else 0.0,
                                'english_percentage': float(latin_pct_str) if latin_pct_str else 0.0,
                            }
                        else:
                            self.logger.warning(f"Filename '{filename}' in CSV does not match expected 'doc_*.md' format. Skipping.")
                else:
                    self.logger.warning(f"No analysis CSV found at {temp_csv_path}")
                    
            except Exception as e:
                self.logger.error(f"Error reading analysis results from {temp_csv_path}: {e}", exc_info=True)
        
        return results
    
    def update_database_with_results(self, results):
        """
        Update database with Rust cleaning results.
        
        Args:
            results: Dictionary of document_id -> cleaning results
            
        Returns:
            bool: Success status (True if any updates attempted)
        """
        if not results:
            self.logger.warning("No results to update in database.")
            return False

        updated_count = 0
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            for doc_id, data in results.items():
                if data.get('cleaned_content') is None:
                    self.logger.warning(f"Skipping DB update for doc_id {doc_id} as cleaned_content is missing.")
                    continue

                try:
                    cursor.execute("""
                        UPDATE documents
                        SET content_cleaned = ?, 
                            badness_score = ?, 
                            greek_percentage = ?, 
                            english_percentage = ?,
                            updated_at = ? 
                        WHERE id = ?
                    """, (
                        data['cleaned_content'],
                        data.get('badness_score', 1.0),
                        data.get('greek_percentage', 0.0),
                        data.get('english_percentage', 0.0),
                        datetime.utcnow().isoformat(),
                        doc_id
                    ))
                    if cursor.rowcount > 0:
                        updated_count += 1
                        self.logger.debug(f"Updated document {doc_id} with cleaning results.")
                    else:
                        self.logger.warning(f"No rows updated for document {doc_id}. It might not exist or match conditions.")
                except sqlite3.Error as e_sql:
                    self.logger.error(f"SQL error updating document {doc_id}: {e_sql}. Data: {data}")
            
            conn.commit()
            conn.close()
            self.logger.info(f"Successfully updated {updated_count} documents in the database.")
            return updated_count > 0
            
        except Exception as e:
            self.logger.error(f"Error updating database with results: {e}", exc_info=True)
            if 'conn' in locals() and conn:
                conn.rollback()
                conn.close()
            return False
    
    def process_all_documents(self):
        """
        Process all documents that need Rust cleaning.
        
        Returns:
            bool: Success status
        """
        self.logger.info("Starting Rust cleaning pipeline")
        
        # Get documents needing cleaning
        documents = self.get_documents_needing_cleaning()
        
        if not documents:
            self.logger.info("No documents found that need cleaning")
            return True
        
        self.logger.info(f"Found {len(documents)} documents needing cleaning")
        
        # Process in batches if needed
        batch_size = self.batch_size
        total_processed = 0
        total_errors = 0
        
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(documents) + batch_size - 1) // batch_size
            
            self.logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} documents)")
            
            # Process batch with Rust
            results = self.process_documents_with_rust(batch)
            
            if results:
                # Update database
                success = self.update_database_with_results(results)
                if success:
                    total_processed += len(results)
                    self.logger.info(f"Batch {batch_num} completed successfully")
                else:
                    total_errors += len(batch)
                    self.logger.error(f"Batch {batch_num} database update failed")
            else:
                total_errors += len(batch)
                self.logger.error(f"Batch {batch_num} processing failed")
        
        self.logger.info(f"Rust cleaning pipeline completed: {total_processed} processed, {total_errors} errors")
        return total_processed > 0
    
    def get_cleaning_stats(self):
        """
        Get cleaning statistics from the database.
        
        Returns:
            dict: Dictionary with cleaning statistics
        """
        try:
            if not os.path.exists(self.database_path):
                self.logger.error(f"Database file not found at {self.database_path}")
                return {
                    "error": f"Database file not found at {self.database_path}",
                    "avg_badness": None, "min_badness": None, "max_badness": None,
                    "avg_greek": None, "avg_english": None,
                    "docs_with_content": 0, "docs_cleaned": 0, "docs_needing_cleaning": 0
                }

            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Get cleaning statistics
            stats = {}
            
            # Total documents with content
            cursor.execute("SELECT COUNT(*) FROM documents WHERE content IS NOT NULL AND content != ''")
            stats['docs_with_content'] = cursor.fetchone()[0]
            
            # Documents with cleaned content
            cursor.execute("SELECT COUNT(*) FROM documents WHERE content_cleaned IS NOT NULL")
            stats['docs_cleaned'] = cursor.fetchone()[0]
            
            # Documents needing cleaning
            cursor.execute("""
                SELECT COUNT(*) FROM documents 
                WHERE content IS NOT NULL AND content != '' 
                AND content_cleaned IS NULL
            """)
            stats['docs_needing_cleaning'] = cursor.fetchone()[0]
            
            # Badness score statistics
            cursor.execute("""
                SELECT AVG(badness_score), MIN(badness_score), MAX(badness_score)
                FROM documents WHERE badness_score IS NOT NULL
            """)
            row = cursor.fetchone()
            if row and row[0] is not None:
                stats['avg_badness'] = round(row[0], 3)
                stats['min_badness'] = round(row[1], 3)
                stats['max_badness'] = round(row[2], 3)
            
            # Language percentages
            cursor.execute("""
                SELECT AVG(greek_percentage), AVG(english_percentage)
                FROM documents WHERE greek_percentage IS NOT NULL
            """)
            row = cursor.fetchone()
            if row and row[0] is not None:
                stats['avg_greek'] = round(row[0], 1)
                stats['avg_english'] = round(row[1], 1)
            
            conn.close()
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting cleaning stats: {e}")
            return {}


def process_with_rust_cleaner():
    """
    Main entry point for Rust cleaning pipeline.
    
    Returns:
        bool: Success status
    """
    processor = RustProcessor()
    return processor.process_all_documents()


def get_rust_cleaning_stats():
    """Get Rust cleaning statistics."""
    logger = logging.getLogger('rust_processor_cli')
    logger.info("Getting Rust cleaning stats...")
    
    # Create a dummy RustProcessor instance to access its get_cleaning_stats method
    # This will use the DB path from config unless overridden by a potential CLI arg later
    # For now, this assumes get_cleaning_stats in main() will handle DB path
    processor = RustProcessor() 
    stats = processor.get_cleaning_stats()
    
    if stats.get("error"):
        logger.error(f"Error getting cleaning stats: {stats['error']}")
        return

    logger.info(f"Documents with content: {stats['docs_with_content']}")
    logger.info(f"Documents cleaned: {stats['docs_cleaned']}")
    logger.info(f"Documents needing cleaning: {stats['docs_needing_cleaning']}")
    if stats['avg_badness'] is not None:
        logger.info(f"Average badness score: {stats['avg_badness']:.3f} (range: {stats['min_badness']:.3f}-{stats['max_badness']:.3f})")
        logger.info(f"Average Greek content: {stats['avg_greek']:.1f}%")
        logger.info(f"Average English content: {stats['avg_english']:.1f}%")
    else:
        logger.info("No badness scores found to analyze.")


def main():
    """Main function to run Rust processor or get stats."""
    # Setup basic logging for main entry point if not already configured
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger('rust_processor_main')

    parser = argparse.ArgumentParser(description="Rust Processor CLI")
    parser.add_argument(
        "--process", 
        action="store_true", 
        help="Run the full Rust cleaning process on all documents."
    )
    parser.add_argument(
        "--stats", 
        action="store_true", 
        help="Get cleaning statistics from the database."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Override the database path specified in the config."
    )
    
    args = parser.parse_args()

    if args.process:
        logger.info("Starting Rust processing for all documents...")
        processor_instance = RustProcessor(db_path_override=args.db_path)
        processor_instance.process_all_documents()
        logger.info("Rust processing completed.")
    elif args.stats:
        logger.info("Getting Rust cleaning stats...")
        # Pass db_path_override to the RustProcessor instance used by get_cleaning_stats
        processor_for_stats = RustProcessor(db_path_override=args.db_path)
        stats = processor_for_stats.get_cleaning_stats()

        if stats.get("error"):
            logger.error(f"Error getting cleaning stats: {stats['error']}")
            return

        logger.info(f"Database: {processor_for_stats.database_path}")
        logger.info(f"Documents with content: {stats['docs_with_content']}")
        logger.info(f"Documents cleaned: {stats['docs_cleaned']}")
        logger.info(f"Documents needing cleaning: {stats['docs_needing_cleaning']}")
        if stats['avg_badness'] is not None and stats['docs_cleaned'] > 0 :
            logger.info(f"Average badness score: {stats['avg_badness']:.3f} (range: {stats['min_badness']:.3f}-{stats['max_badness']:.3f})")
            logger.info(f"Average Greek content: {stats['avg_greek']:.1f}%")
            logger.info(f"Average English content: {stats['avg_english']:.1f}%")
        elif stats['docs_cleaned'] == 0:
            logger.info("No documents have been cleaned yet in this database.")
        else:
            logger.info("No badness scores found to analyze or docs_cleaned is 0.")
            
    else:
        logger.info("No action specified. Use --process or --stats.")
        parser.print_help()


if __name__ == "__main__":
    main() 