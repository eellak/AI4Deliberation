#!/usr/bin/env python
# coding: utf-8

import os
import re
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from collections import defaultdict
import logging
import sys

# Add script's directory to path to find greek_numerals if needed,
# though standard import should work if both files are in the same directory.
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

# Import the dictionary from the separate file
try:
    from greek_numerals import GREEK_NUMERALS_ORDINAL
except ImportError:
    logging.error("Could not import GREEK_NUMERALS_ORDINAL from greek_numerals.py. Make sure it's in the same directory.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration (Using Absolute Paths) ---
MARKDOWN_DIR = '/mnt/data/gazette_processing/markdown' # Source directory
OUTPUT_DIR = '/mnt/data/AI4Deliberation/ΦΕΚ/nomoi' # Target directory for outputs
OUTPUT_PARQUET = os.path.join(OUTPUT_DIR, 'articles.parquet')
DEBUG_CSV = os.path.join(OUTPUT_DIR, 'unused_articles_debug.csv')

SKIP_PARAM = 1 # Max allowed gap in article numbers for a sequence
START_FROM = 1 # Minimum article number to start a sequence
AT_LEAST = 2   # Minimum number of articles to form a valid sequence
INDEX_MAX_LINES_PERCENT = 0.20 # Check first 20% lines for index
INDEX_MIN_EMPTY_LINES_PERCENT = 0.30 # >30% empty lines between index headers (DEPRECATED by avg line count)
INDEX_MAX_AVG_NON_EMPTY_LINES = 2.5 # New criteria for index detection

# Regex to capture article headers and the text following 'Άρθρο '
# This matches both markdown (## Άρθρο) and plain text (Άρθρο) formats, as well as table formats
ARTICLE_PATTERN = re.compile(r"^(##\s*|\|\s*)?Άρθρο\s+(.*?)\s*($|\||\s*[-–—]|\.)", re.IGNORECASE)

# --- Helper Functions ---

def parse_article_number(num_str):
    """DEPRECATED in favor of inline parsing in find_potential_articles.
    Parses Arabic or Greek word numerals using the imported dictionary."""
    # This function is no longer the primary parsing mechanism for article headers
    # but might be kept for other potential uses or removed later.
    num_str_lower = num_str.strip().lower()
    if num_str_lower.isdigit():
        return int(num_str_lower), 'arabic'
    elif num_str_lower in GREEK_NUMERALS_ORDINAL:
        return GREEK_NUMERALS_ORDINAL[num_str_lower], 'greek_word'
    else:
        parts = num_str_lower.split()
        reconstructed = " ".join(parts)
        if reconstructed in GREEK_NUMERALS_ORDINAL:
             return GREEK_NUMERALS_ORDINAL[reconstructed], 'greek_word'
        return None, None

def is_mostly_empty(lines):
    """DEPRECATED: Replaced by average non-empty line count for index detection.
    Checks if more than a threshold percentage of lines are empty/whitespace."""
    if not lines: return True
    empty_count = sum(1 for line in lines if not line.strip())
    # Original logic: return (empty_count / len(lines)) > INDEX_MIN_EMPTY_LINES_PERCENT
    return False # Keep function signature but make it ineffective

def count_non_empty_lines(lines):
    """Counts non-empty lines."""
    return sum(1 for line in lines if line.strip())

# --- Core Logic Functions ---

def find_potential_articles(filepath):
    """Finds all potential article lines in a file, parsing only the number part.
    
    This function has been enhanced to handle various article formats including:
    - Markdown headers: ## Άρθρο 123
    - Plain text: Άρθρο 123
    - Table cells: | Άρθρο 123 | Title...
    
    The function normalizes these different formats to ensure that only
    the article numeral type (arabic vs greek_word) and numbering are used
    to determine sequences, not formatting differences.
    """
    articles = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        logging.error(f"Error reading {filepath}: {e}")
        return [], []

    # Sort GREEK_NUMERALS_ORDINAL keys by length descending to match longer phrases first
    sorted_greek_numerals = sorted(GREEK_NUMERALS_ORDINAL.keys(), key=len, reverse=True)

    for i, line in enumerate(lines):
        match = ARTICLE_PATTERN.match(line)
        if match:
            full_line_text = line.strip() # Store the full original line
            content_after_arthro = match.group(2).strip()
            num_val = None
            num_type = None
            parsed_num_str = None # The part identified as the number

            # 1. Check for Arabic numerals at the beginning
            # This regex is more robust to handle numbers that might be followed by
            # various punctuation or whitespace
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
                        # Ensure it's a whole word match (followed by whitespace or end of string or punctuation)
                        next_char_pos = len(greek_word)
                        if next_char_pos >= len(content_lower) or \
                           content_lower[next_char_pos].isspace() or \
                           content_lower[next_char_pos] in '.,;:|()-':
                           parsed_num_str = content_after_arthro[:len(greek_word)] # Get the original case substring
                           num_val = GREEK_NUMERALS_ORDINAL[greek_word]
                           num_type = 'greek_word'
                           break # Found the longest match

            # If a number was successfully parsed from the beginning
            if num_val is not None:
                articles.append({
                    'line_num': i,
                    'text': full_line_text, # Use the full line as the title text
                    'number': num_val,
                    'type': num_type,  # This is the ONLY thing that should affect sequence splitting
                    'used_in_sequence': False,
                    'is_index': False
                })
            else:
                 # Log warning only if parsing failed, not if it wasn't an article line
                 logging.warning(f"Could not parse number at start of: '{content_after_arthro}' in {os.path.basename(filepath)} line {i+1}")

    return articles, lines

def detect_index(potential_articles, lines, filename):
    """Detects all sequences that qualify as indices in the first 20% of the document.
    A sequence qualifies as an index if it has low content density (avg non-empty lines < 2.5).
    """
    file_length = len(lines)
    max_line_for_index = int(file_length * INDEX_MAX_LINES_PERCENT)
    logging.info(f"File {filename}: {file_length} lines, max index line: {max_line_for_index}")
    
    # First, identify all valid sequences in the document
    all_sequences = []
    
    # Group articles by type
    arabic_articles = [a for a in potential_articles if a['type'] == 'arabic']
    greek_articles = [a for a in potential_articles if a['type'] == 'greek_word']
    
    # Find all valid sequences for each type
    for article_type, articles in [('arabic', arabic_articles), ('greek_word', greek_articles)]:
        if len(articles) < AT_LEAST:
            continue
            
        # Sort by line number
        sorted_articles = sorted(articles, key=lambda x: x['line_num'])
        
        # Find all valid sequences with proper numbering
        current_sequence = [sorted_articles[0]]
        last_num = sorted_articles[0]['number']
        
        for article in sorted_articles[1:]:
            num = article['number']
            if num > last_num and num <= last_num + 1 + SKIP_PARAM:
                # Continue the sequence
                current_sequence.append(article)
                last_num = num
            else:
                # End the current sequence if it's valid
                if len(current_sequence) >= AT_LEAST:
                    all_sequences.append({
                        'type': article_type,
                        'articles': current_sequence,
                        'start_line': current_sequence[0]['line_num'],
                        'end_line': current_sequence[-1]['line_num'],
                        'start_num': current_sequence[0]['number'],
                        'end_num': current_sequence[-1]['number']
                    })
                # Start a new sequence
                current_sequence = [article]
                last_num = num
        
        # Add the last sequence if valid
        if len(current_sequence) >= AT_LEAST:
            all_sequences.append({
                'type': article_type,
                'articles': current_sequence,
                'start_line': current_sequence[0]['line_num'],
                'end_line': current_sequence[-1]['line_num'],
                'start_num': current_sequence[0]['number'],
                'end_num': current_sequence[-1]['number']
            })
    
    # Filter for sequences that end before the 20% mark
    early_sequences = [seq for seq in all_sequences if seq['end_line'] <= max_line_for_index]
    logging.info(f"Found {len(early_sequences)} sequences ending before line {max_line_for_index}")
    
    # Check each sequence to see if it qualifies as an index
    index_sequences = []
    
    for seq in early_sequences:
        # Calculate average non-empty lines between articles
        total_non_empty = 0
        sections = 0
        articles = seq['articles']
        
        for i in range(1, len(articles)):
            prev_article = articles[i-1]
            curr_article = articles[i]
            content_lines = lines[prev_article['line_num']+1:curr_article['line_num']]
            non_empty_count = count_non_empty_lines(content_lines)
            total_non_empty += non_empty_count
            sections += 1
            
        avg_non_empty = total_non_empty / sections if sections > 0 else float('inf')
        
        # If average non-empty lines is below threshold, this is an index
        if avg_non_empty < INDEX_MAX_AVG_NON_EMPTY_LINES:
            seq['avg_non_empty'] = avg_non_empty
            index_sequences.append(seq)
            logging.info(f"Index sequence: {seq['type']} from line {seq['start_line']+1} to {seq['end_line']+1}")
            logging.info(f"  Articles {seq['start_num']}-{seq['end_num']}, avg non-empty: {avg_non_empty:.2f}")
    
    # Mark all articles in index sequences
    index_lines = set()
    for seq in index_sequences:
        for article in seq['articles']:
            index_lines.add(article['line_num'])
            article['is_index'] = True
    
    # Log summary
    if index_lines:
        min_line = min(index_lines) + 1 if index_lines else 0
        max_line = max(index_lines) + 1 if index_lines else 0
        logging.info(f"Total index: {len(index_lines)} articles from lines {min_line}-{max_line}")
    else:
        logging.info("No index sequences detected")
            
    return index_lines

def find_sequences(potential_articles, filename):
    """Find valid sequences of articles based on the rules.
    Sequences should be consistent in type (arabic or greek word) and in ascending order.
    A new sequence starts when:
    1. Article numeral type changes (arabic vs greek_word), OR
    2. Article numbers are not in strictly ascending order (allowing for SKIP_PARAM gaps)
    
    NOTE: Formatting differences in article titles (like ## prefix or suffix text) should NOT break sequences.
    """
    
    # First filter out index articles
    article_candidates = [a for a in potential_articles if not a['is_index']]
    if not article_candidates:
        return {}
        
    # Sort by line number to process in document order
    sorted_articles = sorted(article_candidates, key=lambda x: x['line_num'])
    
    sequences = []
    current_sequence = []
    last_num = -1
    current_type = None
    sequence_char_code = ord('A')  # Start sequence IDs from 'A'
    
    for article in sorted_articles:
        num = article['number']
        num_type = article['type']
        
        # Check if this article can continue the current sequence
        # ONLY consider the number type and ordering - nothing else should break a sequence
        can_continue = (current_sequence and 
                      num_type == current_type and 
                      num > last_num and 
                      num <= last_num + 1 + SKIP_PARAM)
        
        if can_continue:
            current_sequence.append(article)
            last_num = num
        else:
            # Finish the previous sequence if it was valid
            if len(current_sequence) >= AT_LEAST:
                seq_id = chr(sequence_char_code)
                for item in current_sequence:
                    item['sequence_id'] = seq_id
                    item['used_in_sequence'] = True
                sequences.append(current_sequence)
                sequence_char_code += 1
            
            # Start a new potential sequence if the number is valid
            if num >= START_FROM:
                current_sequence = [article]
                last_num = num
                current_type = num_type
            else:
                current_sequence = []
                last_num = -1
                current_type = None
    
    # Handle the last sequence
    if len(current_sequence) >= AT_LEAST:
        seq_id = chr(sequence_char_code)
        for item in current_sequence:
            item['sequence_id'] = seq_id
            item['used_in_sequence'] = True
        sequences.append(current_sequence)
    
    # Log sequence information
    if sequences:
        logging.info(f"Found {len(sequences)} valid article sequences in {filename}")
        for i, seq in enumerate(sequences):
            logging.info(f"Sequence {i+1}: {len(seq)} articles, numbers {seq[0]['number']}-{seq[-1]['number']}, type: {seq[0]['type']}")
    
    # Convert to dictionary keyed by line_num for easy access
    articles_in_sequences = {}
    for seq in sequences:
        for article in seq:
            articles_in_sequences[article['line_num']] = article
    
    return articles_in_sequences

def segment_content(filepath, lines, articles_in_sequences, index_lines):
    """Segments the file content into Introduction and valid articles."""
    segments = []
    filename = os.path.basename(filepath)
    
    # Check if we have detected index lines for this file
    if index_lines:
        # Get all potential articles from the file to find index articles
        potential_articles, _ = find_potential_articles(filepath)
        
        # Find the articles marked as index
        index_articles = sorted([a for a in potential_articles if a['line_num'] in index_lines], 
                              key=lambda x: x['line_num'])
        
        if index_articles:
            # Extract index content (from first to last index article, inclusive)
            first_idx = index_articles[0]['line_num']
            last_idx = index_articles[-1]['line_num']
            
            # Extract the entire index section including the headers
            index_content = ''.join(lines[first_idx:last_idx+1])
            
            # If there's a title/header before the first index article,
            # try to capture it (like "## ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ")
            index_title = "Index"
            for i in range(max(0, first_idx-5), first_idx):
                if i >= 0 and "ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ" in lines[i]:
                    index_title = lines[i].strip()
                    # Include this title line in the content as well
                    index_content = lines[i] + index_content
                    break
            
            # Add index as a special segment
            segments.append({
                'filename': filename,
                'title': index_title,
                'content': index_content,
                'article_num': None,
                'sequence': 'INDEX'
            })
    
    # Process all valid articles in sequences
    sorted_line_nums = sorted(set(articles_in_sequences.keys()))
    
    # Add introduction segment if there's content before the first article
    # and after any index section
    if sorted_line_nums:
        # Determine the start of the introduction
        intro_start = 0
        
        # If we have an index, start after it
        if index_lines:
            # Start after the last index line
            intro_start = max(index_lines) + 1 if index_lines else 0
        
        # Only create intro if there's actual content between intro_start and first article
        if sorted_line_nums[0] > intro_start:
            intro_content = ''.join(lines[intro_start:sorted_line_nums[0]])
            if intro_content.strip():  # If there's actual content
                segments.append({
                    'filename': filename,
                    'title': 'Introduction',
                    'content': intro_content,
                    'article_num': None,
                    'sequence': None
                })
    
    # Process each article in sequence
    for i, line_num in enumerate(sorted_line_nums):
        article_data = articles_in_sequences[line_num]
        title = article_data['text']
        article_num = article_data['number']
        sequence_id = article_data.get('sequence_id', '')
        
        # Determine content: from current article to the next, or to the end of file
        content_start = line_num + 1  # Skip the article header line
        content_end = sorted_line_nums[i+1] if i < len(sorted_line_nums) - 1 else len(lines)
        content = ''.join(lines[content_start:content_end])
        
        segments.append({
            'filename': filename,
            'title': title,
            'content': content,
            'article_num': article_num,
            'sequence': sequence_id
        })
    
    return segments

# --- Main Execution ---

def main():
    all_segments = []
    unused_articles_report = []
    total_potential_articles = 0
    total_used_in_sequence = 0
    total_index_articles = 0

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.isdir(MARKDOWN_DIR):
        logging.error(f"Markdown directory not found: {MARKDOWN_DIR}")
        sys.exit(1)

    markdown_files = [os.path.join(MARKDOWN_DIR, f) for f in os.listdir(MARKDOWN_DIR) if f.endswith('.md')]

    if not markdown_files:
        logging.warning(f"No markdown files found in {MARKDOWN_DIR}")
    else:
        logging.info(f"Processing {len(markdown_files)} markdown files...")

    for filepath in markdown_files:
        filename = os.path.basename(filepath)
        logging.info(f"Processing {filename}...")

        potential_articles, lines = find_potential_articles(filepath)
        if not lines:
            continue

        for article_candidate in potential_articles: article_candidate['filename'] = filename
        total_potential_articles += len(potential_articles)

        index_lines = detect_index(potential_articles, lines, filename)
        total_index_articles += len(index_lines)

        non_index_articles = [a for a in potential_articles if not a['is_index']]

        articles_in_sequences = find_sequences(non_index_articles, filename)
        total_used_in_sequence += len(articles_in_sequences)

        file_segments = segment_content(filepath, lines, articles_in_sequences, index_lines)
        all_segments.extend(file_segments)

        for article in potential_articles:
            if not article['is_index'] and not article['used_in_sequence']:
                unused_articles_report.append({
                    'filename': filename,
                    'line_number': article['line_num'] + 1,
                    'matched_text': article['text']
                })

    # --- Output Results ---
    if all_segments:
        logging.info(f"Saving {len(all_segments)} segments to {OUTPUT_PARQUET}...")
        df = pd.DataFrame(all_segments)
        schema = pa.schema([
            pa.field('filename', pa.string()),
            pa.field('title', pa.string()),
            pa.field('content', pa.string()),
            pa.field('article_num', pa.int64()), # Ensure article_num is int64 (nullable)
            pa.field('sequence', pa.string())
        ])
        try:
            table = pa.Table.from_pandas(df, schema=schema)
            pq.write_table(table, OUTPUT_PARQUET)
            logging.info("Parquet file saved successfully.")
        except Exception as e:
            logging.error(f"Error writing Parquet file: {e}")
    else:
        logging.warning("No segments were generated.")

    # --- Output Debug Report ---
    total_unused = len(unused_articles_report)
    if unused_articles_report:
        logging.info(f"Saving {total_unused} unused article patterns to {DEBUG_CSV}...")
        df_debug = pd.DataFrame(unused_articles_report)
        try:
            df_debug.to_csv(DEBUG_CSV, index=False, encoding='utf-8')
            logging.info("Debug CSV file saved successfully.")
        except Exception as e:
            logging.error(f"Error writing debug CSV file: {e}")
    else:
        logging.info("No unused article patterns found.")

    # --- Print Summary ---
    print("\n--- Processing Summary ---")
    print(f"Total potential 'Άρθρο' patterns found: {total_potential_articles}")
    print(f"Patterns identified as part of an index: {total_index_articles}")
    print(f"Patterns used in valid article sequences: {total_used_in_sequence}")
    unused_non_index = total_potential_articles - total_index_articles - total_used_in_sequence
    print(f"Unused patterns (not index, not in sequence): {unused_non_index}")

    if total_potential_articles > 0:
        total_candidates_for_sequences = total_potential_articles - total_index_articles
        if total_candidates_for_sequences > 0:
            percent_unused = (unused_non_index / total_candidates_for_sequences) * 100
            print(f"Percentage of non-index patterns unused: {percent_unused:.2f}%")
        else:
            print("Percentage of non-index patterns unused: N/A (no non-index patterns found)")
    else:
        print("Percentage of non-index patterns unused: N/A (no patterns found)")

    print("-------------------------")

if __name__ == "__main__":
    main()
