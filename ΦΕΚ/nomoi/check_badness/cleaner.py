#!/usr/bin/env python3
"""
Comprehensive text cleaning script that uses the refactored Rust-based text_cleaner_rs module
to process markdown files and generate a CSV with badness scores.
"""
import text_cleaner_rs
import time
import sys
import os
import csv
from pathlib import Path
import argparse

def print_separator():
    """Print a visual separator line."""
    print("-" * 80)

def analyze_text_metrics(text):
    """Calculate text metrics for the given string."""
    # Logic to calculate text metrics (implement based on your requirements)
    total_chars = len(text)
    non_whitespace = sum(1 for c in text if not c.isspace())
    lines = text.count('\n') + 1
    
    # Return a dictionary of metrics
    return {
        'total_chars': total_chars,
        'non_whitespace_chars': non_whitespace,
        'lines': lines,
        # You can add more metrics here
    }

def main():
    """
    Process markdown files and generate badness scores CSV.
    """
    parser = argparse.ArgumentParser(description="Clean markdown files and generate badness scores")
    parser.add_argument("--input", default="/mnt/data/gazette_processing/markdown", 
                       help="Input directory containing markdown files")
    parser.add_argument("--output", default="/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/check_badness/sample_cleaned_markdown_v5", 
                       help="Output directory for cleaned files")
    parser.add_argument("--metrics", default="/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/check_badness/text_metrics.csv", 
                       help="Output CSV file for text metrics/badness scores")
    parser.add_argument("--threads", type=int, default=0, 
                       help="Number of threads (0 = auto)")
    args = parser.parse_args()

    # Input and output paths
    input_dir = args.input
    output_dir = args.output
    metrics_file = args.metrics
    
    # Check if output directory exists and create it if necessary
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Scripts to keep (character sets to preserve)
    scripts_to_keep = ["greek", "latin", "numbers", "punctuation", "common_symbols"]
    
    print_separator()
    print(f"Starting Markdown cleaning process with metrics collection...")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Metrics CSV: {metrics_file}")
    print(f"Scripts to keep: {scripts_to_keep}")
    print_separator()
    
    # Record start time
    start_time = time.time()
    
    # Use the Rust cleaning function
    if hasattr(text_cleaner_rs, 'batch_clean_markdown_files'):
        print("Using new API: batch_clean_markdown_files")
        results = text_cleaner_rs.batch_clean_markdown_files(
            input_dir,
            output_dir,
            scripts_to_keep,
            args.threads
        )
    else:
        print("Using compatibility API: process_directory_native")
        results = text_cleaner_rs.process_directory_native(
            input_dir,
            output_dir,
            scripts_to_keep,
            args.threads
        )
    
    # Calculate elapsed time
    elapsed_time = time.time() - start_time
    
    # Print results
    print_separator()
    print(f"Cleaning completed in {elapsed_time:.2f} seconds")
    
    if isinstance(results, dict):
        files_processed = results.get('files_processed', 'N/A')
        files_with_errors = results.get('files_with_errors', 'N/A')
        print(f"Files processed: {files_processed}")
        print(f"Files with errors: {files_with_errors}")
    
    # Now collect metrics for each file and write to CSV
    print_separator()
    print(f"Collecting text metrics and generating badness scores...")
    
    # Initialize CSV file
    Path(metrics_file).parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_file, 'w', newline='') as csvfile:
        fieldnames = [
            'file', 'original_size', 'cleaned_size', 'size_reduction', 
            'original_lines', 'cleaned_lines', 'unusual_chars', 
            'badness_score'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        # Walk through output directory and collect metrics
        files_processed = 0
        for root, _, files in os.walk(output_dir):
            for file in sorted(files):
                if file.endswith('.md'):
                    files_processed += 1
                    
                    # Get relative path for reporting
                    output_file = os.path.join(root, file)
                    rel_path = os.path.relpath(output_file, output_dir)
                    
                    # Find corresponding input file
                    rel_dir = os.path.dirname(rel_path)
                    input_file = os.path.join(input_dir, rel_path)
                    
                    # Skip if input file doesn't exist
                    if not os.path.exists(input_file):
                        continue
                    
                    # Read original and cleaned content
                    try:
                        with open(input_file, 'r', encoding='utf-8') as f:
                            original_content = f.read()
                        
                        with open(output_file, 'r', encoding='utf-8') as f:
                            cleaned_content = f.read()
                            
                        # Calculate metrics
                        original_size = len(original_content)
                        cleaned_size = len(cleaned_content)
                        size_reduction = ((original_size - cleaned_size) / original_size * 100) if original_size > 0 else 0
                        
                        original_lines = original_content.count('\n') + 1
                        cleaned_lines = cleaned_content.count('\n') + 1
                        
                        # Count unusual characters (if you have a function for it)
                        # This is a placeholder, implement based on your definition of "unusual"
                        unusual_chars = sum(1 for c in original_content if ord(c) > 127)
                        
                        # Calculate badness score (customize formula based on your criteria)
                        badness_score = (unusual_chars / original_size * 100) if original_size > 0 else 0
                        
                        # Write metrics to CSV
                        writer.writerow({
                            'file': rel_path,
                            'original_size': original_size,
                            'cleaned_size': cleaned_size,
                            'size_reduction': f"{size_reduction:.2f}%",
                            'original_lines': original_lines,
                            'cleaned_lines': cleaned_lines,
                            'unusual_chars': unusual_chars,
                            'badness_score': f"{badness_score:.2f}"
                        })
                        
                        # Show progress every 100 files
                        if files_processed % 100 == 0:
                            print(f"Processed metrics for {files_processed} files...")
                    
                    except Exception as e:
                        print(f"Error processing {rel_path}: {e}")
    
    print(f"Metrics collection completed. Processed {files_processed} files.")
    print(f"Badness scores saved to: {metrics_file}")

if __name__ == "__main__":
    main()
