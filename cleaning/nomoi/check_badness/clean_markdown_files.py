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
# import csv # Retained for now, though Rust handles CSV writing directly. # No longer needed
from pathlib import Path
# import concurrent.futures # Keep for potential future parallelization of Python part

def print_separator():
    """Print a visual separator line."""
    print("-" * 80)

def run_initial_cleaning_and_analysis(
    input_dir_str: str, 
    output_cleaned_dir_str: str | None, 
    output_analysis_csv_str: str | None, 
    scripts_to_keep_input_str: str, # e.g., "greek,latin"
    num_threads: int,
    perform_cleaning_if_output_dir_specified: bool = True # New flag
):
    """
    Cleans and/or analyzes markdown files using the Rust backend.

    Args:
        input_dir_str: Path to the input directory.
        output_cleaned_dir_str: Path to the output directory for cleaned files.
                                If None, or if perform_cleaning is False, files are not written.
        output_analysis_csv_str: Path to the output CSV for analysis. If None, CSV is not generated.
        scripts_to_keep_input_str: Comma-separated string of scripts to keep (e.g., "greek,latin").
                                   Core scripts like punctuation, numbers, common_symbols are always added.
        num_threads: Number of threads for processing.
        perform_cleaning_if_output_dir_specified: If True and output_cleaned_dir_str is provided,
                                                  cleaned files are written. If False, cleaned files
                                                  are not written (analysis only).
    """
    print_separator()
    print(f"Starting Rust-based cleaning/analysis...")
    print(f"Input directory: {input_dir_str}")

    # Determine scripts for Rust
    user_scripts = [s.strip() for s in scripts_to_keep_input_str.split(',') if s.strip()]
    base_scripts = ["punctuation", "numbers", "common_symbols"]
    final_scripts_for_rust = list(set(user_scripts + base_scripts))
    print(f"Effective scripts for Rust (user + base): {final_scripts_for_rust}")

    # Determine if cleaned files should be written by Rust
    cleaned_files_output_dir_for_rust_call = None
    if output_cleaned_dir_str and perform_cleaning_if_output_dir_specified:
        cleaned_files_output_dir_for_rust_call = output_cleaned_dir_str
        print(f"Output directory for cleaned files: {cleaned_files_output_dir_for_rust_call}")
    elif output_cleaned_dir_str and not perform_cleaning_if_output_dir_specified:
        print(f"Analysis-only mode: Cleaned files will NOT be written to {output_cleaned_dir_str} (if provided).")
    elif not output_cleaned_dir_str:
         print(f"Output directory for cleaned files: Not specified.")


    if output_analysis_csv_str:
        print(f"Output CSV: {output_analysis_csv_str}")
    else:
        print(f"CSV report will not be generated (path not specified).")
        
    print(f"Threads: {num_threads}")

    processing_start_time = time.time()
    
    try:
        text_cleaner_rs.generate_analysis_report_for_directory(
            input_dir_str,
            output_analysis_csv_str if output_analysis_csv_str else "",
            cleaned_files_output_dir_for_rust_call,
            final_scripts_for_rust,
            num_threads
        )
        print(f"Rust function generate_analysis_report_for_directory completed.")
        if output_analysis_csv_str: print(f"Analysis report should be at {output_analysis_csv_str}")
        if cleaned_files_output_dir_for_rust_call: print(f"Cleaned files should be in {cleaned_files_output_dir_for_rust_call}")

    except Exception as e:
        print(f"\nError calling Rust function generate_analysis_report_for_directory: {e}")
        # Potentially re-raise or return an error status
        raise

    processing_elapsed_time = time.time() - processing_start_time
    print(f"Rust-based processing for this step completed in {processing_elapsed_time:.2f} seconds.")
    print_separator()
    
    # Return paths for orchestration
    return {
        "cleaned_output_dir": cleaned_files_output_dir_for_rust_call,
        "analysis_csv": output_analysis_csv_str
    }

def main():
    """
    CLI entry point: Clean markdown files and/or generate analysis CSV using the Rust module.
    """
    parser = argparse.ArgumentParser(
        description="Clean Markdown files and/or generate analysis CSV using Rust module."
    )
    parser.add_argument("--input", required=True,
                        help="Input directory containing markdown files")
    parser.add_argument("--output", default=None,
                        help="Output directory for cleaned markdown files (optional, enables cleaning output)")
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4, 
                        help="Number of threads for Rust batch processing (default: all available cores or 4)")
    parser.add_argument("--scripts", type=str, default="lat,grc", # Changed default to lat,grc to match typical use
                        help="Comma-separated list of primary scripts to keep/analyze (e.g., lat,grc). Base scripts (punctuation, numbers, symbols) are always included.")
    parser.add_argument("--analysis_csv", type=str, default=None,
                        help="Output path for the analysis CSV report (optional)")

    args = parser.parse_args()

    input_dir_abs = os.path.abspath(args.input)
    output_cleaned_abs = os.path.abspath(args.output) if args.output else None
    analysis_csv_abs = os.path.abspath(args.analysis_csv) if args.analysis_csv else None

    overall_start_time = time.time()

    if not output_cleaned_abs and not analysis_csv_abs:
        print("Neither --output (for cleaned files) nor --analysis_csv were specified. Nothing to do.")
        sys.exit(0)

    try:
        run_initial_cleaning_and_analysis(
            input_dir_str=input_dir_abs,
            output_cleaned_dir_str=output_cleaned_abs,
            output_analysis_csv_str=analysis_csv_abs,
            scripts_to_keep_input_str=args.scripts,
            num_threads=args.threads,
            perform_cleaning_if_output_dir_specified=True # CLI always intends to clean if --output is given
        )
    except Exception as e:
        print(f"Pipeline step failed: {e}")
        sys.exit(1)


    overall_elapsed_time = time.time() - overall_start_time
    print(f"Total script execution time: {overall_elapsed_time:.2f} seconds.")
    print_separator()

if __name__ == "__main__":
    main() 