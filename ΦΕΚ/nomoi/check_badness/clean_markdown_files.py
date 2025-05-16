#!/usr/bin/env python3
"""
Script to clean Markdown files using the text_cleaner_rs Rust module.
This processes files and outputs them to a specified directory.
It can also generate a CSV report with text analysis metrics.
"""
import text_cleaner_rs
import time
import sys
import os
import argparse
import csv # Retained for now, though Rust handles CSV writing directly.
from pathlib import Path
# import concurrent.futures # Keep for potential future parallelization of Python part

def print_separator():
    """Print a visual separator line."""
    print("-" * 80)

def invoke_rust_analysis_and_report(
    input_dir_str: str, 
    csv_output_path: str, 
    cleaned_files_output_dir: str or None, # New parameter
    scripts_to_analyze: list, 
    num_threads: int
):
    """
    Invokes the Rust function to perform analysis, optionally save cleaned files, and generate the CSV report directly.
    """
    print_separator()
    print(f"Starting Rust-based unified processing...")
    print(f"Input directory: {input_dir_str}")
    if cleaned_files_output_dir:
        print(f"Output directory for cleaned files: {cleaned_files_output_dir}")
    else:
        print(f"Cleaned files will not be saved.")
    if csv_output_path:
        print(f"Output CSV: {csv_output_path}")
    else:
        print(f"CSV report will not be generated.")
        
    print(f"Scripts for analysis/cleaning: {scripts_to_analyze}")
    print(f"Threads: {num_threads}")

    processing_start_time = time.time()
    
    try:
        # Call the unified Rust function
        # Note: The Rust function expects Option<&str> for cleaned_files_output_dir
        # In Python, we pass None or a string. PyO3 handles the conversion.
        text_cleaner_rs.generate_analysis_report_for_directory(
            input_dir_str,
            csv_output_path if csv_output_path else "", # Pass empty string if None, Rust side should handle
            cleaned_files_output_dir, # Pass None or path string
            scripts_to_analyze,
            num_threads
        )
        print(f"Rust function generate_analysis_report_for_directory completed.")
        if csv_output_path: print(f"Analysis report should be at {csv_output_path}")
        if cleaned_files_output_dir: print(f"Cleaned files should be in {cleaned_files_output_dir}")

    except Exception as e:
        print(f"\nError calling Rust function generate_analysis_report_for_directory: {e}")

    processing_elapsed_time = time.time() - processing_start_time
    print(f"Rust-based unified processing completed in {processing_elapsed_time:.2f} seconds.")
    print_separator()

def main():
    """
    Clean markdown files and/or generate analysis CSV using the Rust module.
    """
    parser = argparse.ArgumentParser(
        description="Clean Markdown files and/or generate analysis CSV using Rust module."
    )
    parser.add_argument("--input", default="ΦΕΚ/nomoi/check_badness", 
                        help="Input directory containing markdown files")
    parser.add_argument("--output", default=None,  # Changed default to None
                        help="Output directory for cleaned markdown files (optional)")
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4, 
                        help="Number of threads for Rust batch processing (default: all available cores or 4)")
    parser.add_argument("--scripts", type=str, default="greek,latin", 
                        help="Comma-separated list of scripts to keep/analyze (default: greek,latin)")
    parser.add_argument("--analysis_csv", type=str, default=None, # Changed default to None
                        help="Output path for the analysis CSV report (optional)")

    args = parser.parse_args()

    input_dir = os.path.abspath(args.input)
    scripts_for_rust = [s.strip() for s in args.scripts.split(',') if s.strip()]
    num_threads = args.threads
    output_cleaned_dir = os.path.abspath(args.output) if args.output else None
    analysis_csv_path = os.path.abspath(args.analysis_csv) if args.analysis_csv else None

    overall_start_time = time.time()

    if not output_cleaned_dir and not analysis_csv_path:
        print("Neither --output nor --analysis_csv were specified. Nothing to do.")
        sys.exit(0)

    # Constructing a more comprehensive list of scripts for the Rust function.
    # The Rust function will use this for both allowed_chars in cleaning and for analysis.
    # Ensure core scripts for cleaning are present if scripts_for_rust is minimal.
    # This logic ensures that cleaning within the Rust function is comprehensive.
    base_scripts = ["punctuation", "numbers", "common_symbols"]
    final_scripts_for_rust = list(set(scripts_for_rust + base_scripts))

    # Unified call to the Rust backend
    invoke_rust_analysis_and_report(
        input_dir, 
        analysis_csv_path, 
        output_cleaned_dir, 
        final_scripts_for_rust, 
        num_threads
    )

    overall_elapsed_time = time.time() - overall_start_time
    print(f"Total script execution time: {overall_elapsed_time:.2f} seconds.")
    print_separator()

if __name__ == "__main__":
    main() 