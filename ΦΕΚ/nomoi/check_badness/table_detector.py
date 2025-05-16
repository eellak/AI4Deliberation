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

def main():
    """
    Invokes the Rust batch function to analyze markdown files and generate a table summary CSV.
    The CSV will contain: file, total_tables, malformed_tables.
    """
    parser = argparse.ArgumentParser(
        description="Generate a table summary CSV from markdown files using Rust batch processing."
    )
    parser.add_argument(
        "--input", 
        required=True, # Make input mandatory
        help="Input directory containing markdown files."
    )
    parser.add_argument(
        "--output", 
        default="./reports_gazette/table_summary_report.csv", # Default relative to script execution or CWD
        help="Output CSV file for table summary report (default: ./reports_gazette/table_summary_report.csv)"
    )
    parser.add_argument(
        "--threads", 
        type=int, 
        default=0, # Default to 0, let Rust/Rayon decide optimal threads based on cores
        help="Number of threads for processing (0 = Rayon default, usually number of logical cores)."
    )
    # Sample argument might be harder to implement if Rust batch doesn't support it directly.
    # For now, removing it to simplify, assuming full directory processing by Rust.
    # parser.add_argument("--sample", type=int, default=0,
    #                     help="Process only a sample of files (0 = all files) - NOT CURRENTLY SUPPORTED IN BATCH MODE")

    args = parser.parse_args()

    input_dir = args.input
    output_file = args.output
    num_threads = args.threads

    # Ensure the output directory exists before calling Rust
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print_separator()
    print(f"Starting Markdown table summary generation via Rust batch processing...")
    print(f"Input directory: {input_dir}")
    print(f"Output summary report file: {output_file}")
    print(f"Number of threads: {'Rayon default' if num_threads == 0 else num_threads}")
    print_separator()

    start_time = time.time()

    try:
        # Call the Rust batch function
        # The text_cleaner_rs module should be in PYTHONPATH or installed in the environment
        text_cleaner_rs.batch_generate_table_summary_csv(
            input_dir, output_file, num_threads
        )
        
        elapsed_time = time.time() - start_time
        print_separator()
        print(f"Rust batch processing completed in {elapsed_time:.2f} seconds.")
        print(f"Table summary report saved to: {output_file}")
        print_separator()

    except Exception as e:
        elapsed_time = time.time() - start_time
        print_separator()
        print(f"An error occurred after {elapsed_time:.2f} seconds during Rust batch processing:")
        print(f"{e}")
        print_separator()
        sys.exit(1) # Exit with an error code

if __name__ == "__main__":
    main()
