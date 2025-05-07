#!/usr/bin/env python3
# coding: utf-8

"""
Test script for the text_cleaner module.
This script processes the specified input directory, cleaning all markdown files
and saving the results to the output directory.
"""

import os
import sys
from pathlib import Path
import pandas as pd
from text_cleaner import TextCleaner

def main():
    # Define paths
    input_dir = "/mnt/data/gazette_processing/markdown"
    output_dir = "/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/check_badness/extraction_metrics_rs/cleaned_markdown"
    results_csv = "/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/check_badness/extraction_metrics_rs/analysis_results.csv"
    
    # Make sure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize cleaner with scripts to keep (Greek, Latin, French, punctuation, numbers, symbols)
    cleaner = TextCleaner(scripts_to_keep=["gre", "lat", "fra", "punct", "num", "sym"])
    
    print(f"Processing files from: {input_dir}")
    print(f"Saving cleaned files to: {output_dir}")
    
    # Find all markdown files in the input directory
    input_files = list(Path(input_dir).glob('**/*.md'))
    print(f"Found {len(input_files)} markdown files to process")
    
    # Process files in parallel, with cleaning
    results_df = cleaner.process_batch(
        [str(f) for f in input_files],
        output_dir=output_dir,
        num_workers=os.cpu_count() or 4
    )
    
    # Save results to CSV
    results_df.to_csv(results_csv, index=False)
    
    # Print summary statistics
    print("\nAnalysis Results:")
    print(f"Total files processed: {len(results_df)}")
    
    # Calculate statistics on badness
    bad_threshold = 0.1  # 10% bad content
    very_bad_threshold = 0.3  # 30% bad content
    
    bad_files = results_df[results_df['badness'] > bad_threshold]
    very_bad_files = results_df[results_df['badness'] > very_bad_threshold]
    
    print(f"Files with badness > {bad_threshold}: {len(bad_files)} ({len(bad_files)/len(results_df):.2%})")
    print(f"Files with badness > {very_bad_threshold}: {len(very_bad_files)} ({len(very_bad_files)/len(results_df):.2%})")
    print(f"Average badness: {results_df['badness'].mean():.4f}")
    
    # Script percentages
    if 'gre_percentage' in results_df.columns:
        print(f"Average Greek percentage: {results_df['gre_percentage'].mean():.2f}%")
    if 'lat_percentage' in results_df.columns:
        print(f"Average Latin percentage: {results_df['lat_percentage'].mean():.2f}%")
    
    # List worst files
    print("\nTop 10 worst files by badness:")
    worst_files = results_df.sort_values('badness', ascending=False).head(10)
    for _, row in worst_files.iterrows():
        print(f"  {row['filename']}: {row['badness']:.4f} badness")
    
    print(f"\nResults saved to: {results_csv}")

if __name__ == "__main__":
    main()
