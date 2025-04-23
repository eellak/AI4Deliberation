#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI4Deliberation PDF Processing Pipeline

This script orchestrates the entire PDF processing pipeline:
1. Export document URLs from the database to a parquet file
2. Resolve URL redirects for all document URLs
3. Process PDFs with GlossAPI (download, extract text)
4. Update the database with the extracted content and quality metrics

Each step can also be run individually by running the corresponding script directly.
"""

import os
import sys
import time
import logging
import argparse
import importlib.util
import subprocess
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/mnt/data/AI4Deliberation/pdf_pipeline/pipeline_log.txt')
    ]
)
logger = logging.getLogger(__name__)

# Pipeline script paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_SCRIPT = os.path.join(SCRIPT_DIR, 'export_documents_to_parquet.py')
REDIRECT_SCRIPT = os.path.join(SCRIPT_DIR, 'process_document_redirects.py')
PROCESS_SCRIPT = os.path.join(SCRIPT_DIR, 'process_pdfs_with_glossapi.py')
UPDATE_SCRIPT = os.path.join(SCRIPT_DIR, 'update_database_with_content.py')

# Ensure the virtual environment is used
VENV_PYTHON = "/mnt/data/venv/bin/python"

def run_script(script_path, label, step_number, extra_args=None):
    """Run a Python script and return success status"""
    logger.info(f"STEP {step_number}: {label}")
    
    if not os.path.exists(script_path):
        logger.error(f"Script not found: {script_path}")
        return False
    
    try:
        # Build command with any extra arguments
        cmd = [VENV_PYTHON, script_path]
        if extra_args:
            cmd.extend(extra_args)
        
        # Run the script using the virtual environment Python
        start_time = time.time()
        result = subprocess.run(
            cmd,
            check=True,
            text=True,
            capture_output=True
        )
        
        # Log stdout and stderr
        if result.stdout:
            for line in result.stdout.splitlines():
                logger.info(f"  {line}")
        
        if result.stderr:
            for line in result.stderr.splitlines():
                if "WARNING" in line:
                    logger.warning(f"  {line}")
                else:
                    logger.error(f"  {line}")
        
        elapsed = time.time() - start_time
        logger.info(f"Completed {label} in {elapsed:.1f} seconds")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running {script_path}: {e}")
        logger.error(f"Exit code: {e.returncode}")
        
        if e.stdout:
            for line in e.stdout.splitlines():
                logger.info(f"  {line}")
        
        if e.stderr:
            for line in e.stderr.splitlines():
                logger.error(f"  {line}")
                
        return False
    
    except Exception as e:
        logger.error(f"Unexpected error running {script_path}: {e}")
        return False

def run_pipeline(start_step=1, end_step=4, threads=15, disable_sectioning=False):
    """Run the entire PDF processing pipeline or a subset of steps"""
    steps = [
        (EXPORT_SCRIPT, "Export document URLs from database", 1, None),
        (REDIRECT_SCRIPT, "Process URL redirects", 2, None),
        (PROCESS_SCRIPT, "Process PDFs with GlossAPI", 3, [f"--threads={threads}"] + (["--disable-sectioning"] if disable_sectioning else [])),
        (UPDATE_SCRIPT, "Update database with content", 4, None)
    ]
    
    logger.info(f"Starting PDF processing pipeline (steps {start_step}-{end_step})")
    if start_step <= 3 <= end_step:
        logger.info(f"PDF processing will use {threads} threads" + (", sectioning disabled" if disable_sectioning else ""))
    
    success = True
    
    for script_path, label, step_number, extra_args in steps:
        if start_step <= step_number <= end_step:
            step_success = run_script(script_path, label, step_number, extra_args)
            if not step_success:
                success = False
                logger.error(f"Step {step_number} ({label}) failed")
                
                # Ask if we should continue
                while True:
                    answer = input(f"\nStep {step_number} failed. Continue with next step? [y/n]: ").lower()
                    if answer in ['y', 'yes']:
                        break
                    elif answer in ['n', 'no']:
                        logger.info("Pipeline execution stopped by user")
                        return False
                    else:
                        print("Please enter 'y' or 'n'")
    
    if success:
        logger.info("PDF processing pipeline completed successfully")
    else:
        logger.warning("PDF processing pipeline completed with errors")
    
    return success

def print_help():
    """Print usage help"""
    print("\nAI4Deliberation PDF Processing Pipeline")
    print("--------------------------------------")
    print("Usage: python run_pdf_pipeline.py [OPTIONS]")
    print("\nOptions:")
    print("  --help, -h              Show this help message")
    print("  --start N               Start at step N (default: 1)")
    print("  --end N                 End at step N (default: 4)")
    print("  --threads N             Number of threads to use for PDF extraction (default: 4)")
    print("  --disable-sectioning    Skip the document sectioning step")
    print("\nSteps:")
    print("  1. Export document URLs from database")
    print("  2. Process URL redirects")
    print("  3. Process PDFs with GlossAPI")
    print("  4. Update database with content")
    print("\nExamples:")
    print("  Run all steps:                  python run_pdf_pipeline.py")
    print("  Run only steps 3 and 4:         python run_pdf_pipeline.py --start 3")
    print("  Run with 8 threads:             python run_pdf_pipeline.py --threads 8")
    print("  Skip sectioning:                python run_pdf_pipeline.py --disable-sectioning")

def main():
    """Parse command line arguments and run the pipeline"""
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Run the PDF processing pipeline')
    parser.add_argument('--start', type=int, default=1, 
                      help='Start at step N (1=export, 2=redirects, 3=processing, 4=database update)')
    parser.add_argument('--end', type=int, default=4,
                      help='End at step N (default: 4)')
    parser.add_argument('--threads', type=int, default=4,
                      help='Number of threads to use for PDF extraction (default: 4)')
    parser.add_argument('--disable-sectioning', action='store_true',
                      help='Disable document sectioning step')
    
    # Parse arguments
    if len(sys.argv) == 1:
        # No arguments, run with defaults
        run_pipeline(1, 4)
        return
        
    args = parser.parse_args()
    
    # Validate step range
    if args.start < 1 or args.start > 4:
        print(f"Invalid start step: {args.start}. Must be between 1 and 4")
        return
        
    if args.end < 1 or args.end > 4:
        print(f"Invalid end step: {args.end}. Must be between 1 and 4")
        return
        
    if args.start > args.end:
        print(f"Start step ({args.start}) cannot be greater than end step ({args.end})")
        return
    
    # Run pipeline with parsed arguments
    run_pipeline(args.start, args.end, args.threads, args.disable_sectioning)

if __name__ == "__main__":
    main()
