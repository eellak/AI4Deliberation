#!/usr/bin/env python3
"""
Master orchestrator for the document cleaning and analysis pipeline.

Provides:
- Individual calls to each stage of the cleaning/analysis process.
- A 'full-pipeline' mode to run all stages sequentially, producing a final set of 
  cleaned files and a consolidated analysis report.
"""

import argparse
import os
import sys
import time
import shutil # For cleaning up temporary directories
from pathlib import Path

# Import the refactored functions from other scripts
# Assuming they are in the same directory or PYTHONPATH is set up correctly
from clean_markdown_files import run_initial_cleaning_and_analysis
from table_detector import run_table_detection # May not be directly used in full_pipeline but good for individual calls
from table_processor import run_generate_detailed_table_report, run_remove_tables

def print_separator(char='-', length=80):
    print(char * length)

def get_abs_path(path_str):
    return os.path.abspath(path_str) if path_str else None

def main():
    parser = argparse.ArgumentParser(
        description="Master orchestrator for document cleaning and analysis pipeline.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4,
                        help="Global number of threads for Rust batch processing (default: all available cores or 4)")
    parser.add_argument("--scripts", type=str, default="lat,grc",
                        help="Global comma-separated list of primary scripts to keep/analyze (e.g., lat,grc). Used by cleaning and final analysis.")


    subparsers = parser.add_subparsers(dest='pipeline_command', required=True, title='Pipeline Commands',
                                       help='Run `%(prog)s {command} --help` for more information.')

    # --- Sub-parser for initial-clean ---
    parser_ic = subparsers.add_parser('initial-clean', help='Run only the initial cleaning and analysis stage.')
    parser_ic.add_argument("--input-dir", required=True, help="Input directory for initial cleaning.")
    parser_ic.add_argument("--output-cleaned-dir", required=True, help="Output directory for cleaned files from this stage.")
    parser_ic.add_argument("--output-analysis-csv", required=True, help="Output CSV for analysis from this stage.")

    # --- Sub-parser for detect-tables (simple pass-through, mostly for completeness) ---
    parser_dt = subparsers.add_parser('detect-tables', help='Run only table detection (generates summary CSV).')
    parser_dt.add_argument("--input-dir", required=True, help="Input directory for table detection.")
    parser_dt.add_argument("--output-summary-csv", required=True, help="Output CSV for table summary.")

    # --- Sub-parser for generate-detailed-table-report ---
    parser_gdtr = subparsers.add_parser('generate-detailed-table-report', help='Generate the detailed report needed for table removal.')
    parser_gdtr.add_argument("--input-dir", required=True, help="Input directory (typically output of initial-clean).")
    parser_gdtr.add_argument("--output-detailed-csv", required=True, help="Output CSV for detailed table issues.")

    # --- Sub-parser for remove-tables ---
    parser_rt = subparsers.add_parser('remove-tables', help='Remove tables based on a detailed report.')
    parser_rt.add_argument("--input-md-dir", required=True, help="Input directory with markdown files (typically output of initial-clean).")
    parser_rt.add_argument("--report-csv", required=True, help="Detailed table report CSV.")
    parser_rt.add_argument("--output-final-md-dir", required=True, help="Output directory for files with tables removed.")
    
    # --- Sub-parser for full-pipeline ---
    parser_fp = subparsers.add_parser('full-pipeline', help='Run the entire cleaning and table removal pipeline.')
    parser_fp.add_argument("--input-dir", required=True, help="Initial input directory with raw markdown files.")
    parser_fp.add_argument("--final-output-dir", required=True, help="Final output directory for fully cleaned files.")
    parser_fp.add_argument("--final-report-csv", required=True, help="Path for the final consolidated analysis report (badness, script %).")
    parser_fp.add_argument("--temp-dir-root", default=None, help="Optional root for temporary subdirectories (e.g., ./temp_pipeline_run). Defaults to being inside final-output-dir.")

    args = parser.parse_args()
    overall_start_time = time.time()

    # Global args
    num_threads = args.threads
    scripts_to_keep_str = args.scripts

    try:
        if args.pipeline_command == 'initial-clean':
            print_separator('=')
            print("Executing: Initial Clean Stage")
            print_separator('=')
            run_initial_cleaning_and_analysis(
                input_dir_str=get_abs_path(args.input_dir),
                output_cleaned_dir_str=get_abs_path(args.output_cleaned_dir),
                output_analysis_csv_str=get_abs_path(args.output_analysis_csv),
                scripts_to_keep_input_str=scripts_to_keep_str,
                num_threads=num_threads,
                perform_cleaning_if_output_dir_specified=True
            )

        elif args.pipeline_command == 'detect-tables':
            print_separator('=')
            print("Executing: Table Detection Stage")
            print_separator('=')
            run_table_detection(
                input_dir_str=get_abs_path(args.input_dir),
                output_summary_csv_str=get_abs_path(args.output_summary_csv),
                num_threads=num_threads
            )

        elif args.pipeline_command == 'generate-detailed-table-report':
            print_separator('=')
            print("Executing: Generate Detailed Table Report Stage")
            print_separator('=')
            run_generate_detailed_table_report(
                input_dir_str=get_abs_path(args.input_dir),
                output_csv_str=get_abs_path(args.output_detailed_csv),
                num_threads=num_threads
            )
        
        elif args.pipeline_command == 'remove-tables':
            print_separator('=')
            print("Executing: Remove Tables Stage")
            print_separator('=')
            run_remove_tables(
                input_dir_md_str=get_abs_path(args.input_md_dir),
                report_csv_str=get_abs_path(args.report_csv),
                output_dir_final_md_str=get_abs_path(args.output_final_md_dir),
                num_threads=num_threads
            )

        elif args.pipeline_command == 'full-pipeline':
            print_separator('*')
            print("Executing: Full Pipeline")
            print_separator('*')

            initial_input_dir = get_abs_path(args.input_dir)
            final_output_dir = get_abs_path(args.final_output_dir)
            final_report_csv = get_abs_path(args.final_report_csv)
            
            # Setup temporary directory structure
            if args.temp_dir_root:
                temp_base = Path(get_abs_path(args.temp_dir_root))
            else:
                temp_base = Path(final_output_dir) / "_pipeline_temp"
            
            temp_cleaned_s1_dir = temp_base / "cleaned_s1"
            temp_detailed_report_csv = temp_base / "detailed_table_report_s1.csv"
            
            # Ensure final output dir and temp dirs exist and are clean if they are the same
            Path(final_output_dir).mkdir(parents=True, exist_ok=True)
            if temp_base.exists() and temp_base.is_dir():
                 print(f"Cleaning up existing temporary base directory: {temp_base}")
                 shutil.rmtree(temp_base)
            temp_base.mkdir(parents=True, exist_ok=True)
            temp_cleaned_s1_dir.mkdir(parents=True, exist_ok=True)

            print(f"Temporary files will be stored under: {temp_base}")

            # STEP 1: Initial Cleaning (scripts + base chars removed)
            print_separator('-')
            print("FULL PIPELINE STEP 1: Initial Cleaning & Analysis")
            run_initial_cleaning_and_analysis(
                input_dir_str=initial_input_dir,
                output_cleaned_dir_str=str(temp_cleaned_s1_dir),
                output_analysis_csv_str=None, # We don't need the analysis CSV from this intermediate step
                scripts_to_keep_input_str=scripts_to_keep_str,
                num_threads=num_threads,
                perform_cleaning_if_output_dir_specified=True
            )
            print("FULL PIPELINE STEP 1: Completed.")

            # STEP 2: Generate Detailed Table Report (on S1 cleaned files)
            print_separator('-')
            print("FULL PIPELINE STEP 2: Generating Detailed Table Report")
            run_generate_detailed_table_report(
                input_dir_str=str(temp_cleaned_s1_dir),
                output_csv_str=str(temp_detailed_report_csv),
                num_threads=num_threads
            )
            print("FULL PIPELINE STEP 2: Completed.")

            # STEP 3: Remove Tables (using S1 cleaned files and detailed report, output to FINAL dir)
            print_separator('-')
            print("FULL PIPELINE STEP 3: Removing Tables")
            run_remove_tables(
                input_dir_md_str=str(temp_cleaned_s1_dir),
                report_csv_str=str(temp_detailed_report_csv),
                output_dir_final_md_str=final_output_dir, # Output directly to the final destination
                num_threads=num_threads
            )
            print("FULL PIPELINE STEP 3: Completed. Final MD files should be in", final_output_dir)

            # STEP 4: Final Analysis (on S2 table-removed files in final_output_dir)
            print_separator('-')
            print("FULL PIPELINE STEP 4: Generating Final Analysis Report")
            # Use run_initial_cleaning_and_analysis in analysis-only mode
            run_initial_cleaning_and_analysis(
                input_dir_str=final_output_dir, # Analyze the final cleaned files
                output_cleaned_dir_str=None,    # Don't write cleaned files again
                output_analysis_csv_str=final_report_csv, # This is the main CSV output we want
                scripts_to_keep_input_str=scripts_to_keep_str, # For consistent script % calculation
                num_threads=num_threads,
                perform_cleaning_if_output_dir_specified=False # CRITICAL: Analysis only
            )
            print(f"FULL PIPELINE STEP 4: Completed. Final analysis report at {final_report_csv}")
            
            # STEP 5: Cleanup temporary files
            print_separator('-')
            print(f"FULL PIPELINE STEP 5: Cleaning up temporary directory: {temp_base}")
            try:
                shutil.rmtree(temp_base)
                print(f"Successfully removed temporary directory: {temp_base}")
            except Exception as e_shutil:
                print(f"Warning: Could not remove temporary directory {temp_base}: {e_shutil}")
            print("FULL PIPELINE STEP 5: Completed.")

            print_separator('*')
            print("Full pipeline completed successfully!")
            print(f"Final cleaned files in: {final_output_dir}")
            print(f"Final analysis report: {final_report_csv}")
            print_separator('*')

    except Exception as e:
        print_separator('!')
        print(f"Pipeline command '{args.pipeline_command}' failed critically: {e}")
        # Consider printing traceback for more detail
        import traceback
        traceback.print_exc()
        print_separator('!')
        sys.exit(1)
    finally:
        overall_elapsed_time = time.time() - overall_start_time
        print_separator('#')
        print(f"Total orchestrator execution time for command '{args.pipeline_command}': {overall_elapsed_time:.2f} seconds.")
        print_separator('#')

if __name__ == "__main__":
    main() 