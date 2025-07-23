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
import re # For title range parsing
from typing import List, Dict, Any, Tuple, Set # For type hinting

# --- Environment Setup ---
os.environ['TORCHDYNAMO_DISABLE'] = '1'

# --- Dynamically add article_parser_utils to path and import ---
# Add the parent directory of article_extraction_analysis to sys.path
# to allow importing article_parser_utils
ARTICLE_PARSER_UTILS_PATH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'new_html_extraction', 'article_extraction_analysis'))
if ARTICLE_PARSER_UTILS_PATH not in sys.path:
    sys.path.append(ARTICLE_PARSER_UTILS_PATH)
import article_parser_utils # Now this should work at module level

# --- Logger Setup for Stage 1 Reasoning Trace ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Generate a timestamp string for the log file
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE_NAME = f"stage1_reasoning_trace_{TIMESTAMP}.log"
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, LOG_FILE_NAME)

stage1_logger = logging.getLogger("Stage1ReasoningTrace")
stage1_logger.setLevel(logging.DEBUG)
stage1_logger.propagate = False # Prevent duplicate messages to root logger

# Add reasoning trace logger for clean prompt/output logging
reasoning_trace_logger = logging.getLogger("ReasoningTrace")
reasoning_trace_logger.setLevel(logging.DEBUG)
reasoning_trace_logger.propagate = False

if not stage1_logger.hasHandlers(): # Add handler only if it doesn't exist
    trace_file_handler = logging.FileHandler(LOG_FILE_PATH, mode='w') # 'w' is fine for unique filenames
    # General formatter for most logs
    general_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    trace_file_handler.setFormatter(general_formatter)
    stage1_logger.addHandler(trace_file_handler)
    
    # Add reasoning trace handler to same file
    reasoning_trace_handler = logging.FileHandler(LOG_FILE_PATH, mode='a')
    reasoning_trace_formatter = logging.Formatter('%(message)s')  # Just the message, no timestamp
    reasoning_trace_handler.setFormatter(reasoning_trace_formatter)
    reasoning_trace_logger.addHandler(reasoning_trace_handler)
    
    stage1_logger.info(f"Stage 1 Reasoning Trace logger initialized. Log file: {LOG_FILE_PATH}")

stage1_logger.info(f"TORCHDYNAMO_DISABLE set to: {os.environ.get('TORCHDYNAMO_DISABLE')}")

# --- Constants ---
# DB_PATH = "/mnt/data/AI4Deliberation/deliberation_data_gr_updated_better_extraction.db" # Older DB
DB_PATH = "/mnt/data/AI4Deliberation/new_html_extraction/deliberation_data_gr_markdownify.db" # Newer DB used in tests
TABLE_NAME = "articles"
CONSULTATIONS_TABLE_NAME = "consultations" # For fetching consultation title in dry run
TEXT_COLUMN_NAME = "content"
TITLE_COLUMN_NAME = "title" # For DB article title - THIS WAS MISSING
ID_COLUMN_NAME = "id" # For fetching by original_db_id if needed
MODEL_ID = "google/gemma-3-4b-it" 

STAGE1_PROMPT_TEMPLATE = (
    "Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω κειμένου στα Ελληνικά, σε απλή γλώσσα, "
    "κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως 3 προτάσεις.\n"
    "Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες αν πρόκειται για νομοθετικό άρθρο.\n"
    "Οι περιλήψεις πρέπει να είναι όσο πιο σύντομες γίνεται, διατηρώντας την ουσία του κειμένου και να μην είναι παραπάνω απο 3 προτάσεις σε μήκος.\n"
    "Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης, μη βάζεις εισαγωγή στη περίψη απλώς γράψε την:"
)

STAGE2_PROMPT_TEMPLATE = (
    "Οι παρακάτω είναι ατομικές περιλήψεις πολλαπλών άρθρων από μία ενιαία διαβούλευση. "
    "Παρακαλώ συνδυάστε τις σε ένα ενιαίο, συνεκτικό και περιεκτικό κείμενο στα Ελληνικά που αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου. "
    "Στοχεύστε σε μια περιεκτική επισκόπηση περίπου 350 λέξεων και 6-7 παραγράφων."
)

# --- Article Chunking Helper Functions (Inspired by consultation_article_sequence_extractor.py) ---

TITLE_RANGE_RE = re.compile(r"\(\s*(\d{1,3})\s*[–\-]\s*(\d{1,3})\s*\)") # For parsing ranges like (1-5) in titles

def parse_db_article_title_range(db_article_title: str) -> List[int]:
    """Parses a numeric range (e.g., Άρθρα 1-5) from a DB article title string."""
    # This regex is simpler than the one in consultation_article_sequence_extractor
    # and focuses on ranges like (1-5) or ( 1 - 5 ), common in titles.
    # It does not look for "Άρθρο" prefix explicitly within the regex, assuming titles might vary.
    # The one in generate_partial_range_report.py is r"\(\s*(?:(?:[ΑAΆÁ]ρθρ?ο?\s+)|(?:[ΑAΆÁ]ρθρα\s+))?(\d{1,3})\s*[-\u2013\u2014]\s*(\d{1,3})\s*\)"
    # For now, using a simpler one, can be enhanced if needed.
    m = TITLE_RANGE_RE.search(db_article_title or "")
    if not m:
        return []
    try:
        start, end = int(m.group(1)), int(m.group(2))
        return list(range(start, end + 1)) if start <= end else []
    except ValueError:
        return []

def find_and_prioritize_mentions_for_gaps(text_content: str, needed_numbers: List[int]) -> List[Dict[str, Any]]:
    """Finds all mentions for needed_numbers in text and returns a list of chosen mentions with priority."""
    if not needed_numbers or not text_content:
        return []
    
    needed_set = set(needed_numbers)
    candidate_mentions_for_needed_numbers: Dict[int, Dict[str, Any]] = {}

    all_mentions_in_text = article_parser_utils._get_true_main_article_header_locations(text_content) # From article_parser_utils
    stage1_logger.debug(f"Found {len(all_mentions_in_text)} total mentions in text for gap filling.")

    for mention_details in all_mentions_in_text:
        parsed_mention_info = mention_details.get("parsed_details", {})
        article_num_of_mention = parsed_mention_info.get("main_number")

        if article_num_of_mention is None or article_num_of_mention not in needed_set:
            continue # This mention is not for a number we currently need

        # Determine priority (lower is better)
        priority = 1
        if mention_details.get("is_start_of_line") and not mention_details.get("is_quoted"):
            priority = 1
        elif mention_details.get("is_start_of_line") and mention_details.get("is_quoted"):
            priority = 2
        elif not mention_details.get("is_start_of_line") and not mention_details.get("is_quoted"):
            priority = 3
        else: # Not start of line and quoted
            priority = 4
        
        current_best_mention_for_num = candidate_mentions_for_needed_numbers.get(article_num_of_mention)
        if current_best_mention_for_num is None or priority < current_best_mention_for_num.get("priority", 5):
            mention_to_store = mention_details.copy() # Work with a copy
            mention_to_store["priority"] = priority # Store determined priority
            # Ensure it's in the format expected by reconstruct_article_chunks_with_prioritized_mentions
            # The 'parsed_info' key is used in the reconstructor's mapping
            mention_to_store["parsed_info"] = parsed_mention_info 
            candidate_mentions_for_needed_numbers[article_num_of_mention] = mention_to_store
            stage1_logger.debug(f"Chose mention for article {article_num_of_mention} (Prio: {priority}): '{mention_details.get('match_text')}' at line {mention_details.get('line_index')}")

    return list(candidate_mentions_for_needed_numbers.values())

def get_internally_completed_chunks_for_db_article(db_article_content: str, db_article_title: str) -> List[Dict[str, Any]]:
    """Processes a single DB article's content to find and complete internal article sequences, then returns structured chunks."""
    if not db_article_content or not db_article_content.strip():
        stage1_logger.info("DB article content is empty. Returning no chunks.")
        return []

    stage1_logger.debug(f"Starting internal completion for DB article. Title: '{db_article_title}'")
    
    # 1. Get initial sequence from "true" headers (start of line, not quoted)
    true_headers_locations = article_parser_utils._get_true_main_article_header_locations(db_article_content)
    initial_sequence_numbers = sorted({h_loc["article_number"] for h_loc in true_headers_locations})
    stage1_logger.debug(f"Initial 'true' header sequence numbers: {initial_sequence_numbers}")

    mentions_for_reconstruction = [] # These will be passed to the final chunk reconstruction

    # 2. Try to complete based on DB article's own title range (if any)
    expected_numbers_from_title = parse_db_article_title_range(db_article_title)
    if expected_numbers_from_title:
        stage1_logger.debug(f"Numbers expected from DB article title '{db_article_title}': {expected_numbers_from_title}")
        missing_compared_to_title = sorted(list(set(expected_numbers_from_title) - set(initial_sequence_numbers)))
        if missing_compared_to_title:
            stage1_logger.debug(f"Numbers missing from initial sequence compared to title range: {missing_compared_to_title}")
            mentions_for_title_gaps = find_and_prioritize_mentions_for_gaps(db_article_content, missing_compared_to_title)
            mentions_for_reconstruction.extend(mentions_for_title_gaps)
            found_numbers_for_title_gaps = {m['parsed_info'].get('main_number') for m in mentions_for_title_gaps}
            initial_sequence_numbers = sorted(list(set(initial_sequence_numbers).union(found_numbers_for_title_gaps)))
            stage1_logger.debug(f"Sequence after attempting to fill title gaps: {initial_sequence_numbers}")
        else:
            stage1_logger.debug("Initial sequence already satisfies title range (if any).")
    else:
        stage1_logger.debug("No numeric range found in DB article title.")

    # 3. Try to complete remaining internal gaps in the sequence derived so far
    # A 'gap' is e.g. [1, 3] -> gap is [2]
    internal_gaps_to_fill = []
    if len(initial_sequence_numbers) >= 2:
        for i in range(len(initial_sequence_numbers) - 1):
            start_num, end_num = initial_sequence_numbers[i], initial_sequence_numbers[i+1]
            if end_num > start_num + 1: # A gap exists
                internal_gaps_to_fill.extend(range(start_num + 1, end_num))
    
    if internal_gaps_to_fill:
        # Remove duplicates if any number was needed by both title and internal gap fill
        internal_gaps_to_fill = sorted(list(set(internal_gaps_to_fill) - set(m['parsed_info'].get('main_number') for m in mentions_for_reconstruction)))
        stage1_logger.debug(f"Remaining internal numeric gaps to fill: {internal_gaps_to_fill}")
        if internal_gaps_to_fill: # Check again if any are left after filtering
            mentions_for_internal_gaps = find_and_prioritize_mentions_for_gaps(db_article_content, internal_gaps_to_fill)
            mentions_for_reconstruction.extend(mentions_for_internal_gaps)
            # No need to update initial_sequence_numbers further for this step, as reconstruction uses all delimiters.
            stage1_logger.debug(f"Added {len(mentions_for_internal_gaps)} mentions for internal gaps.")
    else:
        stage1_logger.debug("No further internal numeric gaps identified in the sequence.")

    # 4. Reconstruct chunks using true headers and all collected prioritized mentions
    # Prepare main_delims for reconstruct_article_chunks_with_prioritized_mentions
    main_delimiters_for_reconstruction = []
    for h_loc in true_headers_locations:
        # Ensure the structure matches what reconstruct_article_chunks_with_prioritized_mentions expects
        # It expects 'line_num', 'parsed_header', 'raw_header_line', 'char_offset_in_original_line'
        raw_line = h_loc.get("original_line_text", "")
        match_text = h_loc.get("match_text", "")
        char_offset = raw_line.find(match_text) if raw_line and match_text else 0
        
        main_delimiters_for_reconstruction.append({
            "line_num": h_loc["line_index"] + 1, # Convert 0-indexed to 1-indexed
            "parsed_header": h_loc["parsed_header_details_copy"], # This was in consultation_article_sequence_extractor
            "raw_header_line": match_text, 
            "char_offset_in_original_line": max(0, char_offset)
        })

    # Mentions are already mostly in the right format, ensure 'parsed_info' is present
    # find_and_prioritize_mentions_for_gaps already adds 'parsed_info'
    # reconstruct_article_chunks_with_prioritized_mentions also needs line_number to be 1-indexed.
    # find_all_article_mentions returns line_index (0-indexed), so adjust here.
    formatted_mentions_for_reconstruction = []
    for m in mentions_for_reconstruction:
        formatted_mention = m.copy()
        formatted_mention["line_number"] = m["line_index"] + 1 # Adjust to 1-indexed
        formatted_mentions_for_reconstruction.append(formatted_mention)

    stage1_logger.debug(f"Reconstructing chunks with {len(main_delimiters_for_reconstruction)} main delimiters and {len(formatted_mentions_for_reconstruction)} prioritized mentions.")
    
    # Ensure `original_text`, `main_header_locations`, `prioritized_mentions_input`
    reconstructed_chunks = article_parser_utils.reconstruct_article_chunks_with_prioritized_mentions(
        original_text=db_article_content,
        main_header_locations=main_delimiters_for_reconstruction, # This expects a specific format, ensure it matches
        prioritized_mentions_input=formatted_mentions_for_reconstruction # This also expects specific format
    )

    if not reconstructed_chunks:
        stage1_logger.warning(f"Chunk reconstruction returned empty for DB article title: '{db_article_title}'. This might happen if content is only whitespace or very unusual.")
        # If reconstructor returns None or [], and content was not empty, treat as single block to be safe for summarization
        if db_article_content and db_article_content.strip():
            stage1_logger.debug("Treating non-empty content as a single fallback chunk.")
            return [{'type': 'preamble', 'content': db_article_content, 'article_number': None, 'raw_header': 'N/A - Fallback single chunk'}]
        return []

    # Filter out empty preamble/other chunks if necessary, or ensure they are handled by caller
    final_chunks_for_summarization = []
    for i, chunk in enumerate(reconstructed_chunks):
        chunk_content = chunk.get('content_text') or chunk.get('content')
        if chunk_content and chunk_content.strip():
            # Add info needed for dry run and processing
            chunk['chunk_index_within_db_article'] = i
            chunk['db_article_title_for_chunk'] = db_article_title # Carry over parent DB article title
            # 'article_number' should be set by reconstructor for 'article' type chunks
            # 'raw_header' or 'title_line' should also be set by reconstructor
            final_chunks_for_summarization.append(chunk)
        else:
            stage1_logger.debug(f"Skipping empty chunk (index {i}) after reconstruction.")
            
    stage1_logger.info(f"Processed DB article '{db_article_title}', resulted in {len(final_chunks_for_summarization)} non-empty chunks for summarization.")
    return final_chunks_for_summarization

# --- Core Functions ---

def load_model_and_processor(model_id=MODEL_ID):
    stage1_logger.info(f"Loading model: {model_id}")
    try:
        model = Gemma3ForConditionalGeneration.from_pretrained(
            model_id,
            device_map="auto",
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa"
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
            query = f"SELECT {ID_COLUMN_NAME}, {TITLE_COLUMN_NAME}, {content_column} FROM {table_name} WHERE consultation_id = ? AND {ID_COLUMN_NAME} = ? AND {content_column} IS NOT NULL AND {content_column} != ''"
            cursor.execute(query, (consultation_id, article_db_id))
        else:
            query = f"SELECT {ID_COLUMN_NAME}, {TITLE_COLUMN_NAME}, {content_column} FROM {table_name} WHERE consultation_id = ? AND {content_column} IS NOT NULL AND {content_column} != ''"
            cursor.execute(query, (consultation_id,))
            
        rows = cursor.fetchall()
        for row in rows:
            articles_data.append({'id': row[0], 'title': row[1], 'content': row[2]})
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
    """Fetches consultation title and URL for dry run reporting."""
    consultation_title = ""
    consultation_url = ""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT title, url FROM consultations WHERE id = ?", (consultation_id,))
        result = cursor.fetchone()
        if result:
            consultation_title, consultation_url = result
        else:
            stage1_logger.warning(f"No consultation details found for consultation_id {consultation_id}")
    except sqlite3.Error as e:
        stage1_logger.error(f"Database error fetching consultation details: {e}", exc_info=True)
    except Exception as e:
        stage1_logger.error(f"Error fetching consultation details: {e}", exc_info=True)
    
    return consultation_title, consultation_url

def check_response_completeness(response_text):
    """
    Checks if the response ends with a proper sentence terminator.
    Returns True if the response is complete, False if it appears truncated.
    """
    if not response_text:
        return False
    
    end_punctuation = ['.', '?', '!', '."', '?"', '!"', '.»', '?»', '!»']
    is_complete = any(response_text.strip().endswith(punct) for punct in end_punctuation)
    return is_complete

def get_token_count(text, processor):
    """Count tokens in text using the processor's tokenizer."""
    if not text or not isinstance(text, str) or text.strip() == "":
        return 0
    try:
        inputs = processor.tokenizer(text, return_tensors=None, add_special_tokens=True)
        return len(inputs["input_ids"])
    except Exception as e:
        stage1_logger.error(f"Error tokenizing text for count: {e}")
        return 0

def summarize_text(model, processor, stage_id: str, initial_llm_prompt_text: str,
                   core_input_data_for_correction: str, original_task_instructions_for_correction: str,
                   target_tokens_for_summary: int, retry_if_truncated=True):
    """
    Generic summarization function with truncation handling and retries.
    Based on the implementation from run_summarization.py
    """
    
    # Add reasoning trace
    reasoning_trace_logger.info(f"\n{'='*80}")
    reasoning_trace_logger.info(f"STAGE {stage_id} - SUMMARIZATION CALL")
    reasoning_trace_logger.info(f"{'='*80}")
    reasoning_trace_logger.info(f"PROMPT:\n{initial_llm_prompt_text}")
    reasoning_trace_logger.info(f"\n{'-'*40}")
    
    final_returned_value_for_log = ""
    if not initial_llm_prompt_text or not isinstance(initial_llm_prompt_text, str) or initial_llm_prompt_text.strip() == "":
        stage1_logger.warning(f"[Stage {stage_id}] Skipping summarization due to empty or invalid initial_llm_prompt_text.")
        final_returned_value_for_log = "Skipped due to empty/invalid prompt."
        reasoning_trace_logger.info(f"OUTPUT: {final_returned_value_for_log}")
        reasoning_trace_logger.info(f"{'='*80}\n")
        return None

    default_system_prompt_text = "You are a helpful assistant specialized in summarizing texts concisely."
    messages = [
        {"role": "system", "content": [{"type": "text", "text": default_system_prompt_text}]}, 
        {"role": "user", "content": [{"type": "text", "text": initial_llm_prompt_text}]}
    ]

    try:
        stage1_logger.debug(f"[Stage {stage_id}] Attempting initial LLM call.")
        inputs = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[-1]
        with torch.inference_mode():
            generation = model.generate(**inputs, max_new_tokens=target_tokens_for_summary, do_sample=False)
            generation = generation[0][input_len:]
        decoded_summary = processor.decode(generation, skip_special_tokens=True)
        is_complete_initial = check_response_completeness(decoded_summary)
        stage1_logger.debug(f"[Stage {stage_id}] Initial LLM call completed. Completeness: {is_complete_initial}")

        if retry_if_truncated and not is_complete_initial:
            stage1_logger.warning(f"[Stage {stage_id}] Generated response appears to be truncated: '{decoded_summary[-50:]}...'")
            
            # Stage-specific constraints for truncation correction
            specific_constraints_for_stage = ""
            if stage_id == "1":
                specific_constraints_for_stage = (
                    "- Η περίληψη πρέπει να είναι έως 2-3 προτάσεις το μέγιστο.\n"
                    "- Πρέπει να περιλαμβάνει τις βασικές αλλαγές σε νόμους, θεσμούς, ή διαδικασίες που αναφέρονται στο άρθρο."
                )
            elif stage_id == "2":
                specific_constraints_for_stage = (
                    "- Η συνολική περίληψη πρέπει να αποτυπώνει τα κύρια σημεία και τον "
                    "ευρύτερο στόχο του νομοσχεδίου.\n"
                    "- Πρέπει να περιορίζεται σε περίπου 300 λέξεις και 6 "
                    "παραγράφους το μέγιστο.\n"
                    "- Πρέπει να διατηρεί τη συνοχή και την περιεκτικότητα.\n"
                    "- Πρέπει να είναι κατανοητή σε πολίτες χωρίς εξειδικευμένες "
                    "νομικές γνώσεις."
                )
            elif stage_id == "3.1":
                specific_constraints_for_stage = (
                    "- Η σημείωση πρέπει να εστιάζει μόνο στην πιο σημαντική πληροφορία που λείπει από την Αρχική Συνολική Περίληψη (Στάδιο 2) σε σχέση με το συγκεκριμένο άρθρο.\n"
                    "- Πρέπει να είναι μία μόνο πρόταση, έως 150-200 τόκενς."
                )
            elif stage_id == "3.2":
                specific_constraints_for_stage = (
                    "- Η τελική περίληψη πρέπει να ενσωματώνει τα σημαντικότερα σημεία που επισημάνθηκαν στις σημειώσεις.\n"
                    "- Πρέπει να διατηρεί τη συνοχή, την ακρίβεια και τη συντομία.\n"
                    "- Πρέπει να περιορίζεται σε περίπου 300 λέξεις και 6 παραγράφους το μέγιστο.\n"
                    "- Πρέπει να είναι κατανοητή σε πολίτες χωρίς εξειδικευμένες νομικές γνώσεις."
                )

            correction_prompt_header = (
                "Η παρακάτω απόκριση που παρήγαγες κόπηκε επειδή πιθανόν ξεπέρασες το όριο των επιτρεπτών χαρακτήρων (tokens):\n\n"
                "--- ΑΡΧΗ ΑΠΟΚΟΜΜΕΝΗΣ ΑΠΟΚΡΙΣΗΣ ---\n"
            )
            correction_prompt_instructions_header = (
                "\n--- ΤΕΛΟΣ ΑΠΟΚΟΜΜΕΝΗΣ ΑΠΟΚΡΙΣΗΣ ---\n\n"
                "Για να δημιουργήσεις αυτή την απόκριση, σου δόθηκαν οι παρακάτω οδηγίες και δεδομένα εισόδου:\n\n"
                "--- ΑΡΧΙΚΕΣ ΟΔΗΓΙΕΣ ΕΡΓΑΣΙΑΣ ---\n"
            )
            correction_prompt_input_data_header = (
                "\n--- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΟΔΗΓΙΩΝ ΕΡΓΑΣΙΑΣ ---\n\n"
                "--- ΑΡΧΙΚΑ ΔΕΔΟΜΕΝΑ ΕΙΣΟΔΟΥ ---\n"
            )
            correction_prompt_footer = (
                "\n--- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΔΕΔΟΜΕΝΩΝ ΕΙΣΟΔΟΥ ---\n\n"
                "ΠΑΡΑΚΑΛΩ ΔΗΜΙΟΥΡΓΗΣΕ ΜΙΑ ΝΕΑ, ΣΥΝΤΟΜΟΤΕΡΗ ΕΚΔΟΧΗ:\n"
                "Μελέτησε προσεκτικά την αποκομμένη απόκριση, τις αρχικές οδηγίες και τα αρχικά δεδομένα.\n"
                "Η νέα σου απόκριση πρέπει:\n"
                "- Να είναι σημαντικά συντομότερη από την προηγούμενη προσπάθεια.\n"
                "- Να διατηρεί τα πιο κρίσιμα σημεία σε σχέση με τις αρχικές οδηγίες.\n"
                "- Να ολοκληρώνεται σωστά με κατάλληλο σημείο στίξης (π.χ., τελεία).\n"
            )
            correction_prompt_final_instruction = "\nΠαρακαλώ γράψε μόνο τη νέα, διορθωμένη απόκριση."
            
            correction_prompt = (
                f"{correction_prompt_header}{decoded_summary}"
                f"{correction_prompt_instructions_header}{original_task_instructions_for_correction}"
                f"{correction_prompt_input_data_header}{core_input_data_for_correction}"
                f"{correction_prompt_footer}{specific_constraints_for_stage}"
                f"{correction_prompt_final_instruction}"
            )
            
            retry_system_prompt_text = (
                "Είσαι ένας εξυπηρετικός βοηθός. Η προηγούμενη απόκρισή σου ήταν ατελής (αποκομμένη). "
                "Παρακαλώ διόρθωσέ την ακολουθώντας τις νέες οδηγίες για συντομότερη απάντηση και λαμβάνοντας υπόψη το παρεχόμενο πλαίσιο."
            )
            retry_messages = [
                {"role": "system", "content": [{"type": "text", "text": retry_system_prompt_text}]}, 
                {"role": "user", "content": [{"type": "text", "text": correction_prompt}]}
            ]
            
            reasoning_trace_logger.info(f"TRUNCATION DETECTED - RETRY PROMPT:\n{correction_prompt}")
            reasoning_trace_logger.info(f"\n{'-'*40}")
            
            stage1_logger.debug(f"[Stage {stage_id}] Attempting truncation correction retry LLM call.")
            retry_inputs = processor.apply_chat_template(retry_messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
            retry_input_len = retry_inputs["input_ids"].shape[-1]
            with torch.inference_mode():
                retry_generation = model.generate(**retry_inputs, max_new_tokens=target_tokens_for_summary, do_sample=False)
                retry_generation = retry_generation[0][retry_input_len:]
            retry_summary = processor.decode(retry_generation, skip_special_tokens=True)
            is_complete_retry = check_response_completeness(retry_summary)
            stage1_logger.debug(f"[Stage {stage_id}] Truncation correction retry completed. Completeness: {is_complete_retry}")

            if is_complete_retry:
                stage1_logger.info(f"[Stage {stage_id}] Retry successful, got a complete response.")
                final_returned_value_for_log = retry_summary + "\n[Σημείωση: Αυτή η απόκριση ενδέχεται να έχει συντομευτεί αυτόματα λόγω προηγούμενης αποκοπής.]"
                reasoning_trace_logger.info(f"RETRY OUTPUT: {final_returned_value_for_log}")
                reasoning_trace_logger.info(f"{'='*80}\n")
                return final_returned_value_for_log
            else:
                stage1_logger.warning(f"[Stage {stage_id}] Even the retry attempt resulted in a truncated response.")
                final_returned_value_for_log = decoded_summary + "\n[Σημείωση: Η παραπάνω απόκριση εντοπίστηκε ως πιθανώς ατελής (αποκομμένη) από τον αυτόματο έλεγχο, καθώς δεν ολοκληρώθηκε με κατάλληλο σημείο στίξης.]"
                reasoning_trace_logger.info(f"TRUNCATED OUTPUT: {final_returned_value_for_log}")
                reasoning_trace_logger.info(f"{'='*80}\n")
                return final_returned_value_for_log
        else:
            final_returned_value_for_log = decoded_summary
            reasoning_trace_logger.info(f"OUTPUT: {final_returned_value_for_log}")
            reasoning_trace_logger.info(f"{'='*80}\n")
            return final_returned_value_for_log
    except Exception as e:
        stage1_logger.error(f"[Stage {stage_id}] Error during summarization: {e}", exc_info=True)
        final_returned_value_for_log = f"Error during summarization: {e}"
        reasoning_trace_logger.info(f"ERROR OUTPUT: {final_returned_value_for_log}")
        reasoning_trace_logger.info(f"{'='*80}\n")
        return None

def summarize_chunk_stage1(model, processor, chunk_title_line: str, text_chunk_content: str, prompt_template: str):
    """
    Summarizes a single text chunk using Stage 1 logic with truncation handling.
    """
    if not text_chunk_content or text_chunk_content.strip() == "":
        stage1_logger.warning("Empty text chunk content provided to summarize_chunk_stage1.")
        return "Το περιεχόμενο αυτής της ενότητας ήταν κενό."
    
    # Prepare the full prompt
    full_prompt = f"{prompt_template}\n\nΤίτλος Ενότητας: {chunk_title_line}\n\nΚείμενο Ενότητας:\n{text_chunk_content}"
    
    # Use the generic summarize_text function with Stage 1 parameters
    stage1_logger.info("Starting model.generate()...")
    import time
    start_time = time.time()
    
    summary = summarize_text(
        model=model,
        processor=processor,
        stage_id="1",
        initial_llm_prompt_text=full_prompt,
        core_input_data_for_correction=text_chunk_content,
        original_task_instructions_for_correction=prompt_template,
        target_tokens_for_summary=300,
        retry_if_truncated=True
    )
    
    end_time = time.time()
    stage1_logger.info(f"model.generate() completed in {end_time - start_time:.2f} seconds.")
    
    if summary is None:
        stage1_logger.error("Summarization failed, returning error message.")
        return "Η περίληψη αυτής της ενότητας απέτυχε."
    
    return summary

def run_consultation_summarization(consultation_id, article_db_id_to_process=None, dry_run=False):
    """
    Runs the full summarization workflow: Stage 1 (individual articles) + Stage 2 (cohesive summary).
    """
    # === STAGE 1: Individual Article Summarization ===
    stage1_logger.info(f"=== Starting Stage 1: Individual Article Summarization for consultation_id: {consultation_id} ===")
    
    # Load model for summarization (skip if dry run)
    model, processor = None, None
    if not dry_run:
        model, processor = load_model_and_processor()
        if model is None or processor is None:
            stage1_logger.error("Failed to load model and processor. Cannot proceed with actual summarization.")
            return [], ""

    # Fetch articles from database
    db_article_entries = fetch_articles_for_consultation(consultation_id, article_db_id_to_process)
    if not db_article_entries:
        stage1_logger.warning(f"No articles found for consultation_id {consultation_id}")
        return [], ""

    stage1_logger.info(f"Found {len(db_article_entries)} articles for consultation_id {consultation_id}")

    # Track results
    individual_article_details_for_report = []
    all_individual_summaries_text = []
    dry_run_csv_data = []

    consultation_title_for_dry_run, consultation_url_for_dry_run = "N/A", "N/A"
    if dry_run:
        conn_details = None
        try:
            conn_details = sqlite3.connect(DB_PATH)
            consultation_title_for_dry_run, consultation_url_for_dry_run = fetch_consultation_details_for_dry_run(conn_details, consultation_id)
        finally:
            if conn_details:
                conn_details.close()

    # Process each article
    for db_article_entry in db_article_entries:
        original_db_id = db_article_entry['id']
        original_db_title = db_article_entry['title']
        original_db_content = db_article_entry['content']

        stage1_logger.info(f"Processing DB Article ID: {original_db_id}, Title: '{original_db_title}'")

        if not original_db_content or not original_db_content.strip():
            stage1_logger.warning(f"DB Article ID: {original_db_id} has empty content. Skipping summarization, adding placeholder.")
            summary_text = "(Εσωτερική σημείωση: Το αρχικό περιεχόμενο αυτής της ενότητας της διαβούλευσης ήταν κενό.)"
            all_individual_summaries_text.append(summary_text)
            detail_entry = {
                'consultation_id': consultation_id,
                'db_article_id': original_db_id,
                'chunk_index_within_db_article': 0,
                'chunk_article_number': 'N/A',
                'chunk_title_line': original_db_title,
                'word_count': 0,
                'original_text_chunk': '',
                "original_content_excerpt": original_db_content[:200] + ('...' if len(original_db_content) > 200 else '')
            }
            if dry_run:
                detail_entry['summary'] = summary_text
                dry_run_csv_data.append(detail_entry)
            else:
                detail_entry['summary_model_actual'] = summary_text
            individual_article_details_for_report.append(detail_entry)
            continue

        # Get internally completed and segmented chunks for the current DB article
        sub_article_chunks = get_internally_completed_chunks_for_db_article(original_db_content, original_db_title)

        if not sub_article_chunks:
            stage1_logger.warning(f"No processable sub-article chunks found for DB Article ID: {original_db_id} after parsing. Treating as single block if original content existed.")
            if original_db_content and original_db_content.strip():
                sub_article_chunks = [{
                    'type': 'preamble', 
                    'content': original_db_content, 
                    'article_number': None, 
                    'raw_header': 'N/A - Fallback Whole DB Entry',
                    'chunk_index_within_db_article': 0,
                    'db_article_title_for_chunk': original_db_title
                }]
            else:
                stage1_logger.debug(f"DB Article ID: {original_db_id} - No sub_article_chunks and no fallback content. Continuing to next DB article.")
                continue 

        for chunk in sub_article_chunks:
            chunk_content_to_summarize = chunk.get('content_text') or chunk.get('content')
            chunk_title_for_log = chunk.get('raw_header') or chunk.get('title_line') or original_db_title
            chunk_article_num_for_log = chunk.get('article_number', 'N/A')
            chunk_idx_for_log = chunk.get('chunk_index_within_db_article', 'N/A')

            stage1_logger.info(f"Summarizing chunk: DB_ID={original_db_id}, ChunkIdx={chunk_idx_for_log}, Title/Header='{chunk_title_for_log}', ArtNo={chunk_article_num_for_log}")
            
            wc = article_parser_utils.count_words(chunk_content_to_summarize)
            stage1_logger.debug(f"Word count for current chunk: {wc}")

            summary_text = ""
            if dry_run:
                summary_text = f"[Dry Run Summary for DB_ID:{original_db_id}/ChunkIdx:{chunk_idx_for_log}/ArtNo:{chunk_article_num_for_log}, Title: '{chunk_title_for_log}']"
                stage1_logger.info("Dry run: Skipping actual summarization call.")
            else:
                if model and processor:
                    summary_text = summarize_chunk_stage1(model, processor, chunk_title_for_log, chunk_content_to_summarize, STAGE1_PROMPT_TEMPLATE)
                else:
                    summary_text = "[Error: Model not loaded, cannot summarize]"
                    stage1_logger.error("Model/processor not available for summarization.")
            
            all_individual_summaries_text.append(summary_text)
            
            detail_entry = {
                'consultation_id': consultation_id,
                'db_article_id': original_db_id,
                'chunk_index_within_db_article': chunk_idx_for_log,
                'chunk_article_number': chunk_article_num_for_log,
                'chunk_title_line': chunk_title_for_log,
                'word_count': wc,
                'original_text_chunk': chunk_content_to_summarize,
                "original_content_excerpt": chunk_content_to_summarize[:200] + ('...' if len(chunk_content_to_summarize) > 200 else '')
            }
            if dry_run:
                detail_entry['summary'] = summary_text
                dry_run_csv_data.append(detail_entry)
            else:
                detail_entry['summary_model_actual'] = summary_text
            
            individual_article_details_for_report.append(detail_entry)

    stage1_logger.info(f"=== Stage 1 Complete: Generated {len(all_individual_summaries_text)} individual summaries ===")

    # === STAGE 2: Cohesive Summary Generation ===
    stage1_logger.info(f"=== Starting Stage 2: Cohesive Summary Generation for consultation_id: {consultation_id} ===")
    
    cohesive_summary = ""
    if not all_individual_summaries_text:
        cohesive_summary = "No individual summaries were generated to combine."
        stage1_logger.info("Skipping Stage 2 as no individual summaries were generated.")
    else:
        # Filter out error/empty summaries
        valid_summaries = [s for s in all_individual_summaries_text if s and 
                          "Dry Run Summary" not in s and 
                          "Error: Model not loaded" not in s and 
                          "Το περιεχόμενο αυτής της ενότητας ήταν κενό" not in s and
                          "Η περίληψη αυτής της ενότητας απέτυχε" not in s and
                          "αρχικό περιεχόμενο αυτής της ενότητας της διαβούλευσης ήταν κενό" not in s]
        
        if not valid_summaries:
            cohesive_summary = "No valid individual summaries were available for the cohesive summary."
            stage1_logger.info("Skipping Stage 2 as no valid individual summaries were found.")
        else:
            stage1_logger.info(f"Found {len(valid_summaries)} valid summaries for Stage 2")
            concatenated_summaries = "\n\n---\n\n".join(valid_summaries)
            
            if dry_run:
                cohesive_summary = f"[Dry Run Cohesive Summary for consultation_id: {consultation_id}, based on {len(valid_summaries)} individual summaries]"
                stage1_logger.info("Dry run: Skipping actual Stage 2 summarization call.")
            else:
                if model and processor:
                    # Prepare Stage 2 prompt
                    stage2_full_prompt = f"{STAGE2_PROMPT_TEMPLATE}\n\n---\n{concatenated_summaries}"
                    
                    stage1_logger.info("Starting Stage 2 model.generate() for cohesive summary...")
                    cohesive_summary = summarize_text(
                        model=model,
                        processor=processor,
                        stage_id="2",
                        initial_llm_prompt_text=stage2_full_prompt,
                        core_input_data_for_correction=concatenated_summaries,
                        original_task_instructions_for_correction=STAGE2_PROMPT_TEMPLATE,
                        target_tokens_for_summary=1100,
                        retry_if_truncated=True
                    )
                    
                    if cohesive_summary is None:
                        cohesive_summary = "Failed to generate cohesive summary."
                        stage1_logger.warning("Stage 2 cohesive summary generation failed.")
                    else:
                        stage1_logger.info("Stage 2 cohesive summary generated successfully.")
                else:
                    cohesive_summary = "[Error: Model not loaded, cannot generate cohesive summary]"
                    stage1_logger.error("Model/processor not available for Stage 2 summarization.")

    stage1_logger.info(f"=== Stage 2 Complete ===")

    # === STAGE 3: Missing Information Detection and Final Summary Refinement ===
    stage1_logger.info(f"=== Starting Stage 3: Missing Information Detection and Final Summary Refinement for consultation_id: {consultation_id} ===")
    
    missing_info_notes = []
    stage3_cohesive_summary = cohesive_summary  # Default to Stage 2 summary if Stage 3 doesn't run
    
    # === STAGE 3.1: Missing Information Detection ===
    stage1_logger.info(f"=== Starting Stage 3.1: Missing Information Detection for consultation_id: {consultation_id} ===")
    
    # Check if we have a valid Stage 2 summary to work with
    is_stage2_summary_valid = (cohesive_summary and 
                               "No individual summaries" not in cohesive_summary and 
                               "No valid individual summaries" not in cohesive_summary and
                               "Error: Model not loaded" not in cohesive_summary and
                               "Dry Run Cohesive Summary" not in cohesive_summary and
                               "Failed to generate cohesive summary" not in cohesive_summary)
    
    if is_stage2_summary_valid and not dry_run:
        stage1_logger.info(f"Stage 2 summary is valid, proceeding with Stage 3.1 for {len(individual_article_details_for_report)} articles")
        
        for detail_entry in individual_article_details_for_report:
            article_id = detail_entry['db_article_id']
            chunk_index = detail_entry['chunk_index_within_db_article']
            chunk_title = detail_entry['chunk_title_line']
            original_text_chunk = detail_entry['original_text_chunk']
            stage1_summary = detail_entry.get('summary_model_actual', '')
            
            stage1_logger.info(f"Generating Stage 3.1 missing info note for Article ID: {article_id}, Chunk: {chunk_index}")
            
            # Skip if the original content or Stage 1 summary is empty/invalid
            if (not original_text_chunk or original_text_chunk.strip() == "" or
                not stage1_summary or 
                "Το περιεχόμενο αυτής της ενότητας ήταν κενό" in stage1_summary or
                "Η περίληψη αυτής της ενότητας απέτυχε" in stage1_summary or
                "αρχικό περιεχόμενο αυτής της ενότητας της διαβούλευσης ήταν κενό" in stage1_summary):
                stage1_logger.debug(f"Skipping Stage 3.1 for Article ID: {article_id}, Chunk: {chunk_index} due to empty/invalid content or summary")
                continue
                
            # Build Stage 3.1 prompt
            stage3_1_intro = (
                "Είσαι ένας βοηθός ανάλυσης κειμένων. Σου παρέχονται τρία κείμενα: ένα 'Αρχικό Άρθρο', η 'Περίληψη Άρθρου (Στάδιο 1)' γι' αυτό το άρθρο, "
                "και μια 'Συνολική Περίληψη (Στάδιο 2)' που συνοψίζει πολλά άρθρα, συμπεριλαμβανομένου αυτού.\n\n"
                "Ο σκοπός σου είναι να ελέγξεις αν υπάρχει κάποια σημαντική πληροφορία στο 'Αρχικό Άρθρο' που πιστεύεις ότι λείπει από την 'Συνολική Περίληψη (Στάδιο 2)'. "
                "Εστίασε σε βασικά σημεία, αλλαγές σε νόμους, θεσμούς, ή σημαντικές επιπτώσεις που αναφέρονται στο 'Αρχικό Άρθρο' αλλά δεν καλύπτονται επαρκώς στην 'Συνολική Περίληψη (Στάδιο 2)'.\n\n"
                "Αν εντοπίσεις τέτοια σημαντική πληροφορία που λείπει, διατύπωσε μια σύντομη σημείωση στα Ελληνικά. Η σημείωση πρέπει να είναι μία πρόταση και να μην υπερβαίνει τους 300 τόκενς. "
                "Αν δεν εντοπίσεις κάποια σημαντική παράλειψη, απάντησε ακριβώς: 'Δεν εντοπίστηκαν σημαντικές παραλείψεις σε σχέση με αυτό το άρθρο.'\n\n"
            )
            
            stage3_1_article_section = f"ΑΡΧΙΚΟ ΑΡΘΡΟ:\n--- ΑΡΧΗ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---\n{original_text_chunk}\n--- ΤΕΛΟΣ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---\n\n"
            stage3_1_summary1_section = f"ΠΕΡΙΛΗΨΗ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1):\n--- ΑΡΧΗ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---\n{stage1_summary}\n--- ΤΕΛΟΣ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---\n\n"
            stage3_1_summary2_section = f"ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):\n--- ΑΡΧΗ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---\n{cohesive_summary}\n--- ΤΕΛΟΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---\n\n"
            stage3_1_instruction_out = "Σημείωση σχετικά με πιθανές σημαντικές παραλείψεις (1 πρόταση, έως 300 τόκενς):"
            
            stage3_1_full_prompt = stage3_1_intro + stage3_1_article_section + stage3_1_summary1_section + stage3_1_summary2_section + stage3_1_instruction_out
            stage3_1_core_input = f"ΑΡΧΙΚΟ ΑΡΘΡΟ:\n{original_text_chunk}\n\nΠΕΡΙΛΗΨΗ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1):\n{stage1_summary}\n\nΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):\n{cohesive_summary}"
            
            note_text = summarize_text(
                model=model,
                processor=processor,
                stage_id="3.1",
                initial_llm_prompt_text=stage3_1_full_prompt,
                core_input_data_for_correction=stage3_1_core_input,
                original_task_instructions_for_correction=stage3_1_intro,
                target_tokens_for_summary=300,
                retry_if_truncated=True
            )
            
            if note_text is None:
                note_text = "Η διαδικασία δημιουργίας σημείωσης για παραλείψεις απέτυχε για αυτό το άρθρο."
                stage1_logger.warning(f"Stage 3.1 note generation failed for Article ID: {article_id}, Chunk: {chunk_index}")
            
            # Filter out empty or trivial notes
            if (note_text and note_text.strip() != "" and 
                "Δεν εντοπίστηκαν σημαντικές παραλείψεις σε σχέση με αυτό το άρθρο" not in note_text and
                "Το αρχικό περιεχόμενο του άρθρου ήταν κενό" not in note_text and
                "δεν ήταν διαθέσιμη ή έγκυρη" not in note_text and
                "απέτυχε για αυτό το άρθρο" not in note_text):
                missing_info_notes.append({
                    'db_article_id': article_id,
                    'chunk_index_within_db_article': chunk_index,
                    'chunk_title_line': chunk_title,
                    'stage1_summary': stage1_summary,
                    'note': note_text
                })
                stage1_logger.info(f"Added substantive note for Article ID: {article_id}, Chunk: {chunk_index}")
            else:
                stage1_logger.debug(f"Skipped trivial/empty note for Article ID: {article_id}, Chunk: {chunk_index}: '{note_text}'")
    
    elif dry_run:
        stage1_logger.info("Dry run: Skipping Stage 3.1 missing information detection")
        missing_info_notes = [{"note": f"[Dry Run Stage 3.1 Note for consultation_id: {consultation_id}]"}]
    else:
        stage1_logger.warning("Skipping Stage 3.1 as Stage 2 summary is missing or invalid")
    
    stage1_logger.info(f"=== Stage 3.1 Complete: Generated {len(missing_info_notes)} substantive missing information notes ===")
    
    # === STAGE 3.2: Final Summary Refinement ===
    stage1_logger.info(f"=== Starting Stage 3.2: Final Summary Refinement for consultation_id: {consultation_id} ===")
    
    if missing_info_notes and is_stage2_summary_valid and not dry_run:
        stage1_logger.info(f"Found {len(missing_info_notes)} substantive notes for Stage 3.2 refinement")
        
        # Build combined summaries and notes for Stage 3.2
        notes_for_refinement_input = []
        for note_info in missing_info_notes:
            article_id = note_info['db_article_id']
            chunk_index = note_info['chunk_index_within_db_article']
            chunk_title = note_info['chunk_title_line']
            stage1_summary = note_info['stage1_summary']
            note_text = note_info['note']
            
            notes_for_refinement_input.append(
                f"Περίληψη Άρθρου {article_id} (Chunk {chunk_index}) - '{chunk_title}' (Στάδιο 1):\n{stage1_summary}\n"
                f"Σημείωση για το Άρθρο {article_id} (Chunk {chunk_index}) (σχετικά με πιθανές παραλείψεις από την Συνολική Περίληψη Σταδίου 2):\n{note_text}\n---\n"
            )
        
        concatenated_summaries_and_notes = "\n".join(notes_for_refinement_input)
        
        # Build Stage 3.2 prompt
        stage3_2_intro = (
            "Είσαι ένας βοηθός συγγραφής και επιμέλειας κειμένων. Σου παρέχονται τα εξής:\n"
            "1. Μια 'Συνολική Περίληψη (Στάδιο 2)' μιας διαβούλευσης.\n"
            "2. Ένα σύνολο από 'Συνδυασμένες Περιλήψεις Άρθρων (Στάδιο 1) και Σημειώσεις'. Κάθε σημείωση υποδεικνύει πιθανές σημαντικές πληροφορίες από το αρχικό άρθρο που ενδέχεται να λείπουν ή να μην τονίζονται επαρκώς στην 'Συνολική Περίληψη (Στάδιο 2)'.\n\n"
            "Ο σκοπός σου είναι να αναθεωρήσεις την 'Συνολική Περίληψη (Στάδιο 2)' λαμβάνοντας υπόψη τις πληροφορίες και τις παρατηρήσεις που περιέχονται στις 'Συνδυασμένες Περιλήψεις Άρθρων (Στάδιο 1) και Σημειώσεις'. "
            "Η αναθεωρημένη περίληψη πρέπει να ενσωματώνει τα σημαντικά σημεία που επισημάνθηκαν, διατηρώντας τη συνοχή, την ακρίβεια και τη συντομία. Το τελικό κείμενο πρέπει να είναι στα Ελληνικά.\n\n"
        )
        
        stage3_2_summary2_section = f"ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):\n--- ΑΡΧΗ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---\n{cohesive_summary}\n--- ΤΕΛΟΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---\n\n"
        stage3_2_notes_section = f"ΣΥΝΔΥΑΣΜΕΝΕΣ ΠΕΡΙΛΗΨΕΙΣ ΑΡΘΡΩΝ (ΣΤΑΔΙΟ 1) ΚΑΙ ΣΗΜΕΙΩΣΕΙΣ:\n--- ΑΡΧΗ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---\n{concatenated_summaries_and_notes}\n--- ΤΕΛΟΣ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---\n\n"
        stage3_2_instruction_out = "ΠΑΡΑΚΑΛΩ ΠΑΡΕΧΕΤΕ ΤΗΝ ΑΝΑΘΕΩΡΗΜΕΝΗ ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ:"
        
        stage3_2_full_prompt = stage3_2_intro + stage3_2_summary2_section + stage3_2_notes_section + stage3_2_instruction_out
        stage3_2_core_input = f"ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):\n{cohesive_summary}\n\nΣΥΝΔΥΑΣΜΕΝΕΣ ΠΕΡΙΛΗΨΕΙΣ ΑΡΘΡΩΝ (ΣΤΑΔΙΟ 1) ΚΑΙ ΣΗΜΕΙΩΣΕΙΣ:\n{concatenated_summaries_and_notes}"
        
        stage1_logger.info("Starting Stage 3.2 model.generate() for refined final summary...")
        stage3_cohesive_summary = summarize_text(
            model=model,
            processor=processor,
            stage_id="3.2",
            initial_llm_prompt_text=stage3_2_full_prompt,
            core_input_data_for_correction=stage3_2_core_input,
            original_task_instructions_for_correction=stage3_2_intro,
            target_tokens_for_summary=1100,
            retry_if_truncated=True
        )
        
        if stage3_cohesive_summary is None:
            stage3_cohesive_summary = cohesive_summary  # Fall back to Stage 2 summary
            stage1_logger.warning("Stage 3.2 refinement failed. Using Stage 2 summary as final.")
        else:
            stage1_logger.info("Stage 3.2 refined final summary generated successfully.")
    
    elif dry_run:
        stage1_logger.info("Dry run: Skipping Stage 3.2 final summary refinement")
        stage3_cohesive_summary = f"[Dry Run Stage 3.2 Refined Summary for consultation_id: {consultation_id}, based on {len(missing_info_notes)} notes]"
    elif not missing_info_notes:
        stage1_logger.info("Skipping Stage 3.2 as no substantive missing information notes were generated in Stage 3.1")
        stage3_cohesive_summary = cohesive_summary
    else:
        stage1_logger.warning("Skipping Stage 3.2 as Stage 2 summary is missing or invalid")
        stage3_cohesive_summary = cohesive_summary
    
    stage1_logger.info(f"=== Stage 3.2 Complete ===")
    stage1_logger.info(f"=== Stage 3 Complete ===")

    # Generate CSV output for dry run
    if dry_run and dry_run_csv_data:
        csv_output_filename = os.path.join(SCRIPT_DIR, f"dry_run_consultation_{consultation_id}_stages1and2_{TIMESTAMP}.csv")
        try:
            with open(csv_output_filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'consultation_id', 'consultation_title', 'consultation_url',
                    'db_article_id', 'chunk_index_within_db_article', 
                    'chunk_article_number', 'chunk_title_line', 'word_count', 
                    'original_text_chunk', 'summary', 'original_content_excerpt'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for row_data in dry_run_csv_data:
                    row_data['consultation_title'] = consultation_title_for_dry_run
                    row_data['consultation_url'] = consultation_url_for_dry_run
                    writer.writerow(row_data)
            stage1_logger.info(f"Dry run CSV report generated: {csv_output_filename}")
        except IOError as e:
            stage1_logger.error(f"Error writing dry run CSV: {e}", exc_info=True)
    
    # Write Stage 2 summary to file
    if not dry_run:
        stage2_output_filename = os.path.join(SCRIPT_DIR, f"stage2_cohesive_summary_consultation_{consultation_id}_{TIMESTAMP}.txt")
        try:
            with open(stage2_output_filename, 'w', encoding='utf-8') as f:
                f.write(f"=== STAGE 2: COHESIVE SUMMARY FOR CONSULTATION {consultation_id} ===\n\n")
                f.write(f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Based on {len(all_individual_summaries_text)} individual summaries\n")
                f.write(f"Valid summaries used: {len([s for s in all_individual_summaries_text if s and 'Dry Run Summary' not in s and 'Error:' not in s and 'ήταν κενό' not in s and 'απέτυχε' not in s])}\n\n")
                f.write("COHESIVE SUMMARY:\n")
                f.write("=" * 50 + "\n")
                f.write(cohesive_summary)
                f.write("\n\n")
                f.write("=" * 50 + "\n")
                f.write("END OF COHESIVE SUMMARY\n")
            stage1_logger.info(f"Stage 2 cohesive summary written to: {stage2_output_filename}")
        except IOError as e:
            stage1_logger.error(f"Error writing Stage 2 summary to file: {e}", exc_info=True)

        # Write Stage 3 final summary and missing info notes to file
        stage3_output_filename = os.path.join(SCRIPT_DIR, f"stage3_final_summary_consultation_{consultation_id}_{TIMESTAMP}.txt")
        try:
            with open(stage3_output_filename, 'w', encoding='utf-8') as f:
                f.write(f"=== FINAL SUMMARY (STAGE 3.2) FOR CONSULTATION {consultation_id} ===\n\n")
                f.write(f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Based on Stage 2 summary + {len(missing_info_notes)} missing information notes\n\n")
                
                f.write("FINAL REFINED SUMMARY (Stage 3.2):\n")
                f.write("=" * 60 + "\n")
                f.write(stage3_cohesive_summary)
                f.write("\n\n")
                f.write("=" * 60 + "\n")
                f.write("END OF FINAL REFINED SUMMARY\n\n")
                
                if missing_info_notes:
                    f.write("=== MISSING INFORMATION NOTES (STAGE 3.1) ===\n\n")
                    for i, note_info in enumerate(missing_info_notes, 1):
                        f.write(f"Note {i}:\n")
                        f.write(f"  Article ID: {note_info['db_article_id']}\n")
                        f.write(f"  Chunk Index: {note_info['chunk_index_within_db_article']}\n")
                        f.write(f"  Chunk Title: {note_info['chunk_title_line']}\n")
                        f.write(f"  Missing Info Note: {note_info['note']}\n\n")
                        f.write(f"  Stage 1 Summary (for reference):\n")
                        f.write(f"  {note_info['stage1_summary']}\n")
                        f.write("-" * 40 + "\n\n")
                else:
                    f.write("=== NO MISSING INFORMATION NOTES GENERATED ===\n")
                    f.write("No substantive missing information was identified in Stage 3.1.\n\n")
                
                f.write("=== STAGE 2 SUMMARY (FOR COMPARISON) ===\n\n")
                f.write(cohesive_summary)
                f.write("\n\n")
                f.write("=" * 60 + "\n")
                f.write("END OF STAGE 2 SUMMARY\n")
                
            stage1_logger.info(f"Stage 3 final summary and notes written to: {stage3_output_filename}")
        except IOError as e:
            stage1_logger.error(f"Error writing Stage 3 summary to file: {e}", exc_info=True)

    stage1_logger.info(f"Finished consultation summarization for consultation_id: {consultation_id}. Produced {len(all_individual_summaries_text)} individual summaries and 1 cohesive summary.")
    
    return individual_article_details_for_report, stage3_cohesive_summary

def main():
    cli = argparse.ArgumentParser(description="Orchestrate summarization for a given consultation.")
    cli.add_argument("--consultation_id", type=int, required=True, help="ID of the consultation to process.")
    cli.add_argument("--article_db_id", type=int, default=None, help="Optional: Specific DB article ID to process within the consultation.")
    cli.add_argument("--dry_run", action='store_true', help="Perform a dry run: process data, log, generate CSV, but don't call external model.")
    cli.add_argument("--debug", action='store_true', help="Enable debug level logging to console for Stage 1.")
    args = cli.parse_args()

    if args.debug:
        # Add console handler to the logger if in debug mode for immediate feedback
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - Func: %(funcName)s - Line: %(lineno)d - %(message)s')
        console_handler.setFormatter(formatter)
        # Check if handlers are already present to avoid duplicates if main() is called multiple times (e.g. in tests)
        if not any(isinstance(h, logging.StreamHandler) for h in stage1_logger.handlers):
            stage1_logger.addHandler(console_handler)
            stage1_logger.info("DEBUG mode enabled: Logging Stage 1 Reasoning Trace to console.")

    stage1_logger.info(f"Script started with args: {args}")

    start_time = datetime.datetime.now()
    results = run_consultation_summarization(args.consultation_id, article_db_id_to_process=args.article_db_id, dry_run=args.dry_run)
    end_time = datetime.datetime.now()
    elapsed_time = (end_time - start_time).total_seconds()

    stage1_logger.info(f"Script finished after {elapsed_time:.2f} seconds.")

    if args.debug:
        stage1_logger.info(f"Processing completed. Result preview (first item from list of detailed reports):")
        # results is a tuple: (list_of_detailed_reports, concatenated_summary_string)
        # results[0] is individual_article_details_for_report (the list)
        # results[1] is final_concatenated_summaries (the string)
        if results and results[0]: # Check if results tuple exists and its first element (the list) is not empty
            first_detailed_report_list = results[0]
            stage1_logger.info(f"Type of results[0] (list of detailed reports): {type(first_detailed_report_list)}")
            
            if isinstance(first_detailed_report_list, list) and first_detailed_report_list:
                first_detail_item = first_detailed_report_list[0] # This is the first dictionary in the list
                stage1_logger.info(f"Type of the first item in the detailed report list (results[0][0]): {type(first_detail_item)}")
                
                if isinstance(first_detail_item, dict):
                    stage1_logger.info(f"Keys in the first detail item (results[0][0]): {list(first_detail_item.keys())}")
                    
                    summary_key_to_check = 'summary' if args.dry_run else 'summary_model_actual'
                    if summary_key_to_check in first_detail_item:
                        summary_preview = str(first_detail_item[summary_key_to_check])
                        if len(summary_preview) > 150:
                            summary_preview = summary_preview[:150] + "..."
                        stage1_logger.info(f"Preview of '{summary_key_to_check}' for first detail item: {summary_preview}")
                    else:
                        stage1_logger.info(f"'{summary_key_to_check}' key not found in the first detail item.")
                else:
                    stage1_logger.info("The first item in the detailed report list (results[0][0]) is not a dictionary.")
            else:
                stage1_logger.info("The list of detailed reports (results[0]) is empty or not a list.")
        else:
            stage1_logger.info("No results returned from run_consultation_summarization, or the list of detailed reports is empty.")

if __name__ == "__main__":
    main() 