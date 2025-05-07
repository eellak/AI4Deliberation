#!/usr/bin/env python3
"""
Text cleaner script that uses the Rust-based text_cleaner_rs module to process
a directory of markdown files in parallel.
"""
import text_cleaner_rs
import time
import sys
import os

def print_separator():
    """Print a visual separator line."""
    print("-" * 80)

def main():
    """
    Process markdown files using Rust-based text cleaner.
    
    Uses text_cleaner_rs.process_directory_native to process all markdown files
    from the input directory and save cleaned versions to the output directory.
    """
    # Check if output directory exists and create it if necessary
    input_dir = "/mnt/data/gazette_processing/markdown"
    output_dir = "/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/check_badness/sample_cleaned_markdown"
    
    # Make sure output directory exists
    os.makedirs(output_dir, exist_ok=True)
        
    # Scripts to keep - USING THE CORRECT SCRIPT CODES to match v2
    scripts_to_keep = ["gre", "lat", "fra", "punct", "num", "sym"]
    
    # Use 0 for automatic thread count (Rayon will decide based on CPU cores)
    num_threads = 0
    
    print_separator()
    print(f"Starting batch text cleaning...")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Scripts to keep: {scripts_to_keep}")
    print(f"Threads: {'auto' if num_threads == 0 else num_threads}")
    print_separator()
    
    start_time = time.time()
    
    try:
        # Call the Rust batch processing function
        result = text_cleaner_rs.process_directory_native(
            input_dir,
            output_dir,
            scripts_to_keep,
            num_threads
        )
        
        # Calculate elapsed time
        elapsed_time = time.time() - start_time
        
        # Display results
        print(f"Processing completed in {elapsed_time:.2f} seconds")
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Message: {result.get('message', 'No message provided')}")
        print(f"Files processed: {result.get('files_processed', 0)}")
        print(f"Files with errors: {result.get('files_with_errors', 0)}")
        print(f"Total files found: {result.get('total_files_found', 0)}")
        print_separator()
        
        return 0
    except Exception as e:
        print(f"Error: {e}")
        print_separator()
        return 1

if __name__ == "__main__":
    sys.exit(main())
