#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Pipeline Orchestrator with Proper Execution Order and Immediate Anonymization

This orchestrator ensures:
1. New consultations are scraped from opengov.gr
2. Each consultation is anonymized immediately after scraping
3. A one-time full database anonymization is performed
4. Comprehensive logging for diagnostics
"""

import os
import sys
import time
import logging
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Dict, List, Tuple, Optional

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ai4deliberation_pipeline.config.config_manager import load_config
from ai4deliberation_pipeline.utils.anonymizer import anonymise_sqlite, pseudonymize
from ai4deliberation_pipeline.scraper.db_models import init_db, Consultation, Comment
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


class EnhancedPipelineOrchestrator:
    """Enhanced orchestrator with immediate anonymization and detailed logging."""
    
    def __init__(self, config: Dict):
        self.config = config
        self.database_path = config['database']['default_path']
        self.log_dir = config['directories']['logs']
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Ensure log directory exists
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Setup detailed logging
        self.logger = self._setup_logging()
        self.stats = {
            'consultations_found': 0,
            'consultations_processed': 0,
            'consultations_anonymized': 0,
            'comments_anonymized': 0,
            'errors': []
        }
        
    def _setup_logging(self) -> logging.Logger:
        """Setup comprehensive logging with multiple handlers."""
        logger = logging.getLogger('enhanced_orchestrator')
        logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers
        logger.handlers = []
        
        # Detailed formatter
        formatter = logging.Formatter(
            '%(asctime)s - [%(levelname)s] - %(funcName)s:%(lineno)d - %(message)s'
        )
        
        # Main log file
        main_log = os.path.join(self.log_dir, f'enhanced_orchestrator_{self.timestamp}.log')
        main_handler = logging.FileHandler(main_log)
        main_handler.setLevel(logging.DEBUG)
        main_handler.setFormatter(formatter)
        logger.addHandler(main_handler)
        
        # Error log file
        error_log = os.path.join(self.log_dir, f'errors_{self.timestamp}.log')
        error_handler = logging.FileHandler(error_log)
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        logger.addHandler(error_handler)
        
        # Pipeline orchestrator log (for compatibility)
        pipeline_log = os.path.join(self.log_dir, 'pipeline_orchestrator.log')
        pipeline_handler = logging.FileHandler(pipeline_log)
        pipeline_handler.setLevel(logging.INFO)
        pipeline_handler.setFormatter(formatter)
        logger.addHandler(pipeline_handler)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        return logger
        
    def run_full_database_anonymization(self) -> bool:
        """Perform one-time anonymization of the entire database."""
        self.logger.info("=" * 80)
        self.logger.info("STARTING FULL DATABASE ANONYMIZATION")
        self.logger.info("=" * 80)
        
        try:
            # Check if database exists
            if not os.path.exists(self.database_path):
                self.logger.error(f"Database not found at: {self.database_path}")
                return False
                
            self.logger.info(f"Anonymizing database: {self.database_path}")
            start_time = time.time()
            
            # Use the anonymizer module's function
            anonymise_sqlite(self.database_path)
            
            elapsed = time.time() - start_time
            self.logger.info(f"Full database anonymization completed in {elapsed:.2f} seconds")
            
            # Verify anonymization
            self._verify_anonymization()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Full database anonymization failed: {e}", exc_info=True)
            self.stats['errors'].append(f"Full DB anonymization: {str(e)}")
            return False
            
    def _verify_anonymization(self):
        """Verify that anonymization was successful."""
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Check for non-anonymized usernames
            cursor.execute("""
                SELECT COUNT(*) FROM comments 
                WHERE username IS NOT NULL 
                AND username != '' 
                AND username NOT LIKE 'user_%'
            """)
            non_anon_count = cursor.fetchone()[0]
            
            if non_anon_count > 0:
                self.logger.warning(f"Found {non_anon_count} non-anonymized usernames remaining")
            else:
                self.logger.info("✓ All usernames successfully anonymized")
                
            # Get sample of anonymized usernames
            cursor.execute("""
                SELECT DISTINCT username FROM comments 
                WHERE username LIKE 'user_%' 
                LIMIT 5
            """)
            samples = cursor.fetchall()
            self.logger.info(f"Sample anonymized usernames: {[s[0] for s in samples]}")
            
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error verifying anonymization: {e}")
            
    def discover_new_consultations(self) -> List[str]:
        """Run the scraper to discover new consultations."""
        self.logger.info("=" * 80)
        self.logger.info("DISCOVERING NEW CONSULTATIONS")
        self.logger.info("=" * 80)
        
        try:
            # Path to list_consultations.py
            script_path = os.path.join(
                project_root, 
                'ai4deliberation_pipeline', 
                'scraper', 
                'list_consultations.py'
            )
            
            if not os.path.exists(script_path):
                self.logger.error(f"list_consultations.py not found at: {script_path}")
                return []
                
            self.logger.info(f"Running consultation discovery script: {script_path}")
            
            # Run with --update flag
            result = subprocess.run(
                [sys.executable, script_path, '--update'],
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            if result.returncode != 0:
                self.logger.error(f"Discovery script failed with code {result.returncode}")
                self.logger.error(f"STDERR: {result.stderr}")
                return []
                
            self.logger.info("Discovery script output:")
            for line in result.stdout.split('\n'):
                if line.strip():
                    self.logger.info(f"  {line}")
                    
            # Read the CSV to get consultation URLs
            csv_path = os.path.join(project_root, 'all_consultations.csv')
            if os.path.exists(csv_path):
                import csv
                urls = []
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if 'url' in row:
                            urls.append(row['url'])
                            
                self.logger.info(f"Found {len(urls)} consultations in CSV")
                self.stats['consultations_found'] = len(urls)
                return urls
            else:
                self.logger.warning("all_consultations.csv not found")
                return []
                
        except Exception as e:
            self.logger.error(f"Error discovering consultations: {e}", exc_info=True)
            self.stats['errors'].append(f"Discovery: {str(e)}")
            return []
            
    def scrape_and_anonymize_consultation(self, url: str) -> bool:
        """Scrape a single consultation and immediately anonymize it."""
        self.logger.info(f"Processing consultation: {url}")
        
        try:
            # Import scraping function
            from ai4deliberation_pipeline.scraper.scrape_single_consultation import scrape_and_store
            
            # Initialize database session
            engine, Session = init_db(f'sqlite:///{self.database_path}')
            session = Session()
            
            # Scrape the consultation
            self.logger.debug(f"Scraping consultation from {url}")
            success = scrape_and_store(url, session)
            
            if not success:
                self.logger.warning(f"Failed to scrape consultation: {url}")
                return False
                
            # Get the consultation ID for immediate anonymization
            consultation = session.query(Consultation).filter_by(url=url).first()
            if not consultation:
                self.logger.error(f"Consultation not found after scraping: {url}")
                return False
                
            consultation_id = consultation.id
            self.logger.info(f"Consultation scraped successfully. ID: {consultation_id}")
            
            # Immediately anonymize comments for this consultation
            anonymized_count = self._anonymize_consultation_comments(session, consultation_id)
            
            session.close()
            
            self.logger.info(f"✓ Consultation {consultation_id} processed: {anonymized_count} comments anonymized")
            self.stats['consultations_processed'] += 1
            self.stats['consultations_anonymized'] += 1
            self.stats['comments_anonymized'] += anonymized_count
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing consultation {url}: {e}", exc_info=True)
            self.stats['errors'].append(f"Consultation {url}: {str(e)}")
            return False
            
    def _anonymize_consultation_comments(self, session, consultation_id: int) -> int:
        """Anonymize all comments for a specific consultation."""
        try:
            # Get all comments for this consultation through articles
            comments = session.execute(text("""
                SELECT c.id, c.username 
                FROM comments c
                JOIN articles a ON c.article_id = a.id
                WHERE a.consultation_id = :cid
                AND c.username IS NOT NULL
                AND c.username != ''
                AND c.username NOT LIKE 'user_%'
            """), {'cid': consultation_id}).fetchall()
            
            if not comments:
                self.logger.debug(f"No comments to anonymize for consultation {consultation_id}")
                return 0
                
            # Anonymize each username
            anonymized_count = 0
            for comment_id, username in comments:
                anon_username = pseudonymize(username)
                if anon_username != username:
                    session.execute(text("""
                        UPDATE comments 
                        SET username = :anon 
                        WHERE id = :id
                    """), {'anon': anon_username, 'id': comment_id})
                    anonymized_count += 1
                    
            session.commit()
            
            self.logger.debug(f"Anonymized {anonymized_count} comments for consultation {consultation_id}")
            return anonymized_count
            
        except Exception as e:
            self.logger.error(f"Error anonymizing consultation {consultation_id}: {e}")
            session.rollback()
            return 0
            
    def run_pipeline(self, skip_full_anonymization: bool = False):
        """Run the complete pipeline with proper order."""
        start_time = time.time()
        
        self.logger.info("=" * 80)
        self.logger.info("ENHANCED PIPELINE ORCHESTRATOR STARTED")
        self.logger.info(f"Timestamp: {self.timestamp}")
        self.logger.info(f"Database: {self.database_path}")
        self.logger.info(f"Log directory: {self.log_dir}")
        self.logger.info("=" * 80)
        
        # Step 1: One-time full database anonymization
        if not skip_full_anonymization:
            if not self.run_full_database_anonymization():
                self.logger.error("Full database anonymization failed. Continuing anyway...")
        else:
            self.logger.info("Skipping full database anonymization (--skip-full-anonymization flag)")
            
        # Step 2: Discover new consultations
        consultation_urls = self.discover_new_consultations()
        
        if not consultation_urls:
            self.logger.warning("No consultations found to process")
            return
            
        # Step 3: Process each consultation with immediate anonymization
        self.logger.info(f"Processing {len(consultation_urls)} consultations...")
        
        for i, url in enumerate(consultation_urls, 1):
            self.logger.info(f"\n--- Processing consultation {i}/{len(consultation_urls)} ---")
            
            # Add delay to avoid overwhelming the server
            if i > 1:
                delay = 2.0
                self.logger.debug(f"Waiting {delay} seconds before next request...")
                time.sleep(delay)
                
            self.scrape_and_anonymize_consultation(url)
            
        # Final statistics
        elapsed_time = time.time() - start_time
        self.logger.info("\n" + "=" * 80)
        self.logger.info("PIPELINE EXECUTION COMPLETED")
        self.logger.info("=" * 80)
        self.logger.info(f"Total execution time: {elapsed_time:.2f} seconds")
        self.logger.info(f"Consultations found: {self.stats['consultations_found']}")
        self.logger.info(f"Consultations processed: {self.stats['consultations_processed']}")
        self.logger.info(f"Consultations anonymized: {self.stats['consultations_anonymized']}")
        self.logger.info(f"Total comments anonymized: {self.stats['comments_anonymized']}")
        self.logger.info(f"Errors encountered: {len(self.stats['errors'])}")
        
        if self.stats['errors']:
            self.logger.error("Errors summary:")
            for error in self.stats['errors']:
                self.logger.error(f"  - {error}")
                
        self.logger.info(f"\nLog files created:")
        self.logger.info(f"  - Main log: enhanced_orchestrator_{self.timestamp}.log")
        self.logger.info(f"  - Error log: errors_{self.timestamp}.log")
        self.logger.info(f"  - Pipeline log: pipeline_orchestrator.log")


def main():
    parser = argparse.ArgumentParser(
        description="Enhanced AI4Deliberation Pipeline Orchestrator"
    )
    parser.add_argument(
        '--skip-full-anonymization',
        action='store_true',
        help='Skip the one-time full database anonymization'
    )
    parser.add_argument(
        '--config',
        type=str,
        help='Path to custom configuration file'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config if args.config else None)
    
    # Create and run orchestrator
    orchestrator = EnhancedPipelineOrchestrator(config)
    orchestrator.run_pipeline(skip_full_anonymization=args.skip_full_anonymization)


if __name__ == "__main__":
    main()