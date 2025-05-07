#!/usr/bin/env python3
# coding: utf-8

import os
import sys
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import List, Dict, Any, Optional, Union
import pandas as pd

# Add Rust module path
sys.path.append(os.path.join(os.path.dirname(__file__), 'extraction_metrics_rs'))

try:
    import text_cleaner_rs as rust_cleaner
except ImportError:
    print("Error importing text_cleaner_rs Rust module. Building module...")
    try:
        import subprocess
        subprocess.run(
            ["maturin", "develop", "--release"],
            cwd=os.path.join(os.path.dirname(__file__), 'extraction_metrics_rs'),
            check=True
        )
        import text_cleaner_rs as rust_cleaner
        print("Successfully built and imported text_cleaner_rs Rust module.")
    except Exception as e:
        print(f"Failed to build or import the text_cleaner_rs Rust module: {e}")
        print("Make sure maturin is installed: pip install maturin")
        sys.exit(1)


def _process_file_worker(args):
    """Worker function for processing a file in a separate process."""
    file_path, output_dir, scripts_to_keep = args
    
    # Get relative path for output file if output_dir is specified
    output_path = None
    if output_dir:
        rel_path = os.path.basename(file_path)
        output_path = os.path.join(output_dir, rel_path)
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        # Create a new cleaner instance in this process
        cleaner = TextCleaner(scripts_to_keep=scripts_to_keep)
        
        # Process the file
        result = cleaner.process_file(file_path, output_path)
        
        # Add the filename to the result
        result['filename'] = os.path.basename(file_path)
        
        return result
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return {
            'filename': os.path.basename(file_path),
            'error': str(e),
            'badness': 1.0  # Assume maximum badness for error cases
        }


class TextCleaner:
    """Python wrapper for the Rust text cleaning and analysis module."""
    
    def __init__(self, scripts_to_keep: Optional[List[str]] = None):
        """
        Initialize the TextCleaner with scripts to keep.
        
        Args:
            scripts_to_keep: List of script codes to preserve. Default preserves
                         Greek, English, French, punctuation and numbers.
        """
        self.scripts_to_keep = scripts_to_keep or ["gre", "lat", "fra", "punct", "num"]
        self._validate_scripts()
    
    def _validate_scripts(self):
        """Validate that all scripts are available in the Rust module."""
        available_scripts = rust_cleaner.list_available_scripts()
        for script in self.scripts_to_keep:
            if script not in available_scripts:
                raise ValueError(f"Unknown script code: {script}. Available scripts: {available_scripts}")
    
    def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        Analyze text for badness and script percentages.
        
        Args:
            text: The text content to analyze
            
        Returns:
            Dictionary with badness score and other metrics
        """
        return rust_cleaner.analyze_text(text, self.scripts_to_keep)
    
    def clean_text(self, text: str) -> str:
        """
        Clean text by removing problematic content.
        
        Args:
            text: The text content to clean
            
        Returns:
            Cleaned text with <!-- text-missing --> comments where needed
        """
        return rust_cleaner.clean_text(text, self.scripts_to_keep)
    
    def process_file(self, input_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a single file, analyzing and optionally cleaning it.
        
        Args:
            input_path: Path to the input file
            output_path: Optional path where to save the cleaned file
            
        Returns:
            Dictionary with analysis results
        """
        return rust_cleaner.process_file(input_path, output_path, self.scripts_to_keep)
    
    def process_batch(self, 
                     input_files: List[str], 
                     output_dir: Optional[str] = None,
                     num_workers: int = os.cpu_count() or 4) -> pd.DataFrame:
        """
        Process a batch of files in parallel.
        
        Args:
            input_files: List of input file paths
            output_dir: Directory where to save cleaned files
            num_workers: Number of parallel workers
            
        Returns:
            DataFrame with analysis results for all files
        """
        # Prepare arguments for the worker function
        worker_args = [(file_path, output_dir, self.scripts_to_keep) for file_path in input_files]
        
        # Process files in parallel
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            results = list(executor.map(_process_file_worker, worker_args))
        
        # Convert results to DataFrame
        df = pd.DataFrame(results)
        
        # Extract script percentages to separate columns if available
        if 'script_percentages' in df.columns:
            for script_name in self.scripts_to_keep:
                df[f'{script_name}_percentage'] = df['script_percentages'].apply(
                    lambda x: x.get(script_name, 0) if isinstance(x, dict) else 0
                )
            
            # Drop the original script_percentages dictionary column
            df = df.drop(columns=['script_percentages'])
        
        return df


def main():
    parser = argparse.ArgumentParser(description='Text Cleaning and Analysis Tool')
    parser.add_argument('--input', '-i', required=True, help='Input file or directory')
    parser.add_argument('--output', '-o', help='Output directory (for cleaned files)')
    parser.add_argument('--scripts', '-s', nargs='+', default=['gre', 'lat', 'fra', 'punct', 'num', 'sym'],
                        help='Scripts to preserve (default: %(default)s)')
    parser.add_argument('--analyze-only', '-a', action='store_true', help='Only analyze without cleaning')
    parser.add_argument('--csv', '-c', help='CSV file to save analysis results')
    parser.add_argument('--workers', '-w', type=int, default=os.cpu_count() or 4,
                        help='Number of worker processes (default: %(default)s)')
    parser.add_argument('--list-scripts', action='store_true', help='List available script codes and exit')
    
    args = parser.parse_args()
    
    if args.list_scripts:
        try:
            import text_cleaner_rs as rust_cleaner
            print("Available script codes:")
            for script in rust_cleaner.list_available_scripts():
                print(f"  {script}")
            return
        except ImportError:
            print("Error: Unable to import the text_cleaner_rs module.")
            return
    
    # Initialize the cleaner with scripts to keep
    cleaner = TextCleaner(scripts_to_keep=args.scripts)
    
    input_path = Path(args.input)
    
    # Check if input is a directory or a file
    if input_path.is_dir():
        # Find all markdown files in the directory
        input_files = [str(f) for f in input_path.glob('**/*.md')]
        print(f"Found {len(input_files)} markdown files in {input_path}")
        
        # Process batch of files
        output_dir = args.output if not args.analyze_only else None
        results_df = cleaner.process_batch(
            input_files,
            output_dir=output_dir,
            num_workers=args.workers
        )
        
        # Print summary
        total_files = len(results_df)
        bad_files = len(results_df[results_df['badness'] > 0.1])
        print(f"\nAnalysis summary:")
        print(f"Total files: {total_files}")
        print(f"Files with badness > 0.1: {bad_files} ({bad_files/total_files:.2%})")
        print(f"Average badness: {results_df['badness'].mean():.4f}")
        
        if 'gre_percentage' in results_df.columns:
            print(f"Average Greek percentage: {results_df['gre_percentage'].mean():.2f}%")
        
        # Save results to CSV if requested
        if args.csv:
            results_df.to_csv(args.csv, index=False)
            print(f"Results saved to {args.csv}")
    else:
        # Process single file
        output_path = None
        if args.output:
            if os.path.isdir(args.output):
                output_path = os.path.join(args.output, os.path.basename(input_path))
            else:
                output_path = args.output
        
        if args.analyze_only:
            output_path = None
        
        # Process the file
        result = cleaner.process_file(str(input_path), output_path)
        
        # Print results
        print("\nAnalysis results:")
        print(f"Badness score: {result['badness']:.4f}")
        print(f"Bad content count: {result['bad_count']}")
        print(f"Good content count: {result['good_count']}")
        print(f"Glyph tag count: {result['glyph_count']}")
        print(f"Unusual character count: {result['unusual_count']}")
        
        if 'script_percentages' in result:
            print("\nScript percentages:")
            for script, percentage in result['script_percentages'].items():
                print(f"  {script}: {percentage:.2f}%")
        
        if output_path:
            print(f"\nCleaned text saved to: {output_path}")


if __name__ == "__main__":
    main()
