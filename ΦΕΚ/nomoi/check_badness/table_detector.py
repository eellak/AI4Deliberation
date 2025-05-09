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
        
        if hasattr(text_cleaner_rs, 'analyze_tables_in_string'):
            # This is the path we expect to be taken.
            # analyze_tables_in_string should return Vec<Py<TableIssue>> from Rust
            issues_from_rust = text_cleaner_rs.analyze_tables_in_string(content)
            # print(f"DEBUG: For {file_path}, analyze_tables_in_string returned: {type(issues_from_rust)} - {issues_from_rust}") # Optional detailed debug
            return file_path, issues_from_rust, None 
        elif hasattr(text_cleaner_rs, 'detect_malformed_tables'): # Older/alternative Rust function name
            issues_from_rust = text_cleaner_rs.detect_malformed_tables(content)
            return file_path, issues_from_rust, None
        else:
            # Fallback: perform a simple regex-based detection in Python
            import re
            table_issues_py = []
            lines = content.split('\n')
            separator_pattern = re.compile(r'^\s*\|[\s\-:]+\|\s*$')
            for i, line in enumerate(lines):
                if separator_pattern.match(line):
                    table_issues_py.append({
                        'line_number': i + 1,
                        'description': "Table separator detected (Python fallback)",
                        'expected_columns': None,
                        'found_columns': None
                    })
            return file_path, table_issues_py, None
            
    except Exception as e:
        print(f"ERROR in analyze_file for {file_path}: {e}")
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

    input_dir = args.input
    output_file = args.output
    
    print_separator()
    print(f"Starting Markdown table analysis process...")
    print(f"Input directory: {input_dir}")
    print(f"Output report file: {output_file}")
    print_separator()
    
    markdown_files = []
    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith('.md'):
                markdown_files.append(os.path.join(root, file))
    
    if args.sample > 0 and args.sample < len(markdown_files):
        import random
        markdown_files = random.sample(markdown_files, args.sample)
        print(f"Using a sample of {args.sample} files")
    
    total_files = len(markdown_files)
    print(f"Found {total_files} markdown files to analyze")
    
    start_time = time.time()
    
    results = []
    files_with_issues_count = 0
    total_issues_count = 0
    files_with_errors_count = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {executor.submit(analyze_file, file_path): file_path for file_path in markdown_files}
        
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            if i % 100 == 0 and i > 0:
                elapsed = time.time() - start_time
                print(f"Processed {i}/{total_files} files ({i/total_files*100:.1f}%) in {elapsed:.2f} seconds")
            
            file_path, issues_obj, error_msg = future.result()
            if error_msg:
                files_with_errors_count += 1
            
            if issues_obj: # This could be a list of TableIssues or the tuple (int, list)
                # If Rust returned (total_tables, issues_list)
                if isinstance(issues_obj, tuple) and len(issues_obj) == 2 and isinstance(issues_obj[0], int):
                    actual_issues_list = issues_obj[1]
                else:
                    actual_issues_list = issues_obj # Assume it's already the list of issues
                
                if actual_issues_list: # If there are actual issues in the list
                    files_with_issues_count += 1
                    total_issues_count += len(actual_issues_list)
                    results.append((file_path, actual_issues_list)) # Store the list of issues
    
    elapsed_time = time.time() - start_time
    
    print_separator()
    print(f"Table analysis completed in {elapsed_time:.2f} seconds")
    print(f"Files processed: {total_files}")
    print(f"Files with errors: {files_with_errors_count}")
    print(f"Files with table issues: {files_with_issues_count}")
    print(f"Total table issues found: {total_issues_count}")
    
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['file', 'line_number', 'description', 'expected_columns', 'found_columns']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for file_path, issues_list_for_file in results:
            rel_path = os.path.relpath(file_path, input_dir)
            for issue_item in issues_list_for_file:
                print(f"DEBUG: CSV Loop: Processing issue_item: {issue_item} of type {type(issue_item)} for file {rel_path}")
                if hasattr(issue_item, 'line_number'):
                    writer.writerow({
                        'file': rel_path,
                        'line_number': issue_item.line_number,
                        'description': issue_item.description,
                        'expected_columns': issue_item.expected_columns if hasattr(issue_item, 'expected_columns') else None,
                        'found_columns': issue_item.found_columns if hasattr(issue_item, 'found_columns') else None
                    })
                else:
                    # This block should ideally not be reached if Rust returns Vec<Py<TableIssue>> correctly.
                    print(f"WARNING: issue_item for file {rel_path} is NOT a TableIssue object. Type: {type(issue_item)}, Value: {issue_item}")
                    # Attempting to treat as dict, which was the source of the original error
                    try:
                        writer.writerow({
                            'file': rel_path,
                            'line_number': issue_item['line_number'], 
                            'description': issue_item['description'],
                            'expected_columns': issue_item.get('expected_columns'),
                            'found_columns': issue_item.get('found_columns')
                        })
                    except TypeError as te:
                        print(f"ERROR: TypeError when processing unexpected issue_item {issue_item} for {rel_path}: {te}")
                    except KeyError as ke:
                        print(f"ERROR: KeyError when processing unexpected issue_item {issue_item} for {rel_path}: {ke}")
    
    print_separator()
    print(f"Table issues report saved to: {output_file}")

if __name__ == "__main__":
    main()
