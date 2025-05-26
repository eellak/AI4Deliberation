#!/usr/bin/env python3
"""
Script to connect to the SQLite database, read article contents,
and detect if a single 'content' entry contains multiple articles
defined sequentially (e.g., "Άρθρο 1", "Άρθρο 2", ...).
"""

import sqlite3
import re
import logging
import csv
import os
import sys # Added for csv.field_size_limit

# Import the new utility function and the existing parser for detailed inspection if needed
from article_parser_utils import check_overall_article_sequence_integrity, parse_article_header, calculate_average_word_count_of_true_articles # Added calculate_average_word_count_of_true_articles
# Removed extract_article_sequences and check_article_number_sequence_continuity as their logic is now encapsulated or replaced

# --- Configuration ---
DB_PATH = "/mnt/data/AI4Deliberation/new_html_extraction/deliberation_data_gr_markdownify.db"
TABLE_NAME = "articles"
CONTENT_COLUMN_NAME = "content"
ID_COLUMN_NAME = "id"  # Primary key of the articles table
CONSULTATION_ID_COLUMN_NAME = "consultation_id"

# Regex to capture "Άρθρο <number>" at the start of a line
# It captures the number. Allows for optional whitespace after "Άρθρο".
# It expects the number to be followed by a space, a dot, or end of line.
# ARTICLE_LINE_PATTERN = re.compile(r"^\\s*Άρθρο\\s*(\\d+)(?:[\\s.]|$)", re.IGNORECASE) # REMOVED

# Output CSV file name
OUTPUT_CSV_FILE = "crammed_articles_integrity_report_enhanced_v3.csv" # Changed output filename for v3

# --- !!! DEBUGGING SWITCH !!! ---
# Set this to an article DB ID (int or list of ints) to inspect its content and sequence integrity.
# If not None, the script will ONLY fetch and print this article's content and analysis, then exit.
ARTICLE_ID_TO_INSPECT = None # Set to None for a full run
# --- !!! END DEBUGGING SWITCH !!! ---

# Configure logging
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

# Increase CSV field size limit for potentially large content fields
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    # Handle cases where sys.maxsize is too large for the system's C long type
    csv.field_size_limit(int(csv.field_size_limit() * 0.9)) # Or some other large reasonable number
    logging.warning(f"sys.maxsize too large for csv.field_size_limit. Set to {csv.field_size_limit()}")

def fetch_consultation_details(conn, consultation_id):
    """Fetches title and URL for a given consultation_id from the 'consultations' table."""
    # Assuming consultations table has columns: id (matches consultation_id), title, url
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title, url FROM consultations WHERE id = ?", (consultation_id,))
        row = cursor.fetchone()
        if row:
            return {"title": row[0], "url": row[1]}
        else:
            logging.warning(f"Consultation details not found for consultation_id: {consultation_id}")
            return {"title": "N/A", "url": "N/A"}
    except sqlite3.Error as e:
        logging.error(f"Database error fetching consultation details for {consultation_id}: {e}")
        return {"title": "Error fetching", "url": "Error fetching"}

def main():
    if ARTICLE_ID_TO_INSPECT is not None:
        logging.info(f"--- INSPECTION MODE: Analyzing Article DB ID(s): {ARTICLE_ID_TO_INSPECT} ---")
        conn_inspect = None
        try:
            conn_inspect = sqlite3.connect(DB_PATH)
            cursor_inspect = conn_inspect.cursor()
            
            ids_to_inspect = []
            if isinstance(ARTICLE_ID_TO_INSPECT, list):
                ids_to_inspect = ARTICLE_ID_TO_INSPECT
            elif isinstance(ARTICLE_ID_TO_INSPECT, int):
                ids_to_inspect = [ARTICLE_ID_TO_INSPECT]
            else:
                logging.error(f"ARTICLE_ID_TO_INSPECT must be an int or a list of ints. Found: {type(ARTICLE_ID_TO_INSPECT)}")
                return

            for article_id in ids_to_inspect:
                logging.info(f"--- Analyzing content for Article DB ID: {article_id} ---")
                query_inspect = (f"SELECT {CONTENT_COLUMN_NAME}, {CONSULTATION_ID_COLUMN_NAME} "
                               f"FROM {TABLE_NAME} WHERE {ID_COLUMN_NAME} = ?")
                cursor_inspect.execute(query_inspect, (article_id,))
                row_inspect = cursor_inspect.fetchone()
                if row_inspect:
                    content_to_inspect = row_inspect[0]
                    consult_id_inspect = row_inspect[1]
                    
                    print(f"--- START CONTENT FOR ARTICLE_DB_ID: {article_id} (Consultation ID: {consult_id_inspect}) ---")
                    print(content_to_inspect)
                    print(f"--- END CONTENT FOR ARTICLE_DB_ID: {article_id} ---")
                    
                    integrity_result = check_overall_article_sequence_integrity(content_to_inspect)
                    avg_wc = calculate_average_word_count_of_true_articles(content_to_inspect)
                    
                    logging.info(f"Integrity Check Result for DB ID {article_id}:")
                    logging.info(f"  Forms single continuous sequence: {integrity_result['forms_single_continuous_sequence']}")
                    logging.info(f"  Count of detected articles: {integrity_result['count_of_detected_articles']}")
                    logging.info(f"  Average word count of true articles: {avg_wc:.2f}") # Added avg word count
                    if integrity_result['detected_articles_details']:
                        logging.info("  Detected articles details:")
                        for art_detail in integrity_result['detected_articles_details']:
                            logging.info(f"    - Number: {art_detail['number']}, Line Idx: {art_detail['line_index']}, Text: \\\"{art_detail['raw_line']}\\\"")
                    else:
                        logging.info("  No article headers detected.")
                else:
                    logging.warning(f"Article DB ID {article_id} not found for inspection.")
        except sqlite3.Error as e:
            logging.error(f"Database error during inspection: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred during inspection: {e}", exc_info=True)
        finally:
            if conn_inspect:
                conn_inspect.close()
        return # Exit after inspection

    # --- Full run ---
    logging.info(f"Starting full analysis for article sequence integrity. Output CSV will be: {OUTPUT_CSV_FILE}")
    report_data = []
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        query = (f"SELECT {ID_COLUMN_NAME}, {CONSULTATION_ID_COLUMN_NAME}, {CONTENT_COLUMN_NAME} "
                 f"FROM {TABLE_NAME} "
                 f"WHERE {CONTENT_COLUMN_NAME} IS NOT NULL AND {CONTENT_COLUMN_NAME} != ''")
        
        logging.info(f"Executing query: {query}")
        cursor.execute(query)
        
        articles_processed = 0
        relevant_entries_found = 0 # Entries with >1 detected articles
        
        for row in cursor:
            articles_processed += 1
            article_db_id = row[0]
            consultation_id = row[1]
            content = row[2]
            
            integrity_result = check_overall_article_sequence_integrity(content)
            count_detected = integrity_result['count_of_detected_articles']
            
            # We are interested in entries that *could* have cramming issues, 
            # meaning they have more than one article declaration.
            if count_detected > 1:
                relevant_entries_found += 1
                consultation_info = fetch_consultation_details(conn, consultation_id)
                avg_word_count = calculate_average_word_count_of_true_articles(content) # Calculate average word count
                
                detected_numbers = [str(art['number']) for art in integrity_result['detected_articles_details']]
                detected_titles = [art['raw_line'] for art in integrity_result['detected_articles_details']]

                report_data.append({
                    'consultation_id': consultation_id,
                    'consultation_title': consultation_info['title'],
                    'consultation_url': consultation_info['url'],
                    'article_db_id': article_db_id,
                    'count_of_detected_articles': count_detected,
                    'avg_word_count_true_articles': f"{avg_word_count:.2f}", # Added new field
                    'detected_article_numbers_list': ",".join(detected_numbers),
                    'detected_article_titles_list': "; ".join(detected_titles),
                    'forms_single_continuous_sequence': integrity_result['forms_single_continuous_sequence'],
                    'db_entry_content': content # Added new field
                })

                # Optional: Log if the sequence is NOT continuous for immediate feedback
                if not integrity_result['forms_single_continuous_sequence']:
                    logging.warning(
                        f"DB ID {article_db_id} (Consultation: {consultation_id}) has {count_detected} articles "
                        f"that DO NOT form a single continuous sequence. Numbers: {','.join(detected_numbers)}"
                    )
            
            if articles_processed % 1000 == 0:
                logging.info(f"Processed {articles_processed} articles...")

        logging.info(f"Finished processing {articles_processed} articles.")
        logging.info(f"Found {relevant_entries_found} DB entries containing more than one detected article header.")

        output_file_path = os.path.join(os.path.dirname(__file__) or '.', OUTPUT_CSV_FILE)
        if report_data:
            logging.info(f"Writing {len(report_data)} relevant entries to {output_file_path}")
            fieldnames = ['consultation_id', 'consultation_title', 'consultation_url', 
                          'article_db_id', 'count_of_detected_articles', 
                          'avg_word_count_true_articles', # Added new fieldname
                          'detected_article_numbers_list', 'detected_article_titles_list',
                          'forms_single_continuous_sequence',
                          'db_entry_content'] # Added new fieldname
            with open(output_file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(report_data) # Use writerows for list of dicts
            logging.info(f"CSV report successfully written to {output_file_path}.")
        else:
            logging.info("No relevant entries (with >1 detected articles) found to write to CSV.")

    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")

if __name__ == "__main__":
    main() 