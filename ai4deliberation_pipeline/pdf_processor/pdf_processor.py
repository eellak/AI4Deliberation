#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Pipeline Processor - Configuration-Integrated Interface

This module provides a configuration-integrated interface to the existing PDF pipeline,
orchestrating the complete workflow through the existing scripts.
"""

import os
import sys
import time
import logging
import subprocess
from pathlib import Path

# Add the master_pipeline to path for configuration utilities
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'master_pipeline'))
from utils import load_config

class PDFProcessor:
    """
    Configuration-integrated PDF processor that orchestrates the existing PDF pipeline.
    """
    
    def __init__(self):
        """Initialize PDF processor with configuration."""
        self.config = load_config()
        self.logger = self._setup_logging()
        
        # Get database path from config
        self.database_path = self.config['database']['default_path']
        
        # PDF pipeline workspace from config
        self.workspace_dir = os.path.join(
            self.config['directories']['temp_processing'], 
            'pdf_pipeline_workspace'
        )
        
        # PDF pipeline script paths
        script_dir = os.path.dirname(__file__)
        self.export_script = os.path.join(script_dir, 'export_documents_to_parquet.py')
        self.redirect_script = os.path.join(script_dir, 'process_document_redirects.py')
        self.process_script = os.path.join(script_dir, 'process_pdfs_with_glossapi.py')
        self.update_script = os.path.join(script_dir, 'update_database_with_content.py')
        
        # Get venv python path
        self.venv_python = self.config.get('python', {}).get('venv_path', '/mnt/data/venv/bin/python')
        
        # Create workspace
        os.makedirs(self.workspace_dir, exist_ok=True)
        
    def _setup_logging(self):
        """Setup logging for PDF processor."""
        logger = logging.getLogger('pdf_processor')
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
                os.path.join(log_dir, 'pdf_processor.log')
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        return logger
    
    def _run_script(self, script_path, label, extra_args=None):
        """Run a PDF pipeline script and return success status."""
        self.logger.info(f"Running: {label}")
        
        if not os.path.exists(script_path):
            self.logger.error(f"Script not found: {script_path}")
            return False
        
        try:
            # Build command with any extra arguments
            cmd = [self.venv_python, script_path]
            if extra_args:
                cmd.extend(extra_args)
            
            # Run the script
            start_time = time.time()
            result = subprocess.run(
                cmd,
                check=True,
                text=True,
                capture_output=True,
                cwd=os.path.dirname(script_path)  # Run in script directory
            )
            
            # Log output
            if result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        self.logger.info(f"  {line}")
            
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip():
                        if "WARNING" in line.upper():
                            self.logger.warning(f"  {line}")
                        else:
                            self.logger.error(f"  {line}")
            
            elapsed = time.time() - start_time
            self.logger.info(f"Completed {label} in {elapsed:.1f} seconds")
            return True
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error running {script_path}: {e}")
            self.logger.error(f"Exit code: {e.returncode}")
            
            if e.stdout:
                for line in e.stdout.splitlines():
                    if line.strip():
                        self.logger.info(f"  {line}")
            
            if e.stderr:
                for line in e.stderr.splitlines():
                    if line.strip():
                        self.logger.error(f"  {line}")
                        
            return False
        
        except Exception as e:
            self.logger.error(f"Unexpected error running {script_path}: {e}")
            return False
    
    def process_documents(self, start_step=1, end_step=4):
        """
        Process documents through the PDF pipeline.
        
        Args:
            start_step: Starting step (1=export, 2=redirects, 3=processing, 4=update)
            end_step: Ending step
            
        Returns:
            bool: Success status
        """
        self.logger.info(f"Starting PDF processing pipeline (steps {start_step}-{end_step})")
        self.logger.info(f"Database: {self.database_path}")
        self.logger.info(f"Workspace: {self.workspace_dir}")
        
        # Get PDF pipeline settings from config
        pdf_config = self.config.get('pdf_pipeline', {})
        num_threads = pdf_config.get('threads', 4)
        disable_sectioning = pdf_config.get('disable_sectioning', True)
        
        steps = [
            (self.export_script, "Export non-law documents from database", 1, None),
            (self.redirect_script, "Process URL redirects", 2, None),
            (self.process_script, "Process PDFs with GlossAPI", 3, 
             [f"--threads={num_threads}"] + (["--disable-sectioning"] if disable_sectioning else [])),
            (self.update_script, "Update database with extracted content", 4, None)
        ]
        
        success = True
        
        for script_path, label, step_number, extra_args in steps:
            if start_step <= step_number <= end_step:
                step_success = self._run_script(script_path, label, extra_args)
                if not step_success:
                    success = False
                    self.logger.error(f"Step {step_number} ({label}) failed")
                    break  # Stop on first failure
        
        if success:
            self.logger.info("PDF processing pipeline completed successfully")
        else:
            self.logger.error("PDF processing pipeline failed")
        
        return success
    
    def get_processing_stats(self):
        """
        Get statistics about documents that need PDF processing.
        
        Returns:
            dict: Statistics about document counts and types
        """
        import sqlite3
        import pandas as pd
        
        try:
            conn = sqlite3.connect(self.database_path)
            
            # Query for non-law documents without extraction_quality
            query = """
            SELECT type, COUNT(*) as count
            FROM documents
            WHERE type != 'law_draft'
            AND url IS NOT NULL 
            AND url != ''
            AND (extraction_quality IS NULL)
            GROUP BY type
            ORDER BY count DESC
            """
            
            df = pd.read_sql_query(query, conn)
            conn.close()
            
            if not df.empty:
                total = df['count'].sum()
                stats = {
                    'total_documents': int(total),
                    'by_type': df.set_index('type')['count'].to_dict()
                }
                return stats
            else:
                return {'total_documents': 0, 'by_type': {}}
                
        except Exception as e:
            self.logger.error(f"Error getting processing stats: {e}")
            return {'total_documents': 0, 'by_type': {}, 'error': str(e)}


def process_pdf_documents(start_step=1, end_step=4):
    """
    Main entry point for PDF processing.
    
    Args:
        start_step: Starting step (1=export, 2=redirects, 3=processing, 4=update)
        end_step: Ending step
        
    Returns:
        bool: Success status
    """
    processor = PDFProcessor()
    return processor.process_documents(start_step, end_step)


def get_pdf_processing_stats():
    """
    Get statistics about documents needing PDF processing.
    
    Returns:
        dict: Processing statistics
    """
    processor = PDFProcessor()
    return processor.get_processing_stats()


if __name__ == "__main__":
    # Run the PDF processing pipeline
    import argparse
    
    parser = argparse.ArgumentParser(description='PDF Pipeline Processor')
    parser.add_argument('--start', type=int, default=1, 
                       help='Start at step N (default: 1)')
    parser.add_argument('--end', type=int, default=4,
                       help='End at step N (default: 4)')
    parser.add_argument('--stats', action='store_true',
                       help='Show processing statistics')
    
    args = parser.parse_args()
    
    if args.stats:
        stats = get_pdf_processing_stats()
        print(f"Documents needing PDF processing: {stats['total_documents']}")
        if stats['by_type']:
            print("By type:")
            for doc_type, count in stats['by_type'].items():
                print(f"  {doc_type}: {count}")
    else:
        success = process_pdf_documents(args.start, args.end)
        sys.exit(0 if success else 1) 