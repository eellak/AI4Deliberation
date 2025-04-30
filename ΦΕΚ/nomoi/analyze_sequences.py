#!/usr/bin/env python3
"""
Script to analyze which markdown files have the most number of sequences.
Outputs a CSV with filename, sequence count, and sequences per line percentage.
"""

import os
import re
import csv
import logging
import pandas as pd
from pathlib import Path
from greek_numerals import GREEK_NUMERALS_ORDINAL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ----- Constants from process_gazettes.py -----
SKIP_PARAM = 5  # Allow skipping of article numbers up to this value
MAX_INDEX_LINE_PERCENT = 0.2  # First 20% of the document may contain index

# Regex to capture article headers
ARTICLE_PATTERN = re.compile(r"^(##\s*|\|\s*)?Άρθρο\s+(.*?)\s*($|\||\s*[-–—]|\.)", re.IGNORECASE)

# ----- Helper functions adapted from process_gazettes.py -----
def find_potential_articles(filepath):
    """Finds all potential article lines in a file, parsing only the number part."""
    articles = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        logging.error(f"Error reading {filepath}: {e}")
        return [], 0
    
    # Sort GREEK_NUMERALS_ORDINAL keys by length descending to match longer phrases first
    sorted_greek_numerals = sorted(GREEK_NUMERALS_ORDINAL.keys(), key=len, reverse=True)
    
    for i, line in enumerate(lines):
        match = ARTICLE_PATTERN.match(line)
        if match:
            full_line_text = line.strip()  # Store the full original line
            content_after_arthro = match.group(2).strip()
            num_val = None
            num_type = None
            
            # 1. Check for Arabic numerals at the beginning
            digit_match = re.match(r"^(\d+)(?:\s|$|\.|\,|\-|\'|\|)", content_after_arthro)
            if digit_match:
                parsed_num_str = digit_match.group(1)
                num_val = int(parsed_num_str)
                num_type = 'arabic'
            else:
                # 2. Check for Greek word numerals at the beginning
                content_lower = content_after_arthro.lower()
                for greek_word in sorted_greek_numerals:
                    # Check if it starts with the greek word exactly or followed by delimiter
                    if content_lower.startswith(greek_word):
                        # Ensure it's a whole word match
                        next_char_pos = len(greek_word)
                        if next_char_pos >= len(content_lower) or \
                           content_lower[next_char_pos].isspace() or \
                           content_lower[next_char_pos] in '.,;:|()-':
                           parsed_num_str = content_after_arthro[:len(greek_word)]
                           num_val = GREEK_NUMERALS_ORDINAL[greek_word]
                           num_type = 'greek_word'
                           break  # Found the longest match
            
            # If a number was successfully parsed from the beginning
            if num_val is not None:
                articles.append({
                    'line_num': i,
                    'text': full_line_text,
                    'number': num_val,
                    'type': num_type,
                    'used_in_sequence': False,
                    'is_index': False
                })
    
    return articles, len(lines)

def find_sequences(articles):
    """Find continuous sequences of articles.
    
    A sequence is broken only when:
    1. The numeral type changes (arabic vs greek_word)
    2. The article numbers are not in ascending order (with skips allowed)
    """
    sequences = []
    current_sequence = []
    current_type = None
    
    # Sort articles by line number to process them in order
    sorted_articles = sorted(articles, key=lambda x: x['line_num'])
    
    for article in sorted_articles:
        num = article['number']
        num_type = article['type']
        
        # If there's no current sequence, start a new one
        if not current_sequence:
            current_sequence = [article]
            current_type = num_type
            article['used_in_sequence'] = True
            continue
        
        # Get the last article in the current sequence
        last_article = current_sequence[-1]
        last_num = last_article['number']
        
        # Check if this article can continue the current sequence:
        # 1. Same numeral type
        # 2. Number is greater than the last one
        # 3. Number is not too far ahead (limited by SKIP_PARAM)
        can_continue = (current_sequence and 
                       num_type == current_type and 
                       num > last_num and 
                       num <= last_num + 1 + SKIP_PARAM)
        
        if can_continue:
            current_sequence.append(article)
            article['used_in_sequence'] = True
        else:
            # Can't continue this sequence, save it and start a new one
            if len(current_sequence) > 0:
                sequences.append(current_sequence)
            
            current_sequence = [article]
            current_type = num_type
            article['used_in_sequence'] = True
    
    # Don't forget to add the last sequence if it exists
    if current_sequence:
        sequences.append(current_sequence)
    
    return sequences

def analyze_file_sequences(filepath):
    """Analyze a single file for article sequences and return the count."""
    try:
        # Get filename without full path
        filename = os.path.basename(filepath)
        
        # Find potential articles
        articles, line_count = find_potential_articles(filepath)
        
        # Find sequences among these articles
        sequences = find_sequences(articles)
        
        # Count of sequences
        sequence_count = len(sequences)
        
        # Calculate percentage: (sequence_count / line_count) * 100
        percentage = 0
        if line_count > 0:
            percentage = (sequence_count / line_count) * 100
        
        return {
            'filename': filename,
            'sequence_count': sequence_count,
            'total_lines': line_count,
            'percentage': percentage
        }
    except Exception as e:
        logging.error(f"Error analyzing {filepath}: {e}")
        return {
            'filename': os.path.basename(filepath),
            'sequence_count': 0,
            'total_lines': 0,
            'percentage': 0
        }

def main():
    # Path to markdown files
    markdown_dir = "/mnt/data/gazette_processing/markdown"
    # Output CSV file
    output_csv = "/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/sequence_analysis.csv"
    
    logging.info(f"Analyzing sequences in markdown files from {markdown_dir}...")
    
    # Get all markdown files
    markdown_files = list(Path(markdown_dir).glob('*.md'))
    total_files = len(markdown_files)
    logging.info(f"Found {total_files} markdown files to analyze")
    
    # Analyze each file
    results = []
    for i, filepath in enumerate(markdown_files):
        if i % 100 == 0:
            logging.info(f"Processed {i}/{total_files} files...")
        
        file_result = analyze_file_sequences(str(filepath))
        results.append(file_result)
    
    # Sort results by sequence_count in descending order
    results = sorted(results, key=lambda x: x['sequence_count'], reverse=True)
    
    # Write results to CSV
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'sequence_count', 'percentage'])
        
        for result in results:
            writer.writerow([
                result['filename'],
                result['sequence_count'],
                f"{result['percentage']:.4f}"
            ])
    
    logging.info(f"Results written to {output_csv}")
    
    # Show top 10 files with most sequences
    logging.info("Top 10 files with most sequences:")
    for i, result in enumerate(results[:10]):
        logging.info(f"{i+1}. {result['filename']}: {result['sequence_count']} sequences ({result['percentage']:.4f}%)")

if __name__ == "__main__":
    main()
