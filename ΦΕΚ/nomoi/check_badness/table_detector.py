#!/usr/bin/env python3
"""
Compatible table detector script that uses the available text_cleaner_rs module 
functions to analyze markdown files and detect malformed tables.
"""
import text_cleaner_rs
import time
import sys
import os
import csv
from pathlib import Path
import argparse
import concurrent.futures

def print_separator():
    """Print a visual separator line."""
    print("-" * 80)

def analyze_file(file_path):
    """Analyze a single markdown file for table issues."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # If the refactored API is available, use it
        if hasattr(text_cleaner_rs, 'analyze_tables_in_string'):
            issues = text_cleaner_rs.analyze_tables_in_string(content)
            return file_path, issues, None
        elif hasattr(text_cleaner_rs, 'detect_malformed_tables'):
            issues = text_cleaner_rs.detect_malformed_tables(content)
            return file_path, issues, None
        else:
            # Fallback: perform a simple regex-based detection in Python
            import re
            table_issues = []
            lines = content.split('\n')
            separator_pattern = re.compile(r'^\s*\|[\s\-:]+\|\s*$')
            
            for i, line in enumerate(lines):
                if separator_pattern.match(line):
                    table_issues.append({
                        'line_number': i + 1,
                        'description': "Table separator detected (Python fallback)",
                        'expected_columns': None,
                        'found_columns': None
                    })
            return file_path, table_issues, None
            
    except Exception as e:
        return file_path, [], str(e)

def main():
    """
    Analyze markdown files for table issues using available functions.
    """
    parser = argparse.ArgumentParser(description="Detect table issues in markdown files")
    parser.add_argument("--input", default="/mnt/data/gazette_processing/markdown", 
                        help="Input directory containing markdown files")
    parser.add_argument("--output", default="/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/check_badness/table_issues_report.csv", 
                        help="Output CSV file for table issues report")
    parser.add_argument("--threads", type=int, default=4, 
                        help="Number of threads for processing")
    parser.add_argument("--sample", type=int, default=0,
                        help="Process only a sample of files (0 = all files)")
    args = parser.parse_args()

    # Input path
    input_dir = args.input
    output_file = args.output
    
    print_separator()
    print(f"Starting Markdown table analysis process...")
    print(f"Input directory: {input_dir}")
    print(f"Output report file: {output_file}")
    print_separator()
    
    # Collect markdown files
    markdown_files = []
    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith('.md'):
                markdown_files.append(os.path.join(root, file))
    
    # Limit to sample size if specified
    if args.sample > 0 and args.sample < len(markdown_files):
        import random
        markdown_files = random.sample(markdown_files, args.sample)
        print(f"Using a sample of {args.sample} files")
    
    total_files = len(markdown_files)
    print(f"Found {total_files} markdown files to analyze")
    
    # Record start time
    start_time = time.time()
    
    # Process files in parallel
    results = []
    files_with_issues = 0
    total_issues = 0
    files_with_errors = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {executor.submit(analyze_file, file_path): file_path for file_path in markdown_files}
        
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            if i % 100 == 0 and i > 0:
                elapsed = time.time() - start_time
                print(f"Processed {i}/{total_files} files ({i/total_files*100:.1f}%) in {elapsed:.2f} seconds")
            
            file_path, issues, error = future.result()
            if error:
                files_with_errors += 1
            
            if issues:
                files_with_issues += 1
                total_issues += len(issues)
                results.append((file_path, issues))
    
    # Calculate elapsed time
    elapsed_time = time.time() - start_time
    
    # Print analysis results
    print_separator()
    print(f"Table analysis completed in {elapsed_time:.2f} seconds")
    print(f"Files processed: {total_files}")
    print(f"Files with errors: {files_with_errors}")
    print(f"Files with table issues: {files_with_issues}")
    print(f"Total table issues found: {total_issues}")
    
    # Write issues to CSV file
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', newline='') as csvfile:
        fieldnames = ['file', 'line_number', 'description', 'expected_columns', 'found_columns']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for file_path, issues in results:
            rel_path = os.path.relpath(file_path, input_dir)
            for issue in issues:
                # Handle both object-style issues and dict-style issues
                if hasattr(issue, 'line_number'):
                    # Object-style (from Rust)
                    writer.writerow({
                        'file': rel_path,
                        'line_number': issue.line_number,
                        'description': issue.description,
                        'expected_columns': issue.expected_columns if hasattr(issue, 'expected_columns') else None,
                        'found_columns': issue.found_columns if hasattr(issue, 'found_columns') else None
                    })
                else:
                    # Dict-style (from Python fallback)
                    writer.writerow({
                        'file': rel_path,
                        'line_number': issue['line_number'],
                        'description': issue['description'],
                        'expected_columns': issue['expected_columns'],
                        'found_columns': issue['found_columns']
                    })
    
    print_separator()
    print(f"Table issues report saved to: {output_file}")

if __name__ == "__main__":
    main()
