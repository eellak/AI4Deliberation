#!/usr/bin/env python3
"""
Wrapper script to invoke Rust-based table analysis and summary generation.
Primarily uses the batch processing capabilities of the text_cleaner_rs module.
"""
import text_cleaner_rs
import time
import sys
import os
from pathlib import Path
import argparse
# concurrent.futures is no longer needed if all batching is in Rust.

def print_separator():
    """Print a visual separator line."""
    print("-" * 80)

# The analyze_file function (Python-side single file processing)
# is now removed as the primary path is the Rust batch processing.
# If a debug mode for single files is needed, it could be re-added
# and use text_cleaner_rs.analyze_tables_in_string.

def run_table_detection(input_dir_str: str, output_summary_csv_str: str, num_threads: int):
    """
    Invokes the Rust batch function to analyze markdown files and generate a table summary CSV.
    The CSV will contain: file, total_tables, malformed_tables.

    Args:
        input_dir_str: Path to the input directory.
        output_summary_csv_str: Path to the output CSV file for the table summary.
        num_threads: Number of threads for processing (0 = Rayon default).
    """
    # Ensure the output directory exists before calling Rust
    output_path = Path(output_summary_csv_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print_separator()
    print(f"Starting Markdown table summary generation via Rust batch processing...")
    print(f"Input directory: {input_dir_str}")
    print(f"Output summary report file: {output_summary_csv_str}")
    print(f"Number of threads: {'Rayon default' if num_threads == 0 else num_threads}")
    print_separator()

    start_time = time.time()
    returned_report_path = None

    try:
        text_cleaner_rs.batch_generate_table_summary_csv(
            input_dir_str, output_summary_csv_str, num_threads
        )
        returned_report_path = output_summary_csv_str # Assume success means file is created
        
        elapsed_time = time.time() - start_time
        print_separator()
        print(f"Rust batch processing completed in {elapsed_time:.2f} seconds.")
        print(f"Table summary report saved to: {output_summary_csv_str}")
        print_separator()

    except Exception as e:
        elapsed_time = time.time() - start_time
        print_separator()
        print(f"An error occurred after {elapsed_time:.2f} seconds during Rust batch processing:")
        print(f"{e}")
        print_separator()
        raise # Re-raise the exception to be handled by the caller
    
    return {"summary_csv_path": returned_report_path}

def main():
    """
    CLI entry point.
    """
    parser = argparse.ArgumentParser(
        description="Generate a table summary CSV from markdown files using Rust batch processing."
    )
    parser.add_argument(
        "--input", 
        required=True,
        help="Input directory containing markdown files."
    )
    parser.add_argument(
        "--output", 
        required=True, # Make output CSV path mandatory for CLI use
        help="Output CSV file for table summary report."
    )
    parser.add_argument(
        "--threads", 
        type=int, 
        default=0, 
        help="Number of threads for processing (0 = Rayon default, usually number of logical cores)."
    )

    args = parser.parse_args()
    
    input_dir_abs = os.path.abspath(args.input)
    output_csv_abs = os.path.abspath(args.output)

    try:
        run_table_detection(input_dir_abs, output_csv_abs, args.threads)
    except Exception as e:
        print(f"Table detection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
