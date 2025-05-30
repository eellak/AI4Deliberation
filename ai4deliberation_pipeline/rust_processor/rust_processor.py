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

# Add the master_pipeline to path for configuration utilities
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'master_pipeline'))
from utils import load_config

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
    
    def __init__(self):
        """Initialize Rust processor with configuration."""
        self.config = load_config()
        self.logger = self._setup_logging()
        
        # Get database path from config
        self.database_path = self.config['database']['default_path']
        
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
        Get documents that have content but need Rust cleaning.
        
        Returns:
            list: List of document dictionaries with content that needs cleaning
        """
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Query for documents with content but no cleaned content
            query = """
            SELECT id, type, content, content_cleaned, badness_score
            FROM documents
            WHERE content IS NOT NULL 
            AND content != ''
            AND content_cleaned IS NULL
            ORDER BY id
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            conn.close()
            
            documents = []
            for row in rows:
                doc_id, doc_type, content, content_cleaned, badness_score = row
                documents.append({
                    'id': doc_id,
                    'type': doc_type,
                    'content': content,
                    'content_cleaned': content_cleaned,
                    'badness_score': badness_score
                })
            
            return documents
            
        except Exception as e:
            self.logger.error(f"Error getting documents needing cleaning: {e}")
            return []
    
    def process_documents_with_rust(self, documents):
        """
        Process documents through the Rust text cleaner.
        
        Args:
            documents: List of document dictionaries to process
            
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
            doc_id_to_filename = {}
            for doc in documents:
                filename = f"doc_{doc['id']}.md"
                filepath = os.path.join(temp_input_dir, filename)
                doc_id_to_filename[doc['id']] = filename
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(doc['content'])
            
            self.logger.info(f"Created {len(documents)} temporary markdown files")
            
            # Run Rust text cleaner
            try:
                start_time = time.time()
                self.logger.info(f"Running Rust cleaner with {self.threads} threads, scripts: {self.scripts}")
                
                # Parse scripts for Rust
                user_scripts = [s.strip() for s in self.scripts.split(',') if s.strip()]
                base_scripts = ["punctuation", "numbers", "common_symbols"]
                final_scripts = list(set(user_scripts + base_scripts))
                
                text_cleaner_rs.generate_analysis_report_for_directory(
                    temp_input_dir,
                    temp_csv_path,
                    temp_output_dir,
                    final_scripts,
                    self.threads
                )
                
                elapsed = time.time() - start_time
                self.logger.info(f"Rust processing completed in {elapsed:.2f} seconds")
                
            except Exception as e:
                self.logger.error(f"Error running Rust text cleaner: {e}")
                return {}
            
            # Read the analysis results
            results = {}
            try:
                if os.path.exists(temp_csv_path):
                    df = pd.read_csv(temp_csv_path)
                    self.logger.info(f"Read analysis results for {len(df)} files")
                    
                    for _, row in df.iterrows():
                        filename = row['File Name']  # Correct column name
                        # Extract document ID from filename
                        if filename.startswith('doc_') and filename.endswith('.md'):
                            doc_id = int(filename[4:-3])  # Remove 'doc_' and '.md'
                            
                            # Read cleaned content if available
                            cleaned_filepath = os.path.join(temp_output_dir, filename)
                            cleaned_content = None
                            if os.path.exists(cleaned_filepath):
                                with open(cleaned_filepath, 'r', encoding='utf-8') as f:
                                    cleaned_content = f.read()
                            
                            # Parse percentages (remove % sign)
                            greek_pct_str = str(row.get('Greek Percentage', '0%')).replace('%', '')
                            latin_pct_str = str(row.get('Latin Percentage', '0%')).replace('%', '')
                            
                            results[doc_id] = {
                                'cleaned_content': cleaned_content,
                                'badness_score': float(row.get('Badness', 0.0)),
                                'greek_percentage': float(greek_pct_str) if greek_pct_str else 0.0,
                                'english_percentage': float(latin_pct_str) if latin_pct_str else 0.0,  # Using Latin as English
                                'total_chars': len(cleaned_content) if cleaned_content else 0,
                                'good_chars': 0  # Not provided by this version of Rust cleaner
                            }
                else:
                    self.logger.warning("No analysis CSV found")
                    
            except Exception as e:
                self.logger.error(f"Error reading analysis results: {e}")
                return {}
        
        return results
    
    def update_database_with_results(self, results):
        """
        Update database with Rust cleaning results.
        
        Args:
            results: Dictionary of document_id -> cleaning results
            
        Returns:
            bool: Success status
        """
        if not results:
            self.logger.warning("No results to update")
            return False
        
        try:
            # Use SQLite directly for reliable updates
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            self.logger.info("Connected to database using SQLite")
        
            update_count = 0
            error_count = 0
            
            for doc_id, result in results.items():
                try:
                    cursor.execute(
                        """UPDATE documents 
                           SET content_cleaned = ?, badness_score = ?, 
                               greek_percentage = ?, english_percentage = ?
                           WHERE id = ?""",
                        (result['cleaned_content'], result['badness_score'],
                         result['greek_percentage'], result['english_percentage'], doc_id)
                    )
                    if cursor.rowcount > 0:
                        update_count += 1
                    else:
                        self.logger.warning(f"Document {doc_id} not found")
                    
                    # Commit in batches
                    if update_count % 50 == 0:
                        conn.commit()
                        self.logger.info(f"Updated {update_count} documents so far")
                        
                except Exception as e:
                    self.logger.error(f"Error updating document {doc_id}: {e}")
                    error_count += 1
            
            # Final commit
            conn.commit()
            conn.close()
            
            self.logger.info(f"Database update complete: {update_count} updated, {error_count} errors")
            return update_count > 0
            
        except Exception as e:
            self.logger.error(f"Error updating database: {e}")
            if 'conn' in locals():
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
        Get statistics about documents and their cleaning status.
        
        Returns:
            dict: Statistics about document cleaning
        """
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Get cleaning statistics
            stats = {}
            
            # Total documents with content
            cursor.execute("SELECT COUNT(*) FROM documents WHERE content IS NOT NULL AND content != ''")
            stats['total_with_content'] = cursor.fetchone()[0]
            
            # Documents with cleaned content
            cursor.execute("SELECT COUNT(*) FROM documents WHERE content_cleaned IS NOT NULL")
            stats['total_cleaned'] = cursor.fetchone()[0]
            
            # Documents needing cleaning
            cursor.execute("""
                SELECT COUNT(*) FROM documents 
                WHERE content IS NOT NULL AND content != '' 
                AND content_cleaned IS NULL
            """)
            stats['need_cleaning'] = cursor.fetchone()[0]
            
            # Badness score statistics
            cursor.execute("""
                SELECT AVG(badness_score), MIN(badness_score), MAX(badness_score)
                FROM documents WHERE badness_score IS NOT NULL
            """)
            row = cursor.fetchone()
            if row and row[0] is not None:
                stats['badness_avg'] = round(row[0], 3)
                stats['badness_min'] = round(row[1], 3)
                stats['badness_max'] = round(row[2], 3)
            
            # Language percentages
            cursor.execute("""
                SELECT AVG(greek_percentage), AVG(english_percentage)
                FROM documents WHERE greek_percentage IS NOT NULL
            """)
            row = cursor.fetchone()
            if row and row[0] is not None:
                stats['avg_greek_pct'] = round(row[0], 1)
                stats['avg_english_pct'] = round(row[1], 1)
            
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
    """
    Get statistics about Rust cleaning progress.
    
    Returns:
        dict: Cleaning statistics
    """
    processor = RustProcessor()
    return processor.get_cleaning_stats()


if __name__ == "__main__":
    # Run the Rust cleaning pipeline
    import argparse
    
    parser = argparse.ArgumentParser(description='Rust Text Cleaner Pipeline')
    parser.add_argument('--stats', action='store_true',
                       help='Show cleaning statistics')
    
    args = parser.parse_args()
    
    if args.stats:
        stats = get_rust_cleaning_stats()
        print(f"Documents with content: {stats.get('total_with_content', 0)}")
        print(f"Documents cleaned: {stats.get('total_cleaned', 0)}")
        print(f"Documents needing cleaning: {stats.get('need_cleaning', 0)}")
        if 'badness_avg' in stats:
            print(f"Average badness score: {stats['badness_avg']} (range: {stats['badness_min']}-{stats['badness_max']})")
        if 'avg_greek_pct' in stats:
            print(f"Average Greek content: {stats['avg_greek_pct']}%")
            print(f"Average English content: {stats['avg_english_pct']}%")
    else:
        success = process_with_rust_cleaner()
        sys.exit(0 if success else 1) 