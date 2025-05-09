#!/usr/bin/env python3
"""
Script to clean Markdown files using the text_cleaner_rs Rust module.
This processes files and outputs them to a specified directory.
"""
import text_cleaner_rs
import time
import sys
import os
import argparse
from pathlib import Path
import concurrent.futures

def print_separator():
    """Print a visual separator line."""
    print("-" * 80)

def main():
    """
    Clean markdown files using the Rust module and output to a specified directory.
    """
    parser = argparse.ArgumentParser(description="Clean Markdown files using Rust module")
    parser.add_argument("--input", default="ΦΕΚ/nomoi/check_badness", 
                        help="Input directory containing markdown files")
    parser.add_argument("--output", default="ΦΕΚ/nomoi/check_badness/sample_cleaned_markdown_v5", 
                        help="Output directory for cleaned markdown files")
    parser.add_argument("--threads", type=int, default=4, 
                        help="Number of threads for processing")
    parser.add_argument("--scripts", type=str, default="lat,gre,punct,num,sym", 
                        help="Comma-separated list of scripts to keep (default: lat,gre,punct,num,sym)")
    args = parser.parse_args()

    # Process arguments
    input_dir = os.path.abspath(args.input)
    output_dir = os.path.abspath(args.output)
    scripts_to_keep = args.scripts.split(',')
    num_threads = args.threads
    
    print_separator()
    print(f"Starting Markdown cleaning process...")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Scripts to keep: {scripts_to_keep}")
    print(f"Threads: {num_threads}")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Record start time
    start_time = time.time()
    
    # Check if we have the batch processing function
    if hasattr(text_cleaner_rs, 'batch_clean_and_analyze_files'):
        print(f"Using batch_clean_and_analyze_files for parallel processing")
        result = text_cleaner_rs.batch_clean_and_analyze_files(
            input_dir,
            output_dir,
            scripts_to_keep,
            num_threads
        )
        
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Message: {result.get('message', 'No message provided')}")
        print(f"Files processed successfully: {result.get('files_processed_successfully', 0)}")
        print(f"Files with errors: {result.get('files_with_errors', 0)}")
        print(f"Total files found: {result.get('total_files_found', 0)}")
        
    elif hasattr(text_cleaner_rs, 'batch_clean_markdown_files'):
        print(f"Using batch_clean_markdown_files for parallel processing")
        result = text_cleaner_rs.batch_clean_markdown_files(
            input_dir,
            output_dir,
            scripts_to_keep,
            num_threads
        )
        
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Message: {result.get('message', 'No message provided')}")
        print(f"Files processed: {result.get('files_processed', 0)}")
        print(f"Files with errors: {result.get('files_with_errors', 0)}")
        print(f"Total files found: {result.get('total_files_found', 0)}")
        
    else:
        print("Falling back to process_directory_native function")
        result = text_cleaner_rs.process_directory_native(
            input_dir,
            output_dir,
            scripts_to_keep,
            num_threads
        )
        
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Message: {result.get('message', 'No message provided')}")
        print(f"Files processed: {result.get('files_processed', 0)}")
        
    # Calculate elapsed time
    elapsed_time = time.time() - start_time
    print_separator()
    print(f"Markdown cleaning completed in {elapsed_time:.2f} seconds")
    print_separator()

if __name__ == "__main__":
    main() 