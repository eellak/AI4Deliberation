# Suggested command to install dependencies:
# pip install accelerate transformers torch sqlite3

import torch
from transformers import AutoProcessor, Gemma3ForConditionalGeneration
import sqlite3
import logging
import os

# --- Contextual Formatter Definition ---
class ContextualFormatter(logging.Formatter):
    def format(self, record):
        # Ensure all custom keys have a default value if not provided in 'extra'
        default_extra_keys = {
            'stage_id': 'N/A',
            'call_type': 'N/A',
            'prompt_text': 'N/A',
            'target_tokens': 'N/A',
            'raw_output': 'N/A',
            'completeness': 'N/A',
            'final_output': 'N/A'
        }
        for key, value in default_extra_keys.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return super().format(record)

# --- Configure Main Logger (for console output) ---
main_logger = logging.getLogger("main_script")
main_logger.setLevel(logging.INFO)
main_console_handler = logging.StreamHandler()
main_console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
main_console_handler.setFormatter(main_console_formatter)
main_logger.addHandler(main_console_handler)
main_logger.propagate = False

# --- Configure Reasoning Trace Logger (for file output) ---
trace_logger = logging.getLogger("reasoning_trace")
trace_logger.setLevel(logging.DEBUG)
trace_file_handler = logging.FileHandler("reasoning_trace.log", mode='w')
trace_file_formatter = ContextualFormatter(
    '%(asctime)s - %(levelname)s - STAGE: %(stage_id)s - TYPE: %(call_type)s\n'
    'PROMPT:\n%(prompt_text)s\n'
    'TARGET_TOKENS: %(target_tokens)s\n'
    'RAW_OUTPUT:\n%(raw_output)s\n'
    'COMPLETENESS_CHECK: %(completeness)s\n'
    'FINAL_RETURNED_OUTPUT:\n%(final_output)s\n'
    '-------------------------------------\n'
)
trace_file_handler.setFormatter(trace_file_formatter)
trace_logger.addHandler(trace_file_handler)
trace_logger.propagate = False

# --- Model Configuration ---
MODEL_ID = "google/gemma-3-4b-it"

# --- Database Configuration ---
DB_PATH = "/mnt/data/AI4Deliberation/deliberation_data_gr_updated_better_extraction.db"
TABLE_NAME = "articles"
TEXT_COLUMN_NAME = "content"

def load_model_and_processor():
    """Loads the Gemma model and processor."""
    main_logger.info(f"Loading model: {MODEL_ID}")
    try:
        model = Gemma3ForConditionalGeneration.from_pretrained(
            MODEL_ID,
            device_map="auto",
            torch_dtype=torch.bfloat16,
            # attn_implementation="sdpa" # Recommended if issues persist with default
        ).eval()
        processor = AutoProcessor.from_pretrained(MODEL_ID)
        main_logger.info("Model and processor loaded successfully.")
        return model, processor
    except Exception as e:
        main_logger.error(f"Error loading model or processor: {e}")
        raise

def fetch_target_consultation_id(db_path, articles_table_name, content_column_name):
    """Fetches the consultation_id from the first available article with content."""
    consultation_id = None
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        query = (f"SELECT consultation_id FROM {articles_table_name} "
                 f"WHERE {content_column_name} IS NOT NULL AND {content_column_name} != '' LIMIT 1")
        main_logger.info(f"Executing query to find a target consultation_id: {query}")
        cursor.execute(query)
        row = cursor.fetchone()
        if row:
            consultation_id = row[0]
            main_logger.info(f"Found target consultation_id: {consultation_id}")
        else:
            main_logger.warning("No suitable article found to determine a consultation_id.")
    except sqlite3.Error as e:
        main_logger.error(f"Database error while fetching consultation_id: {e}")
    except Exception as e:
        main_logger.error(f"An unexpected error occurred while fetching consultation_id: {e}")
    finally:
        if conn:
            conn.close()
    return consultation_id

def fetch_articles_for_consultation(db_path, articles_table_name, content_column_name, consultation_id):
    """Fetches all article IDs and contents for a given consultation_id."""
    articles_data = []
    if consultation_id is None:
        main_logger.warning("Cannot fetch articles without a consultation_id.")
        return articles_data
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        query = (f"SELECT id, {content_column_name} FROM {articles_table_name} "
                 f"WHERE consultation_id = ? AND {content_column_name} IS NOT NULL AND {content_column_name} != ''")
        main_logger.info(f"Executing query to fetch articles for consultation_id {consultation_id}: {query}")
        cursor.execute(query, (consultation_id,))
        rows = cursor.fetchall()
        for row in rows:
            articles_data.append({'id': row[0], 'content': row[1]})
        main_logger.info(f"Fetched {len(articles_data)} articles for consultation_id {consultation_id}.")
    except sqlite3.Error as e:
        main_logger.error(f"Database error while fetching articles for consultation {consultation_id}: {e}")
    except Exception as e:
        main_logger.error(f"An unexpected error occurred while fetching articles for consultation {consultation_id}: {e}")
    finally:
        if conn:
            conn.close()
    return articles_data

def get_token_count(text, processor):
    if not text or not isinstance(text, str) or text.strip() == "":
        return 0
    try:
        inputs = processor.tokenizer(text, return_tensors=None, add_special_tokens=True)
        return len(inputs["input_ids"])
    except Exception as e:
        main_logger.error(f"Error tokenizing text for count: {e}")
        return 0

def check_response_completeness(response_text):
    if not response_text:
        return False
    end_punctuation = ['.', '?', '!', '."', '?"', '!"', '.»', '?»', '!»']
    return any(response_text.strip().endswith(punct) for punct in end_punctuation)

def summarize_text(model, processor, stage_id: str, initial_llm_prompt_text: str,
                   core_input_data_for_correction: str, original_task_instructions_for_correction: str,
                   target_tokens_for_summary: int, language_code="el", retry_if_truncated=True):
    final_returned_value_for_log = ""
    if not initial_llm_prompt_text or not isinstance(initial_llm_prompt_text, str) or initial_llm_prompt_text.strip() == "":
        main_logger.warning(f"[Stage {stage_id}] Skipping summarization due to empty or invalid initial_llm_prompt_text.")
        final_returned_value_for_log = "Skipped due to empty/invalid prompt."
        trace_logger.debug("Skipping summarization call.", extra={'stage_id': stage_id, 'call_type': 'N/A', 'prompt_text': initial_llm_prompt_text if initial_llm_prompt_text else "EMPTY_PROMPT", 'target_tokens': target_tokens_for_summary, 'raw_output': 'N/A', 'completeness': 'N/A', 'final_output': final_returned_value_for_log})
        return None

    default_system_prompt_text = "You are a helpful assistant specialized in summarizing texts concisely."
    messages = [{"role": "system", "content": [{"type": "text", "text": default_system_prompt_text}]}, {"role": "user", "content": [{"type": "text", "text": initial_llm_prompt_text}]}]

    try:
        trace_logger.debug("Attempting initial LLM call.", extra={'stage_id': stage_id, 'call_type': 'Initial', 'prompt_text': initial_llm_prompt_text, 'target_tokens': target_tokens_for_summary, 'raw_output': 'PENDING_LLM_CALL', 'completeness': 'PENDING_LLM_CALL', 'final_output': 'PENDING_LLM_CALL'})
        inputs = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[-1]
        with torch.inference_mode():
            generation = model.generate(**inputs, max_new_tokens=target_tokens_for_summary, do_sample=False) # Not using top_p, top_k
            generation = generation[0][input_len:]
        decoded_summary = processor.decode(generation, skip_special_tokens=True)
        is_complete_initial = check_response_completeness(decoded_summary)
        trace_logger.debug("Initial LLM call completed.", extra={'stage_id': stage_id, 'call_type': 'Initial', 'prompt_text': initial_llm_prompt_text, 'target_tokens': target_tokens_for_summary, 'raw_output': decoded_summary, 'completeness': str(is_complete_initial), 'final_output': 'PENDING_FURTHER_PROCESSING'})

        if retry_if_truncated and not is_complete_initial:
            main_logger.warning(f"[Stage {stage_id}] Generated response appears to be truncated: '{decoded_summary[-50:]}...'")
            specific_constraints_for_stage = ""
            if stage_id == "1":
                specific_constraints_for_stage = ("- Η περίληψη πρέπει να είναι έως 2-3 προτάσεις το μέγιστο.\n"
                                                  "- Πρέπει να περιλαμβάνει τις βασικές αλλαγές σε νόμους, θεσμούς, ή διαδικασίες που αναφέρονται στο άρθρο.")
            elif stage_id == "2": # FIX 4: Updated constraints for Stage 2
                specific_constraints_for_stage = (
                    "- Η συνολική περίληψη πρέπει να αποτυπώνει τα κύρια σημεία και τον "
                    "ευρύτερο στόχο του νομοσχεδίου.\n"
                    "- Πρέπει να περιορίζεται σε περίπου 300 λέξεις και 6 " # Changed words & paragraphs
                    "παραγράφους το μέγιστο.\n" # Corrected typo from "παραγράφουςπαραγράφους"
                    "- Πρέπει να διατηρεί τη συνοχή και την περιεκτικότητα.\n"
                    "- Πρέπει να είναι κατανοητή σε πολίτες χωρίς εξειδικευμένες "
                    "νομικές γνώσεις."
                )
            elif stage_id == "3.1":
                specific_constraints_for_stage = ("- Η σημείωση πρέπει να εστιάζει μόνο στην πιο σημαντική πληροφορία που λείπει από την Αρχική Συνολική Περίληψη (Στάδιο 2) σε σχέση με το συγκεκριμένο άρθρο.\n"
                                                  "- Πρέπει να είναι μία μόνο πρόταση, έως 150-200 τόκενς.")
            elif stage_id == "3.2":
                specific_constraints_for_stage = ("- Η τελική περίληψη πρέπει να ενσωματώνει τα σημαντικότερα σημεία που επισημάνθηκαν στις σημειώσεις.\n"
                                                  "- Πρέπει να διατηρεί τη συνοχή, την ακρίβεια και τη συντομία.\n"
                                                  "- Πρέπει να περιορίζεται σε περίπου 300 λέξεις και 6 παραγράφους το μέγιστο.\n" # Matching Stage 2 output style
                                                  "- Πρέπει να είναι κατανοητή σε πολίτες χωρίς εξειδικευμένες νομικές γνώσεις.")

            correction_prompt_header = ("Η παρακάτω απόκριση που παρήγαγες κόπηκε επειδή πιθανόν ξεπέρασες το όριο των επιτρεπτών χαρακτήρων (tokens):\n\n"
                                        "--- ΑΡΧΗ ΑΠΟΚΟΜΜΕΝΗΣ ΑΠΟΚΡΙΣΗΣ ---\n")
            correction_prompt_instructions_header = ("\n--- ΤΕΛΟΣ ΑΠΟΚΟΜΜΕΝΗΣ ΑΠΟΚΡΙΣΗΣ ---\n\n"
                                                     "Για να δημιουργήσεις αυτή την απόκριση, σου δόθηκαν οι παρακάτω οδηγίες και δεδομένα εισόδου:\n\n"
                                                     "--- ΑΡΧΙΚΕΣ ΟΔΗΓΙΕΣ ΕΡΓΑΣΙΑΣ ---\n")
            correction_prompt_input_data_header = ("\n--- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΟΔΗΓΙΩΝ ΕΡΓΑΣΙΑΣ ---\n\n"
                                                   "--- ΑΡΧΙΚΑ ΔΕΔΟΜΕΝΑ ΕΙΣΟΔΟΥ ---\n")
            correction_prompt_footer = ("\n--- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΔΕΔΟΜΕΝΩΝ ΕΙΣΟΔΟΥ ---\n\n"
                                        "ΠΑΡΑΚΑΛΩ ΔΗΜΙΟΥΡΓΗΣΕ ΜΙΑ ΝΕΑ, ΣΥΝΤΟΜΟΤΕΡΗ ΕΚΔΟΧΗ:\n"
                                        "Μελέτησε προσεκτικά την αποκομμένη απόκριση, τις αρχικές οδηγίες και τα αρχικά δεδομένα.\n"
                                        "Η νέα σου απόκριση πρέπει:\n"
                                        "- Να είναι σημαντικά συντομότερη από την προηγούμενη προσπάθεια.\n"
                                        "- Να διατηρεί τα πιο κρίσιμα σημεία σε σχέση με τις αρχικές οδηγίες.\n"
                                        "- Να ολοκληρώνεται σωστά με κατάλληλο σημείο στίξης (π.χ., τελεία).\n")
            correction_prompt_final_instruction = ("\nΠαρακαλώ γράψε μόνο τη νέα, διορθωμένη απόκριση.")
            correction_prompt = (f"{correction_prompt_header}{decoded_summary}"
                                 f"{correction_prompt_instructions_header}{original_task_instructions_for_correction}"
                                 f"{correction_prompt_input_data_header}{core_input_data_for_correction}"
                                 f"{correction_prompt_footer}{specific_constraints_for_stage}"
                                 f"{correction_prompt_final_instruction}")
            retry_system_prompt_text = ("Είσαι ένας εξυπηρετικός βοηθός. Η προηγούμενη απόκρισή σου ήταν ατελής (αποκομμένη). "
                                        "Παρακαλώ διόρθωσέ την ακολουθώντας τις νέες οδηγίες για συντομότερη απάντηση και λαμβάνοντας υπόψη το παρεχόμενο πλαίσιο.")
            retry_messages = [{"role": "system", "content": [{"type": "text", "text": retry_system_prompt_text}]}, {"role": "user", "content": [{"type": "text", "text": correction_prompt}]}]
            
            # FIX 2: Use target_tokens_for_summary for retry generation, prompt already asks for shorter.
            trace_logger.debug("Attempting truncation correction retry LLM call.", extra={'stage_id': stage_id, 'call_type': 'Truncation Correction Retry', 'prompt_text': correction_prompt, 'target_tokens': target_tokens_for_summary, 'raw_output': 'PENDING_LLM_CALL', 'completeness': 'PENDING_LLM_CALL', 'final_output': 'PENDING_LLM_CALL'})
            retry_inputs = processor.apply_chat_template(retry_messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
            retry_input_len = retry_inputs["input_ids"].shape[-1]
            with torch.inference_mode():
                retry_generation = model.generate(**retry_inputs, max_new_tokens=target_tokens_for_summary, do_sample=False) # Use original target_tokens
                retry_generation = retry_generation[0][retry_input_len:]
            retry_summary = processor.decode(retry_generation, skip_special_tokens=True)
            is_complete_retry = check_response_completeness(retry_summary)
            trace_logger.debug("Truncation correction retry LLM call completed.", extra={'stage_id': stage_id, 'call_type': 'Truncation Correction Retry', 'prompt_text': correction_prompt, 'target_tokens': target_tokens_for_summary, 'raw_output': retry_summary, 'completeness': str(is_complete_retry), 'final_output': 'PENDING_FURTHER_PROCESSING'})

            if is_complete_retry:
                main_logger.info(f"[Stage {stage_id}] Retry successful, got a complete response.")
                final_returned_value_for_log = (retry_summary + "\n[Σημείωση: Αυτή η απόκριση ενδέχεται να έχει συντομευτεί αυτόματα λόγω προηγούμενης αποκοπής.]")
                trace_logger.debug("Finalizing after successful retry.", extra={'stage_id': stage_id, 'call_type': 'Truncation Correction Retry', 'prompt_text': 'N/A (Refer to retry call prompt)', 'target_tokens': 'N/A', 'raw_output': retry_summary, 'completeness': str(is_complete_retry), 'final_output': final_returned_value_for_log})
                return final_returned_value_for_log
            else:
                main_logger.warning(f"[Stage {stage_id}] Even the retry attempt resulted in a truncated response.")
                final_returned_value_for_log = (decoded_summary + "\n[Σημείωση: Η παραπάνω απόκριση εντοπίστηκε ως πιθανώς ατελής (αποκομμένη) από τον αυτόματο έλεγχο, καθώς δεν ολοκληρώθηκε με κατάλληλο σημείο στίξης.]")
                trace_logger.debug("Finalizing after failed retry.", extra={'stage_id': stage_id, 'call_type': 'Truncation Correction Retry', 'prompt_text': 'N/A (Refer to retry call prompt)', 'target_tokens': 'N/A', 'raw_output': decoded_summary, 'completeness': str(is_complete_initial), 'final_output': final_returned_value_for_log})
                return final_returned_value_for_log
        else:
            final_returned_value_for_log = decoded_summary
            trace_logger.debug("Finalizing after successful initial call (no retry needed).", extra={'stage_id': stage_id, 'call_type': 'Initial', 'prompt_text': 'N/A (Refer to initial call prompt)', 'target_tokens': 'N/A', 'raw_output': decoded_summary, 'completeness': str(is_complete_initial), 'final_output': final_returned_value_for_log})
            return final_returned_value_for_log
    except Exception as e:
        main_logger.error(f"[Stage {stage_id}] Error during summarization: {e}", exc_info=True) # Added exc_info
        final_returned_value_for_log = f"Error during summarization: {e}"
        trace_logger.error("Exception during summarization process.", extra={'stage_id': stage_id, 'call_type': 'N/A (Exception)', 'prompt_text': initial_llm_prompt_text if 'initial_llm_prompt_text' in locals() else 'PROMPT_UNKNOWN_DUE_TO_ERROR', 'target_tokens': target_tokens_for_summary if 'target_tokens_for_summary' in locals() else 'N/A', 'raw_output': 'N/A', 'completeness': 'N/A', 'final_output': final_returned_value_for_log}, exc_info=True)
        return None

def main():
    # FIX: Setting TORCHDYNAMO_DISABLE=1 if it was found to be a solution
    # This should be done before importing torch if possible, or as an environment variable when running the script.
    # For example: TORCHDYNAMO_DISABLE=1 python your_script.py
    # If you need to set it in code (less ideal for Dynamo, but for other env vars):
    # os.environ['TORCHDYNAMO_DISABLE'] = '1'
    main_logger.info("Starting summarization task...")
    main_logger.info("Relying on huggingface-cli login or HF_TOKEN environment variable for authentication.")

    model, processor = load_model_and_processor()
    if model is None or processor is None:
        main_logger.error("Failed to load model and processor. Exiting.")
        return

    target_consultation_id = fetch_target_consultation_id(DB_PATH, TABLE_NAME, TEXT_COLUMN_NAME)
    if not target_consultation_id:
        main_logger.warning("No target consultation_id found. Exiting.")
        return

    articles_data = fetch_articles_for_consultation(DB_PATH, TABLE_NAME, TEXT_COLUMN_NAME, target_consultation_id)
    if not articles_data:
        main_logger.warning(f"No articles found for consultation_id {target_consultation_id}. Exiting.")
        return

    individual_article_details = []
    all_individual_summaries_text = []

    main_logger.info(f"--- Stage 1: Summarizing {len(articles_data)} individual articles for consultation_id {target_consultation_id} ---")
    for article in articles_data:
        article_id, article_content = article['id'], article['content']
        original_token_length = get_token_count(article_content, processor)
        stage1_target_summary_tokens = 300
        stage1_task_instructions_el = ("Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω άρθρου στα Ελληνικά, σε απλή γλώσσα, "
                                       "κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως 3 προτάσεις.\n"
                                       "Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες.\n"
                                       "Οι περιλήψεις πρέπει να είναι όσο πιο σύντομες γίνεται, διατηρώντας την ουσία του κειμένου και να μην είναι παραπάνω απο 3 προτάσεις σε μήκος.\n"
                                       "Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης, μη βάζεις εισαγωγή στη περίψη απλώς γράψε την:")
        current_core_input_s1 = article_content
        current_initial_prompt_s1 = f"{stage1_task_instructions_el}\n\n{current_core_input_s1}"
        individual_summary, generated_summary_token_length = ("Το αρχικό περιεχόμενο του άρθρου ήταν κενό ή μη έγκυρο.", 0) if original_token_length == 0 else (None, 0)
        if original_token_length > 0:
            main_logger.info(f"Summarizing Article ID: {article_id} (Original tokens: {original_token_length}, Target max_new_tokens: {stage1_target_summary_tokens})")
            individual_summary = summarize_text(model, processor, stage_id="1", initial_llm_prompt_text=current_initial_prompt_s1, core_input_data_for_correction=current_core_input_s1, original_task_instructions_for_correction=stage1_task_instructions_el, target_tokens_for_summary=stage1_target_summary_tokens, language_code="el")
            generated_summary_token_length = get_token_count(individual_summary, processor) if individual_summary else 0
            main_logger.info(f"Article ID: {article_id} - Generated summary token length: {generated_summary_token_length}")
        if not individual_summary: # Covers both empty original and failed summarization
            individual_summary = "Failed to generate summary for this article." if original_token_length > 0 else individual_summary
            main_logger.warning(f"Summary generation failed or skipped for Article ID: {article_id}")
        individual_article_details.append({'id': article_id, 'content': article_content, 'original_token_length': original_token_length, 'target_summary_tokens': stage1_target_summary_tokens, 'summary': individual_summary, 'generated_summary_token_length': generated_summary_token_length})
        all_individual_summaries_text.append(individual_summary)
    main_logger.info("--- Stage 1 Complete. ---")

    # FIX 3: Rename final_cohesive_summary to initial_cohesive_summary_s2
    initial_cohesive_summary_s2 = ""
    generated_initial_summary_s2_tokens = 0 # Initialize
    main_logger.info("--- Stage 2: Generating Initial Cohesive Summary (ΑΡΧΙΚΗ) ---") # FIX 3: Naming
    if all_individual_summaries_text:
        valid_summaries = [s for s in all_individual_summaries_text if s and "Failed to generate" not in s and " ήταν κενό" not in s]
        if valid_summaries:
            concatenated_summaries = "\n\n---\n\n".join(valid_summaries)
            stage2_task_instructions_el = ("Οι παρακάτω είναι ατομικές περιλήψεις πολλαπλών άρθρων από μία ενιαία διαβούλευση. "
                                           "Παρακαλώ συνδυάστε τις σε ένα ενιαίο, συνεκτικό και περιεκτικό κείμενο στα Ελληνικά που αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου. "
                                           "Στοχεύστε σε μια περιεκτική επισκόπηση περίπου 300 λέξεων και 6 παραγράφων.") # Matched constraints in summarize_text
            current_core_input_s2 = concatenated_summaries
            current_initial_prompt_s2 = f"{stage2_task_instructions_el}\n\n---\n{current_core_input_s2}"
            stage2_target_tokens = 1100 # FIX 1: Token limit for Stage 2
            initial_cohesive_summary_s2 = summarize_text(model, processor, stage_id="2", initial_llm_prompt_text=current_initial_prompt_s2, core_input_data_for_correction=current_core_input_s2, original_task_instructions_for_correction=stage2_task_instructions_el, target_tokens_for_summary=stage2_target_tokens, language_code="el")
            generated_initial_summary_s2_tokens = get_token_count(initial_cohesive_summary_s2, processor) if initial_cohesive_summary_s2 else 0
            main_logger.info(f"Stage 2: Initial Cohesive Summary (ΑΡΧΙΚΗ) generated. Token length: {generated_initial_summary_s2_tokens}")
            if not initial_cohesive_summary_s2:
                initial_cohesive_summary_s2 = "Failed to generate an initial cohesive summary."
                main_logger.warning("Generation of Initial Cohesive Summary (ΑΡΧΙΚΗ) failed.")
        else:
            initial_cohesive_summary_s2 = "No valid individual summaries were available for the Initial Cohesive Summary (ΑΡΧΙΚΗ)."
            main_logger.info("Skipping Stage 2 as no valid individual summaries were found.")
    else:
        initial_cohesive_summary_s2 = "No individual summaries were generated to combine."
        main_logger.info("Skipping Stage 2 as no individual summaries were generated.")
    main_logger.info("--- Stage 2 Complete. ---")

    missing_info_notes = []
    main_logger.info(f"--- Stage 3.1: Identifying missing important information from Initial Cohesive Summary (ΑΡΧΙΚΗ) for consultation_id {target_consultation_id} ---")
    is_stage_2_summary_valid = initial_cohesive_summary_s2 and not any(indicator in initial_cohesive_summary_s2 for indicator in ["Failed to generate", "No valid individual summaries", "No individual summaries were generated"])
    if is_stage_2_summary_valid:
        for article_detail in individual_article_details:
            article_id, original_article_content, stage1_summary, original_article_token_length = article_detail['id'], article_detail['content'], article_detail['summary'], article_detail['original_token_length']
            is_stage1_summary_valid = stage1_summary and "Failed to generate" not in stage1_summary and " ήταν κενό" not in stage1_summary
            note_text = ""
            if not original_article_content or original_article_content.strip() == "":
                note_text = "Το αρχικό περιεχόμενο του άρθρου ήταν κενό, δεν είναι δυνατή η δημιουργία σημείωσης."
            elif not is_stage1_summary_valid:
                note_text = "Η αρχική περίληψη του άρθρου (Στάδιο 1) δεν ήταν διαθέσιμη ή έγκυρη."
            else:
                main_logger.info(f"Generating missing information note for Article ID: {article_id}")
                s3_1_intro = ("Είσαι ένας βοηθός ανάλυσης κειμένων. Σου παρέχονται τρία κείμενα: ένα 'Αρχικό Άρθρο', η 'Περίληψη Άρθρου (Στάδιο 1)' γι' αυτό το άρθρο, "
                              "και μια '**Αρχική** Συνολική Περίληψη (Στάδιο 2)' που συνοψίζει πολλά άρθρα, συμπεριλαμβανομένου αυτού.\n\n" # FIX 3
                              "Ο σκοπός σου είναι να ελέγξεις αν υπάρχει κάποια σημαντική πληροφορία στο 'Αρχικό Άρθρο' που πιστεύεις ότι λείπει από την '**Αρχική** Συνολική Περίληψη (Στάδιο 2)'. " # FIX 3
                              "Εστίασε σε βασικά σημεία, αλλαγές σε νόμους, θεσμούς, ή σημαντικές επιπτώσεις που αναφέρονται στο 'Αρχικό Άρθρο' αλλά δεν καλύπτονται επαρκώς στην '**Αρχική** Συνολική Περίληψη (Στάδιο 2)'.\n\n" # FIX 3
                              "Αν εντοπίσεις τέτοια σημαντική πληροφορία που λείπει, διατύπωσε μια σύντομη σημείωση στα Ελληνικά. Η σημείωση πρέπει να είναι μία πρόταση και να μην υπερβαίνει τους 300 τόκενς. "
                              "Αν δεν εντοπίσεις κάποια σημαντική παράλειψη, απάντησε ακριβώς: 'Δεν εντοπίστηκαν σημαντικές παραλείψεις σε σχέση με αυτό το άρθρο.'\n\n")
                s3_1_article_section = ("ΑΡΧΙΚΟ ΑΡΘΡΟ:\n--- ΑΡΧΗ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---\n{original_article_content_placeholder}\n--- ΤΕΛΟΣ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---\n\n")
                s3_1_summary1_section = ("ΠΕΡΙΛΗΨΗ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1):\n--- ΑΡΧΗ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---\n{stage1_summary_placeholder}\n--- ΤΕΛΟΣ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---\n\n")
                s3_1_summary2_section = ("**ΑΡΧΙΚΗ** ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):\n--- ΑΡΧΗ **ΑΡΧΙΚΗΣ** ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---\n{initial_cohesive_summary_s2_placeholder}\n--- ΤΕΛΟΣ **ΑΡΧΙΚΗΣ** ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---\n\n") # FIX 3
                s3_1_instruction_out = ("Σημείωση σχετικά με πιθανές σημαντικές παραλείψεις (1 πρόταση, έως 300 τόκενς):")
                stage3_1_task_instructions_template_el = (s3_1_intro + s3_1_article_section + s3_1_summary1_section + s3_1_summary2_section + s3_1_instruction_out)
                current_initial_prompt_s3_1 = stage3_1_task_instructions_template_el.format(original_article_content_placeholder=original_article_content, stage1_summary_placeholder=stage1_summary, initial_cohesive_summary_s2_placeholder=initial_cohesive_summary_s2)
                current_core_input_s3_1 = (f"ΑΡΧΙΚΟ ΑΡΘΡΟ:\n{original_article_content}\n\nΠΕΡΙΛΗΨΗ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1):\n{stage1_summary}\n\n**ΑΡΧΙΚΗ** ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):\n{initial_cohesive_summary_s2}") # FIX 3
                original_task_instructions_for_correction_s3_1 = stage3_1_task_instructions_template_el
                note_text = summarize_text(model, processor, stage_id="3.1", initial_llm_prompt_text=current_initial_prompt_s3_1, core_input_data_for_correction=current_core_input_s3_1, original_task_instructions_for_correction=original_task_instructions_for_correction_s3_1, target_tokens_for_summary=300, language_code="el")
                if not note_text:
                    note_text = "Η διαδικασία δημιουργίας σημείωσης για παραλείψεις απέτυχε για αυτό το άρθρο."
            main_logger.info(f"Article ID: {article_id} - Missing Info Note: {note_text[:200]}...")
            if (note_text and note_text.strip() != "" and "Δεν εντοπίστηκαν σημαντικές παραλείψεις σε σχέση με αυτό το άρθρο" not in note_text and "Το αρχικό περιεχόμενο του άρθρου ήταν κενό" not in note_text and "δεν ήταν διαθέσιμη ή έγκυρη" not in note_text):
                missing_info_notes.append({'article_id': article_id, 'note': note_text})
                main_logger.info(f"Added note for article {article_id} as it contains substantive feedback")
            else: main_logger.info(f"Skipped adding note for article {article_id} as it was trivial or an error placeholder.")
    else: main_logger.warning("Skipping Stage 3.1 as the Initial Cohesive Summary (ΑΡΧΙΚΗ) is missing or invalid.")
    main_logger.info("--- Stage 3.1 Complete. ---")

    # FIX 3: Rename refined_final_summary to final_summary_s3_2
    final_summary_s3_2 = initial_cohesive_summary_s2 # Default to initial if refinement cannot occur
    generated_final_summary_s3_2_tokens = 0 # Initialize
    main_logger.info(f"--- Stage 3.2: Refining to Final Cohesive Summary (ΤΕΛΙΚΗ) for consultation_id {target_consultation_id} ---") # FIX 3: Naming
    notes_for_refinement_input = []
    if missing_info_notes:
        for article_detail in individual_article_details:
            article_id, stage1_summary = article_detail['id'], article_detail['summary']
            note_detail = next((n for n in missing_info_notes if n['article_id'] == article_id), None)
            current_note = "(Καμία σημείωση για αυτό το άρθρο.)" # FIX 5: Briefer message
            if note_detail and note_detail['note']: current_note = note_detail['note']
            is_stage1_summary_valid_for_refinement = stage1_summary and "Failed to generate" not in stage1_summary and " ήταν κενό" not in stage1_summary
            if is_stage1_summary_valid_for_refinement: notes_for_refinement_input.append(f"Περίληψη Άρθρου {article_id} (Στάδιο 1):\n{stage1_summary}\nΣημείωση για το Άρθρο {article_id} (σχετικά με πιθανές παραλείψεις από την Αρχική Περίληψη Σταδίου 2):\n{current_note}\n---\n")
        if notes_for_refinement_input and is_stage_2_summary_valid:
            concatenated_summaries_and_notes = "\n".join(notes_for_refinement_input)
            s3_2_intro = ("Είσαι ένας βοηθός συγγραφής και επιμέλειας κειμένων. Σου παρέχονται τα εξής:\n"
                          "1. Μια '**Αρχική** Συνολική Περίληψη (Στάδιο 2)' μιας διαβούλευσης.\n" # FIX 3
                          "2. Ένα σύνολο από 'Συνδυασμένες Περιλήψεις Άρθρων (Στάδιο 1) και Σημειώσεις'. Κάθε σημείωση υποδεικνύει πιθανές σημαντικές πληροφορίες από το αρχικό άρθρο που ενδέχεται να λείπουν ή να μην τονίζονται επαρκώς στην '**Αρχική** Συνολική Περίληψη (Στάδιο 2)'.\n\n" # FIX 3
                          "Ο σκοπός σου είναι να αναθεωρήσεις την '**Αρχική** Συνολική Περίληψη (Στάδιο 2)' λαμβάνοντας υπόψη τις πληροφορίες και τις παρατηρήσεις που περιέχονται στις 'Συνδυασμένες Περιλήψεις Άρθρων (Στάδιο 1) και Σημειώσεις'. " # FIX 3
                          "Η αναθεωρημένη περίληψη πρέπει να ενσωματώνει τα σημαντικά σημεία που επισημάνθηκαν, διατηρώντας τη συνοχή, την ακρίβεια και τη συντομία. Το τελικό κείμενο πρέπει να είναι στα Ελληνικά.\n\n")
            s3_2_summary2_section = ("**ΑΡΧΙΚΗ** ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):\n--- ΑΡΧΗ **ΑΡΧΙΚΗΣ** ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---\n{initial_cohesive_summary_s2_placeholder}\n--- ΤΕΛΟΣ **ΑΡΧΙΚΗΣ** ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---\n\n") # FIX 3
            s3_2_notes_section = ("ΣΥΝΔΥΑΣΜΕΝΕΣ ΠΕΡΙΛΗΨΕΙΣ ΑΡΘΡΩΝ (ΣΤΑΔΙΟ 1) ΚΑΙ ΣΗΜΕΙΩΣΕΙΣ:\n--- ΑΡΧΗ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---\n{combined_stage1_summaries_and_notes_placeholder}\n--- ΤΕΛΟΣ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---\n\n")
            s3_2_instruction_out = "ΠΑΡΑΚΑΛΩ ΠΑΡΕΧΕΤΕ ΤΗΝ **ΤΕΛΙΚΗ** ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ:" # FIX 3
            stage3_2_task_instructions_template_el = (s3_2_intro + s3_2_summary2_section + s3_2_notes_section + s3_2_instruction_out)
            current_initial_prompt_s3_2 = stage3_2_task_instructions_template_el.format(initial_cohesive_summary_s2_placeholder=initial_cohesive_summary_s2, combined_stage1_summaries_and_notes_placeholder=concatenated_summaries_and_notes)
            current_core_input_s3_2 = (f"**ΑΡΧΙΚΗ** ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):\n{initial_cohesive_summary_s2}\n\nΣΥΝΔΥΑΣΜΕΝΕΣ ΠΕΡΙΛΗΨΕΙΣ ΑΡΘΡΩΝ (ΣΤΑΔΙΟ 1) ΚΑΙ ΣΗΜΕΙΩΣΕΙΣ:\n{concatenated_summaries_and_notes}") # FIX 3
            original_task_instructions_for_correction_s3_2 = stage3_2_task_instructions_template_el
            refined_target_tokens = 1100 # FIX 1: Token limit for Stage 3.2
            final_summary_s3_2 = summarize_text(model, processor, stage_id="3.2", initial_llm_prompt_text=current_initial_prompt_s3_2, core_input_data_for_correction=current_core_input_s3_2, original_task_instructions_for_correction=original_task_instructions_for_correction_s3_2, target_tokens_for_summary=refined_target_tokens, language_code="el")
            generated_final_summary_s3_2_tokens = get_token_count(final_summary_s3_2, processor) if final_summary_s3_2 else 0
            main_logger.info(f"Stage 3.2: Final Cohesive Summary (ΤΕΛΙΚΗ) generated. Token length: {generated_final_summary_s3_2_tokens}")
            if not final_summary_s3_2:
                main_logger.warning("Refinement to Final Cohesive Summary (ΤΕΛΙΚΗ) failed. The Initial Cohesive Summary (ΑΡΧΙΚΗ) will be used as final.")
                final_summary_s3_2 = initial_cohesive_summary_s2
        elif not is_stage_2_summary_valid: main_logger.warning("Skipping Stage 3.2 as the Initial Cohesive Summary (ΑΡΧΙΚΗ) is missing or invalid.")
        else: main_logger.info("Skipping Stage 3.2 as there were no valid notes or Stage 1 summaries for refinement.")
    else: main_logger.info("Skipping Stage 3.2 as no missing information notes were generated in Stage 3.1.")
    main_logger.info("--- Stage 3.2 Complete. ---")

    output_file_path = "summary_output.txt"
    output_buffer = []
    # FIX 3: Update output headers and use new variable names
    output_buffer.append("========= ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 3.2) =========\n")
    output_buffer.append(f"{final_summary_s3_2}\n")
    if generated_final_summary_s3_2_tokens is not None:
        output_buffer.append(f"(Generated Token Length: {generated_final_summary_s3_2_tokens})\n\n")
    elif generated_initial_summary_s2_tokens is not None and final_summary_s3_2 == initial_cohesive_summary_s2: # Fallback case
        output_buffer.append(f"(Generated Token Length: {generated_initial_summary_s2_tokens} - Αρχική Περίληψη Σταδίου 2 χρησιμοποιήθηκε ως τελική)\n\n")
    else:
        output_buffer.append("(Token length not available for final summary)\n\n")

    output_buffer.append("========= ΑΡΧΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2) =========\n")
    output_buffer.append(f"{initial_cohesive_summary_s2}\n")
    if generated_initial_summary_s2_tokens is not None:
        output_buffer.append(f"(Generated Token Length: {generated_initial_summary_s2_tokens})\n\n")
    else:
        output_buffer.append("(Token length not available for initial cohesive summary)\n\n")

    output_buffer.append("========= INDIVIDUAL ARTICLE SUMMARIES (STAGE 1) =========\n")
    for detail in individual_article_details:
        output_buffer.append(f"--- Article ID: {detail['id']} ---")
        output_buffer.append(f"Generated Stage 1 Summary Token Length: {detail['generated_summary_token_length']}")
        output_buffer.append(f"Stage 1 Summary:\n{detail['summary']}\n")
    if missing_info_notes:
        output_buffer.append("\n========= STAGE 3.1: MISSING INFORMATION NOTES =========\n")
        for note_info in missing_info_notes:
            output_buffer.append(f"--- Note for Article ID: {note_info['article_id']} ---")
            output_buffer.append(f"{note_info['note']}\n")

    main_logger.info(f"Writing all summaries and notes to {output_file_path}")
    try:
        with open(output_file_path, "w", encoding="utf-8") as f: f.write("\n".join(output_buffer))
        main_logger.info(f"Output successfully written to {output_file_path}")
    except IOError as e: main_logger.error(f"Failed to write summary to file: {e}")

if __name__ == "__main__":
    # For issues with TorchDynamo like "Unexpected type in sourceless builder",
    # running the script with TORCHDYNAMO_DISABLE=1 as an environment variable is often a solution:
    # Example: TORCHDYNAMO_DISABLE=1 python your_script_name.py
    main()