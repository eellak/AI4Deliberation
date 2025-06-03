print("Python script execution started (pre-imports)") # DEBUG LINE
#!/usr/bin/env python3
"""
Single entry point script to run the full Rust-based document processing pipeline.
This pipeline includes:
1. Initial text cleaning.
2. Table removal.
3. Final analysis (badness score, Greek/Latin percentages).

Outputs are a directory with cleaned files and a single CSV report,
placed relative to the current working directory by default.
"""

import argparse
import os
import sys
import time
import text_cleaner_rs # Rust library
from pathlib import Path

def print_separator(char='-', length=80):
    """Print a visual separator line."""
    print(char * length)

def main():
    parser = argparse.ArgumentParser(
        description="Run the full document processing pipeline using the Rust backend.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--input-dir", 
        required=True, 
        type=str, 
        help="Input directory containing raw markdown files."
    )
    parser.add_argument(
        "--output-files-dir", 
        type=str, 
        default="./cleaned_output_files",
        help="Directory to save the final cleaned markdown files. Default: ./cleaned_output_files"
    )
    parser.add_argument(
        "--report-csv-path", 
        type=str, 
        default="./final_analysis_report.csv",
        help="Path to save the final 4-column analysis CSV report. Default: ./final_analysis_report.csv"
    )
    parser.add_argument(
        "--scripts", 
        type=str, 
        default="lat,grc",
        help="Comma-separated list of primary scripts to keep/analyze (e.g., lat,grc). Base scripts (punctuation, numbers, symbols) are always included by the Rust backend."
    )
    parser.add_argument(
        "--threads", 
        type=int, 
        default=0, # 0 typically means Rayon default (often num logical cores)
        help="Number of threads for Rust processing (0 = Rayon default)."
    )

    args = parser.parse_args()

    print_separator('=')
    print("Starting Document Processing Pipeline")
    print_separator('=')

    # Resolve paths to be absolute for clarity, though Rust should handle CWD-relative paths
    # The Rust function will create these directories if they don't exist.
    input_dir_abs = Path(args.input_dir).resolve()
    output_files_dir_abs = Path(args.output_files_dir).resolve()
    report_csv_path_abs = Path(args.report_csv_path).resolve()
    
    # Ensure parent directories for outputs exist, as Rust might only create the final dir.
    # This is good practice for the Python wrapper.
    output_files_dir_abs.parent.mkdir(parents=True, exist_ok=True)
    report_csv_path_abs.parent.mkdir(parents=True, exist_ok=True)


    print(f"Input Directory:          {input_dir_abs}")
    print(f"Output Cleaned Files Dir: {output_files_dir_abs}")
    print(f"Output Report CSV:        {report_csv_path_abs}")
    print(f"Scripts to Keep:          {args.scripts}")
    print(f"Number of Threads:        {args.threads if args.threads > 0 else 'Rayon default'}")
    print_separator('.')

    start_time = time.time()
    print(f"Python: Current time before calling Rust pipeline: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("Python: Attempting to call text_cleaner_rs.run_complete_pipeline...")

    try:
        scripts_list = [s.strip() for s in args.scripts.split(',') if s.strip()]
        
        text_cleaner_rs.run_complete_pipeline(
            str(input_dir_abs),
            str(output_files_dir_abs),
            str(report_csv_path_abs),
            scripts_list,
            args.threads
        )
        
        print("Python: Call to text_cleaner_rs.run_complete_pipeline finished.")
        print_separator('.')
        print("Pipeline completed successfully!")
        print(f"Cleaned files are in: {output_files_dir_abs}")
        print(f"Analysis report is at: {report_csv_path_abs}")

    except Exception as e:
        print_separator('!')
        print(f"Python: Pipeline execution FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        print_separator('!')
        sys.exit(1)
    finally:
        elapsed_time = time.time() - start_time
        print_separator()
        print(f"Python: Total execution time: {elapsed_time:.2f} seconds.")
        print(f"Python: Script finished at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print_separator('#')

if __name__ == "__main__":
    main() 