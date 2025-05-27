import os
import sys
import logging
import sqlite3
import torch
from transformers import AutoProcessor, Gemma3ForConditionalGeneration
import argparse # Added for command-line arguments
import datetime # Added for timestamped log files
import csv # Added for CSV output in dry run
import json # Added for json.dumps

# --- Environment Setup ---
os.environ['TORCHDYNAMO_DISABLE'] = '1'

# --- Logger Setup for Stage 1 Reasoning Trace ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Generate a timestamp string for the log file
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE_NAME = f"stage1_reasoning_trace_{TIMESTAMP}.log"
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, LOG_FILE_NAME)

stage1_logger = logging.getLogger("Stage1ReasoningTrace")
stage1_logger.setLevel(logging.DEBUG)
stage1_logger.propagate = False # Prevent duplicate messages to root logger

if not stage1_logger.hasHandlers(): # Add handler only if it doesn't exist
    trace_file_handler = logging.FileHandler(LOG_FILE_PATH, mode='w') # 'w' is fine for unique filenames
    # General formatter for most logs
    general_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    trace_file_handler.setFormatter(general_formatter)
    stage1_logger.addHandler(trace_file_handler)
    stage1_logger.info(f"Stage 1 Reasoning Trace logger initialized. Log file: {LOG_FILE_PATH}")

stage1_logger.info(f"TORCHDYNAMO_DISABLE set to: {os.environ.get('TORCHDYNAMO_DISABLE')}")

# --- Import article_parser_utils ---
# Construct the absolute path to the directory containing article_parser_utils.py
# The orchestrator script is in /mnt/data/AI4Deliberation/gemma_summarization_task/
# The utils script is in /mnt/data/AI4Deliberation/new_html_extraction/article_extraction_analysis/

current_script_dir = os.path.dirname(os.path.abspath(__file__))
# Path to the root of the AI4Deliberation project, assuming orchestrator is one level down
project_root = os.path.abspath(os.path.join(current_script_dir, '..')) 
# Path to the directory containing the utility script
utils_module_dir = os.path.join(project_root, 'new_html_extraction', 'article_extraction_analysis')

if utils_module_dir not in sys.path:
    sys.path.insert(0, utils_module_dir)
    stage1_logger.info(f"Added to sys.path for import: {utils_module_dir}")

try:
    # MODIFIED IMPORT: Using extract_all_main_articles_with_content
    from article_parser_utils import extract_all_main_articles_with_content, check_article_number_sequence_continuity, count_words, parse_article_header
    stage1_logger.info("Successfully imported functions from article_parser_utils.")
except ImportError as e:
    stage1_logger.error(f"Failed to import from article_parser_utils. Error: {e}. Searched sys.path: {sys.path}", exc_info=True)
    # Define a placeholder ONLY if import fails, to allow script to run but highlight the error.
    # MODIFIED FALLBACK
    def extract_all_main_articles_with_content(content_text):
        stage1_logger.error("CRITICAL: Using FAULTY placeholder for extract_all_main_articles_with_content due to import error. Article parsing will NOT occur as intended.")
        if content_text and content_text.strip():
             return [{'type': 'preamble', 'content_text': content_text, 'start_line_original':0, 'end_line_original':len(content_text.splitlines()), 'article_number': 'N/A', 'title_line': 'N/A'}]
        return []
    def check_article_number_sequence_continuity(numbers_list, max_consecutive_zero_steps=5):
        stage1_logger.error("CRITICAL: Using FAULTY placeholder for check_article_number_sequence_continuity.")
        return True
    def count_words(text_content): # Renamed arg to avoid conflict
        stage1_logger.error("CRITICAL: Using FAULTY placeholder for count_words.")
        if not text_content: return 0
        return len(str(text_content).split()) # Basic fallback
    def parse_article_header(line_text):
        stage1_logger.error("CRITICAL: Using FAULTY placeholder for parse_article_header.")
        return None

# --- Constants ---
# DB_PATH = "/mnt/data/AI4Deliberation/deliberation_data_gr_updated_better_extraction.db" # Older DB
DB_PATH = "/mnt/data/AI4Deliberation/new_html_extraction/deliberation_data_gr_markdownify.db" # Newer DB used in tests
TABLE_NAME = "articles"
TEXT_COLUMN_NAME = "content"
ID_COLUMN_NAME = "id" # For fetching by original_db_id if needed
MODEL_ID = "google/gemma-3-4b-it" 

STAGE1_PROMPT_TEMPLATE = (
    "Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω κειμένου στα Ελληνικά, σε απλή γλώσσα, "
    "κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως 3 προτάσεις.\n"
    "Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες αν πρόκειται για νομοθετικό άρθρο.\n"
    "Οι περιλήψεις πρέπει να είναι όσο πιο σύντομες γίνεται, διατηρώντας την ουσία του κειμένου και να μην είναι παραπάνω απο 3 προτάσεις σε μήκος.\n"
    "Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης, μη βάζεις εισαγωγή στη περίψη απλώς γράψε την:"
)

# --- Core Functions ---

def load_model_and_processor(model_id=MODEL_ID):
    stage1_logger.info(f"Loading model: {model_id}")
    try:
        model = Gemma3ForConditionalGeneration.from_pretrained(
            model_id,
            device_map="auto",
            torch_dtype=torch.bfloat16
        ).eval()
        processor = AutoProcessor.from_pretrained(model_id)
        stage1_logger.info("Model and processor loaded successfully.")
        return model, processor
    except Exception as e:
        stage1_logger.error(f"Error loading model or processor: {e}", exc_info=True)
        raise

def fetch_articles_for_consultation(consultation_id, article_db_id=None, db_path=DB_PATH, table_name=TABLE_NAME, content_column=TEXT_COLUMN_NAME):
    stage1_logger.info(f"Fetching articles for consultation_id: {consultation_id}{f', article_db_id: {article_db_id}' if article_db_id else ''}")
    articles_data = []
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        if article_db_id is not None:
            query = f"SELECT {ID_COLUMN_NAME}, {content_column} FROM {table_name} WHERE consultation_id = ? AND {ID_COLUMN_NAME} = ? AND {content_column} IS NOT NULL AND {content_column} != ''"
            cursor.execute(query, (consultation_id, article_db_id))
        else:
            query = f"SELECT {ID_COLUMN_NAME}, {content_column} FROM {table_name} WHERE consultation_id = ? AND {content_column} IS NOT NULL AND {content_column} != ''"
            cursor.execute(query, (consultation_id,))
            
        rows = cursor.fetchall()
        for row in rows:
            articles_data.append({'id': row[0], 'content': row[1]})
        stage1_logger.info(f"Fetched {len(articles_data)} articles for consultation_id {consultation_id}{f', article_db_id: {article_db_id}' if article_db_id else ''}.")
    except sqlite3.Error as e:
        stage1_logger.error(f"Database error fetching articles: {e}", exc_info=True)
    except Exception as e:
        stage1_logger.error(f"Unexpected error fetching articles: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return articles_data

# +++ NEW HELPER FOR DRY RUN CSV +++
def fetch_consultation_details_for_dry_run(conn, consultation_id):
    """Fetches title and URL for a given consultation_id from the 'consultations' table."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title, url FROM consultations WHERE id = ?", (consultation_id,))
        row = cursor.fetchone()
        if row:
            return {"title": row[0], "url": row[1]}
        else:
            stage1_logger.warning(f"Consultation details not found for consultation_id: {consultation_id}")
            return {"title": "N/A", "url": "N/A"}
    except sqlite3.Error as e:
        stage1_logger.error(f"Database error fetching consultation details for {consultation_id}: {e}")
        return {"title": "Error fetching", "url": "Error fetching"}
# +++ END NEW HELPER +++

def summarize_chunk_stage1(model, processor, text_chunk_content, prompt_template):
    if not text_chunk_content or not text_chunk_content.strip():
        stage1_logger.info("Input text chunk is empty. Skipping LLM call, returning placeholder summary.")
        log_message_for_trace = (
            f"LLM_CALL_SKIPPED (empty input)\n"
            f"PROMPT_TEMPLATE:\n{prompt_template}\n"
            f"INPUT_TEXT:\n(empty)\n"
            f"LLM_RAW_OUTPUT_START\n(Εσωτερική σημείωση: Το αρχικό περιεχόμενο για αυτή την ενότητα ήταν κενό.)\nLLM_RAW_OUTPUT_END\n"
            f"LLM_CALL_END\n-------------------------------------"
        )
        stage1_logger.debug(log_message_for_trace)
        return "(Εσωτερική σημείωση: Το αρχικό περιεχόμενο για αυτή την ενότητα ήταν κενό.)"

    full_prompt_user_text = f"{prompt_template}\n\n{text_chunk_content}"
    
    log_message_parts = [
        "LLM_CALL_START",
        f"PROMPT:\n{full_prompt_user_text}", 
        "LLM_RAW_OUTPUT_START"
    ]
    
    raw_output_for_log = "(LLM call not attempted or failed before output)"
    try:
        default_system_prompt_text = "You are a helpful assistant specialized in summarizing texts concisely."
        messages = [
            {"role": "system", "content": [{"type": "text", "text": default_system_prompt_text}]},
            {"role": "user", "content": [{"type": "text", "text": full_prompt_user_text}]}
        ]

        inputs = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[-1]
        
        with torch.inference_mode():
            generation = model.generate(**inputs, max_new_tokens=300, do_sample=False, top_k=None, top_p=None) 
            generation = generation[0][input_len:]
        
        decoded_summary = processor.decode(generation, skip_special_tokens=True)
        raw_output_for_log = decoded_summary
        return decoded_summary
    except Exception as e:
        stage1_logger.error(f"Error during Stage 1 summarization call: {e}", exc_info=True)
        raw_output_for_log = f"(Εσωτερική σημείωση: Αποτυχία δημιουργίας περίληψης λόγω σφάλματος: {e})"
        return "(Εσωτερική σημείωση: Αποτυχία δημιουργίας περίληψης λόγω σφάλματος.)"
    finally:
        log_message_parts.append(raw_output_for_log)
        log_message_parts.append("LLM_RAW_OUTPUT_END")
        log_message_parts.append("LLM_CALL_END")
        log_message_parts.append("-------------------------------------")
        stage1_logger.debug("\n".join(log_message_parts))

def run_consultation_stage1(consultation_id, article_db_id_to_process=None, dry_run=False):
    stage1_logger.info(f"Starting Stage 1 processing for consultation_id: {consultation_id}{f', article_db_id: {article_db_id_to_process}' if article_db_id_to_process else ''}{' (DRY RUN)' if dry_run else ''}")
    
    db_conn_for_dry_run_details = None
    model, processor = None, None

    if not dry_run:
        model, processor = load_model_and_processor()
        if not model or not processor:
            stage1_logger.error("Model/Processor failed to load. Aborting.")
            return None 
    else:
        stage1_logger.info("DRY RUN: Skipping model and processor loading.")
        try:
            db_conn_for_dry_run_details = sqlite3.connect(DB_PATH)
            stage1_logger.info("DRY RUN: Database connection established for consultation details.")
        except sqlite3.Error as e:
            stage1_logger.error(f"DRY RUN: Failed to connect to database for consultation details: {e}")

    # Fetch specific article if article_db_id_to_process is provided, else all for consultation_id
    articles_data = fetch_articles_for_consultation(consultation_id, article_db_id=article_db_id_to_process)
    if not articles_data:
        stage1_logger.warning(f"No articles found for consultation_id {consultation_id}{f', article_db_id: {article_db_id_to_process}' if article_db_id_to_process else ''}. Nothing to process.")
        if db_conn_for_dry_run_details:
            db_conn_for_dry_run_details.close()
        return [] 

    all_stage1_results = [] 
    dry_run_report_rows = [] # For CSV output in dry run

    consult_details_for_csv = {"title": "N/A", "url": "N/A"}
    if dry_run and db_conn_for_dry_run_details:
        consult_details_for_csv = fetch_consultation_details_for_dry_run(db_conn_for_dry_run_details, consultation_id)

    for db_entry in articles_data:
        original_db_id = db_entry['id']
        original_db_content = db_entry['content']
        stage1_logger.info(f"--- Processing DB Entry ID: {original_db_id} (Consultation: {consultation_id}) ---")

        # Initialize aggregated data for this db_entry for the dry run report
        aggregated_row_data_for_dry_run = {}
        if dry_run:
            aggregated_row_data_for_dry_run = {
                'consultation_id': consultation_id,
                'consultation_title': consult_details_for_csv['title'],
                'consultation_url': consult_details_for_csv['url'],
                'original_article_db_id': original_db_id,
                'db_entry_content': original_db_content,
                'word_count_original_entry': count_words(original_db_content),
                'preamble_content': "",
                'detected_article_numbers_list': "[]",
                'detected_article_titles_list': "[]",
                'count_of_detected_articles': 0,
                'word_count_total_parsed_articles': 0,
                'sequence_is_continuous': True,
                'article_structure_json': "[]",
                'processing_stage1_status': 'Processed', # Default, can be updated for errors/skips
                'stage1_summary_concatenated': "" # For live run, this would be different
            }

        if not original_db_content or not original_db_content.strip():
            stage1_logger.warning(f"DB Entry ID: {original_db_id} has empty content. Skipping.")
            if dry_run:
                aggregated_row_data_for_dry_run['processing_stage1_status'] = 'Skipped_Empty_Content'
                aggregated_row_data_for_dry_run['word_count_original_entry'] = 0
                dry_run_report_rows.append(aggregated_row_data_for_dry_run)
            continue

        # ---- START DEBUG PRINT for original_db_id == 1 ----
        if original_db_id == 1 and dry_run:
            print(f"DEBUG: Orchestrator - article_db_id: {original_db_id} - Text before parsing:\n>>>\n{original_db_content}\n<<<")
        # ---- END DEBUG PRINT ----

        # extract_all_main_articles_with_content expects only the text content.
        parsed_data = extract_all_main_articles_with_content(original_db_content) # This returns a LIST of chunks

        # ---- START DEBUG PRINT for original_db_id == 1 ----
        if original_db_id == 1 and dry_run:
            print(f"DEBUG: Orchestrator - article_db_id: {original_db_id} - Parsed data from extract_all_main_articles_with_content:\\n>>>\\n{parsed_data}\\n<<<")
        # ---- END DEBUG PRINT ----
        
        article_chunks = [] # Keep this name for clarity in loop below
        if isinstance(parsed_data, list):
            article_chunks = parsed_data 
            if dry_run:
                try:
                    aggregated_row_data_for_dry_run['article_structure_json'] = json.dumps(parsed_data)
                except TypeError as e:
                    stage1_logger.error(f"Error serializing parsed_data to JSON for DB ID {original_db_id}: {e}")
                    aggregated_row_data_for_dry_run['article_structure_json'] = "Error serializing to JSON"
        elif parsed_data is None:
             stage1_logger.warning(f"DB Entry ID: {original_db_id} - extract_all_main_articles_with_content returned None. Treating as no chunks.")
             article_chunks = []
             if dry_run:
                aggregated_row_data_for_dry_run['processing_stage1_status'] = 'Parser_Returned_None'
                aggregated_row_data_for_dry_run['article_structure_json'] = "None"
        else: 
            stage1_logger.warning(f"DB Entry ID: {original_db_id} - extract_all_main_articles_with_content returned an unexpected type: {type(parsed_data)}. Treating as no chunks.")
            article_chunks = []
            if dry_run:
                aggregated_row_data_for_dry_run['processing_stage1_status'] = f'Parser_Returned_Unexpected_Type_{type(parsed_data).__name__}'
                aggregated_row_data_for_dry_run['article_structure_json'] = str(parsed_data)


        if not article_chunks:
            stage1_logger.warning(f"DB Entry ID: {original_db_id} - No chunks (preamble or article) were extracted. Original content (first 300 chars): {original_db_content[:300]}...")
            if dry_run:
                aggregated_row_data_for_dry_run['processing_stage1_status'] = 'No_Chunks_Extracted'
                # word_count_original_entry already set
                dry_run_report_rows.append(aggregated_row_data_for_dry_run) 
            # No summaries to generate for live run if no chunks
            all_stage1_results.append({
                'original_db_id': original_db_id,
                'original_db_content_preview': original_db_content[:200] + "..." if original_db_content else "",
                'chunk_summaries': [] 
            })
            stage1_logger.info(f"--- Finished processing DB Entry ID: {original_db_id}. 0 chunk(s) processed. ---")
            continue


        db_entry_summaries = [] # For live run
        
        # For dry run aggregation:
        temp_parsed_article_numbers = []
        temp_parsed_article_titles = []
        temp_word_count_total_parsed_articles = 0
        temp_preamble_content = ""
        concatenated_summaries_for_dry_run = []


        for idx, chunk in enumerate(article_chunks): 
            chunk_content_to_summarize = chunk.get('content_text', '')
            chunk_type = chunk.get('type', 'unknown') 
            article_number_in_chunk = chunk.get('article_number') 
            title_line_in_chunk = chunk.get('title_line', 'N/A')

            stage1_logger.info(f"  Processing chunk {idx+1}/{len(article_chunks)} (Type: {chunk_type}, ArtNo: {article_number_in_chunk}, Title: \"{title_line_in_chunk[:50]}...\") for DB ID {original_db_id}")

            summary_text = ""
            if dry_run:
                # For dry run, we don't call LLM, but we collect data for the aggregated row
                if chunk_type == 'article':
                    if article_number_in_chunk is not None:
                        try:
                            temp_parsed_article_numbers.append(int(float(article_number_in_chunk)))
                        except (ValueError, TypeError):
                            stage1_logger.warning(f"Could not convert article_number '{article_number_in_chunk}' to int for DB ID {original_db_id}")
                    if title_line_in_chunk: # Add even if 'N/A' for consistency, or filter if needed
                        temp_parsed_article_titles.append(title_line_in_chunk)
                    temp_word_count_total_parsed_articles += count_words(chunk_content_to_summarize)
                elif chunk_type == 'preamble':
                    temp_preamble_content += chunk_content_to_summarize + "\n" # Concatenate if multiple preambles
                
                # Mock summary for the concatenated field (though not used by detect_multiple_articles)
                mock_summary = f"(DryRun-ChunkSummary:Type={chunk_type},Num={article_number_in_chunk})"
                concatenated_summaries_for_dry_run.append(mock_summary)
                summary_text = mock_summary # For consistency if live run logic uses it
            else: # Live run
                summary_text = summarize_chunk_stage1(model, processor, chunk_content_to_summarize, STAGE1_PROMPT_TEMPLATE)
            
            # This part is for the live run's all_stage1_results structure
            db_entry_summaries.append({
                'chunk_type': chunk_type,
                'article_number_in_chunk': article_number_in_chunk,
                'title_line': title_line_in_chunk,
                'original_chunk_content': chunk_content_to_summarize,
                'stage1_summary': summary_text,
                'word_count_original_chunk': count_words(chunk_content_to_summarize),
                'word_count_summary': count_words(summary_text)
            })
            stage1_logger.info(f"  Chunk {idx+1} (Type: {chunk_type}, ArtNo: {article_number_in_chunk}) summary generated/mocked.")

        if dry_run:
            aggregated_row_data_for_dry_run['preamble_content'] = temp_preamble_content.strip()
            aggregated_row_data_for_dry_run['detected_article_numbers_list'] = json.dumps(sorted(list(set(temp_parsed_article_numbers)))) # Unique, sorted
            aggregated_row_data_for_dry_run['detected_article_titles_list'] = json.dumps(temp_parsed_article_titles) # Order might matter, so keep as is
            aggregated_row_data_for_dry_run['count_of_detected_articles'] = len(temp_parsed_article_numbers)
            aggregated_row_data_for_dry_run['word_count_total_parsed_articles'] = temp_word_count_total_parsed_articles
            if temp_parsed_article_numbers:
                # Correctly handle the boolean returned by check_article_number_sequence_continuity
                sequence_check_result = check_article_number_sequence_continuity(temp_parsed_article_numbers)
                is_continuous = sequence_check_result # It directly returns a boolean
                aggregated_row_data_for_dry_run['sequence_is_continuous'] = is_continuous
            else:
                aggregated_row_data_for_dry_run['sequence_is_continuous'] = True # Or False/None if no articles means not continuous
            aggregated_row_data_for_dry_run['stage1_summary_concatenated'] = " | ".join(concatenated_summaries_for_dry_run)
            dry_run_report_rows.append(aggregated_row_data_for_dry_run)
        
        all_stage1_results.append({
            'original_db_id': original_db_id,
            'original_db_content_preview': original_db_content[:200] + "..." if original_db_content else "",
            'chunk_summaries': db_entry_summaries 
        })
        stage1_logger.info(f"--- Finished processing DB Entry ID: {original_db_id}. {len(db_entry_summaries)} chunk(s) processed. ---")

    if dry_run:
        # Save the dry_run_report_data to a CSV file
        dry_run_filename = os.path.join(SCRIPT_DIR, f"dry_run_orchestrator_report_consultation_{consultation_id}_{TIMESTAMP}.csv") # Changed filename
        
        # Define CSV headers to match detect_multiple_articles_in_db.py closely
        fieldnames = [
            'consultation_id', 'consultation_title', 'consultation_url', 
            'original_article_db_id', 
            'db_entry_content', # Full original content
            'word_count_original_entry',
            'preamble_content', 
            'detected_article_numbers_list', # JSON list of numbers
            'detected_article_titles_list', # JSON list of titles
            'count_of_detected_articles',
            'word_count_total_parsed_articles',
            'sequence_is_continuous',
            'article_structure_json', # Full JSON of parsed chunks
            'processing_stage1_status', # e.g., Processed, Skipped_Empty_Content, No_Chunks_Extracted
            'stage1_summary_concatenated' # Concatenated mock summaries for dry run
        ]
        
        stage1_logger.info(f"DRY RUN: Attempting to save report with {len(dry_run_report_rows)} rows to {dry_run_filename}")
        stage1_logger.info(f"DRY RUN: CSV Headers: {fieldnames}")
        if dry_run_report_rows:
             stage1_logger.debug(f"DRY RUN: Sample row keys: {dry_run_report_rows[0].keys()}")


        try:
            with open(dry_run_filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore') # ignore extras for safety
                writer.writeheader()
                writer.writerows(dry_run_report_rows)
            stage1_logger.info(f"DRY RUN: Report saved to {dry_run_filename}")
        except IOError as e:
            stage1_logger.error(f"DRY RUN: Failed to write report CSV: {e}", exc_info=True)
    
    if db_conn_for_dry_run_details:
        db_conn_for_dry_run_details.close()
        stage1_logger.info("DRY RUN: Database connection for consultation details closed.")

    stage1_logger.info(f"Finished Stage 1 processing for consultation_id: {consultation_id}. Processed {len(articles_data)} DB entries, resulting in {len(all_stage1_results)} summary sets.")
    return all_stage1_results

def main():
    parser = argparse.ArgumentParser(description="Run Stage 1 summarization for a consultation.")
    parser.add_argument("--consultation_id", type=int, required=True, help="The ID of the consultation to process.")
    parser.add_argument("--article_db_id", type=int, required=False, default=None, help="Optional: Specific DB ID of an article to process within the consultation.")
    parser.add_argument("--dry_run", action='store_true', help="Run in dry mode (parses, logs, but doesn't call LLM or save actual summaries to DB).")
    parser.add_argument("--debug", action='store_true', help="Enable debug logging for Stage 1 Reasoning Trace to console.")
    args = parser.parse_args()

    if args.debug:
        # Add console handler for debug messages if --debug is passed
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        debug_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - Func: %(funcName)s - Line: %(lineno)d - %(message)s')
        console_handler.setFormatter(debug_formatter)
        stage1_logger.addHandler(console_handler)
        stage1_logger.info("DEBUG mode enabled: Logging Stage 1 Reasoning Trace to console.")

    stage1_logger.info(f"Script started with args: {args}")

    results = run_consultation_stage1(args.consultation_id, article_db_id_to_process=args.article_db_id, dry_run=args.dry_run)

    if results:
        stage1_logger.info("Processing completed. Result preview (first entry, first chunk summary if available):")
        if results and results[0]['chunk_summaries']:
            first_summary_info = results[0]['chunk_summaries'][0]
            stage1_logger.info(f"  Original DB ID: {results[0]['original_db_id']}")
            stage1_logger.info(f"  Chunk Type: {first_summary_info['chunk_type']}")
            stage1_logger.info(f"  Article Number in Chunk: {first_summary_info['article_number_in_chunk']}")
            stage1_logger.info(f"  Summary: {first_summary_info['stage1_summary'][:100]}...")
        else:
            stage1_logger.info("  No summaries generated or results structure unexpected.")
    else:
        stage1_logger.info("Processing completed with no results or an error occurred.")

    stage1_logger.info("Script finished.")

if __name__ == "__main__":
    main() 