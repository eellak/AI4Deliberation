import os
import sys
import logging
import sqlite3
import torch
from transformers import AutoProcessor, Gemma3ForConditionalGeneration
import argparse
import datetime
import csv
import json
import re
import math
from typing import List, Dict, Any

# --- Environment Setup ---
os.environ['TORCHDYNAMO_DISABLE'] = '1'

# --- Dynamically add article_parser_utils to path and import ---
ARTICLE_PARSER_UTILS_PATH = "/mnt/data/AI4Deliberation/article_extraction_analysis"
if ARTICLE_PARSER_UTILS_PATH not in sys.path:
    sys.path.append(ARTICLE_PARSER_UTILS_PATH)
import article_parser_utils

# --- Logger Setup ---
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:  # e.g., running in Jupyter
    SCRIPT_DIR = os.getcwd()
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE_NAME = f"narrative_workflow_reasoning_trace_{TIMESTAMP}.log"
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, LOG_FILE_NAME)

logger = logging.getLogger("NarrativeWorkflowLogger")
logger.setLevel(logging.DEBUG)
logger.propagate = False
reasoning_trace_logger = logging.getLogger("NarrativeReasoningTrace")
reasoning_trace_logger.setLevel(logging.DEBUG)
reasoning_trace_logger.propagate = False

if not logger.hasHandlers():
    file_handler = logging.FileHandler(LOG_FILE_PATH, mode='w')
    general_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(lineno)d - %(message)s')
    file_handler.setFormatter(general_formatter)
    logger.addHandler(file_handler)
    trace_file_handler = logging.FileHandler(LOG_FILE_PATH, mode='a')
    reasoning_trace_formatter = logging.Formatter('%(message)s')
    trace_file_handler.setFormatter(reasoning_trace_formatter)
    reasoning_trace_logger.addHandler(trace_file_handler)
    logger.info(f"Narrative Workflow Logger initialized. Log file: {LOG_FILE_PATH}")

logger.info(f"TORCHDYNAMO_DISABLE set to: {os.environ.get('TORCHDYNAMO_DISABLE')}")

# --- Constants ---
DB_PATH = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"
TABLE_NAME = "articles"
TEXT_COLUMN_NAME = "content"
TITLE_COLUMN_NAME = "title"
ID_COLUMN_NAME = "id"
MODEL_ID = "google/gemma-3-4b-it"
TITLE_RANGE_RE = re.compile(r"\(\s*(\d{1,3})\s*[–-]\s*(\d{1,3})\s*\)")

# --- Constants for Advanced Input Splitting & Rejoining ---
MAX_SAFE_TOKENS_PER_CHUNK_PROMPT = 7000
TARGET_TOKENS_FOR_INITIAL_CHUNK = 1000

# --- STRATEGIC TOKEN BUDGET FOR FINAL STAGE 2 OUTPUTS ---
TARGET_REJOINED_S2_1_TOKENS = 2800
TARGET_REJOINED_S2_2_TOKENS = 600
TARGET_REJOINED_S2_3_TOKENS = 1200

# --- Prompt Templates ---
# Recommended Greek System Prompt
SYSTEM_PROMPT = "Είσαι ένας εξυπηρετικός βοηθός με εξειδίκευση στη δημιουργία σύντομων και περιεκτικών περιλήψεων."

STAGE1_PROMPT_TEMPLATE = (
    "Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω κειμένου στα Ελληνικά, σε απλή γλώσσα, "
    "κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως 3 προτάσεις.\n"
    "Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες αν πρόκειται για νομοθετικό άρθρο.\n"
    "Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης, μη βάζεις εισαγωγή στην περίληψη απλώς γράψε την:"
)

STAGE2_1_COHESIVE_PROMPT_TEMPLATE = (
    "Οι παρακάτω είναι ατομικές περιλήψεις πολλαπλών άρθρων από μία ενιαία διαβούλευση. "
    "Παρακαλώ συνδυάστε τις σε ένα ενιαίο, συνεκτικό και **λεπτομερές** κείμενο στα Ελληνικά που αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου. "
    "Βεβαιωθείτε ότι καλύπτονται όλες οι σημαντικές πτυχές που αναφέρονται στις επιμέρους περιλήψεις."
)

STAGE2_2_THEMATIC_PROMPT_TEMPLATE = (
    "Βάσει των παρακάτω περιλήψεων άρθρων ενός νομοσχεδίου, προσδιόρισε τα **γενικά θέματα** της νομοθεσίας που θα είχαν **ιδιαίτερο ενδιαφέρον για τους πολίτες**. "
    "Κατάγραψε αυτά τα θέματα με σαφήνεια και συντομία, το καθένα σε νέα γραμμή (π.χ., ξεκινώντας με παύλα)."
)

STAGE2_3_NARRATIVE_PLAN_PROMPT_TEMPLATE = (
    "Με βάση τις παρακάτω περιλήψεις άρθρων, σκιαγράφησε ένα **ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ** για ένα ενημερωτικό άρθρο δημοσιογραφικού ύφους. "
    "Το σχέδιο πρέπει να περιλαμβάνει **6-7 ενότητες**, όπου κάθε ενότητα έχει έναν τίτλο και μια σύντομη περιγραφή (1-2 προτάσεις). "
    "Η δομή πρέπει να έχει αρχή, μέση και τέλος. Η προσέγγιση πρέπει να είναι **αποκλειστικά βασισμένη στα παρεχόμενα στοιχεία, λιτή και αντικειμενική**. "
    "**Προσοχή: Δημιούργησε μόνο το σχέδιο της αφήγησης, όχι την ίδια την αφήγηση.**"
)

STAGE2_X_MULTI_PART_SUFFIX = (
    "\n\nΠΡΟΣΟΧΗ: Τα παρακάτω κείμενα αποτελούν το ΜΕΡΟΣ {part_number} από {total_parts} ενός μεγαλύτερου συνόλου από ατομικές περιλήψεις. "
    "Ο στόχος σας είναι να επεξεργαστείτε **αυτό το συγκεκριμένο μέρος** σύμφωνα με τις αρχικές οδηγίες. "
    "Το αποτέλεσμά σας θα συνδυαστεί αργότερα με τα άλλα μέρη για να δημιουργηθεί το τελικό, πλήρες αποτέλεσμα."
)

REJOIN_STAGE2_1_PROMPT_TEMPLATE = (
    "Σου παρέχονται δύο τμήματα (Μέρος Α και Μέρος Β) μιας συνολικής περίληψης νομοσχεδίου. "
    "Ο σκοπός σου είναι να συνδυάσεις το 'ΜΕΡΟΣ Α' και το 'ΜΕΡΟΣ Β' σε ένα ενιαίο, πλήρες και συνεκτικό κείμενο, σαν να είχαν γραφτεί εξ αρχής μαζί. "
    "Εξάλειψε τυχόν περιττές επαναλήψεις, διασφαλίζοντας ομαλή ροή.\n\n"
    "--- ΜΕΡΟΣ Α ---\n{summary_part_a}\n--- ΤΕΛΟΣ ΜΕΡΟΥΣ Α ---\n\n"
    "--- ΜΕΡΟΣ Β ---\n{summary_part_b}\n--- ΤΕΛΟΣ ΜΕΡΟΥΣ Β ---\n\n"
    "Παρακαλώ παρείχε το ενιαίο κείμενο:"
)

REJOIN_STAGE2_2_PROMPT_TEMPLATE = (
    "Σου παρέχονται δύο λίστες (Μέρος Α και Μέρος Β) με θέματα ενός νομοσχεδίου. "
    "Ο σκοπός σου είναι να τις συνδυάσεις σε μια ενιαία, περιεκτική λίστα. "
    "Ενοποίησε παρόμοια ή επικαλυπτόμενα θέματα. Αφαίρεσε τυχόν διπλότυπα.\n\n"
    "--- ΜΕΡΟΣ Α (ΘΕΜΑΤΑ) ---\n{themes_part_a}\n--- ΤΕΛΟΣ ΜΕΡΟΥΣ Α ---\n\n"
    "--- ΜΕΡΟΣ Β (ΘΕΜΑΤΑ) ---\n{themes_part_b}\n--- ΤΕΛΟΣ ΜΕΡΟΥΣ Β ---\n\n"
    "Παρακαλώ παρείχε την ενιαία, ενοποιημένη λίστα θεμάτων:"
)

REJOIN_STAGE2_3_PROMPT_TEMPLATE = (
    "Σου παρέχονται δύο τμήματα (Μέρος Α και Μέρος Β) ενός σχεδίου αφήγησης. "
    "Ο σκοπός σου είναι να τα συνδυάσεις σε ένα ενιαίο, λογικά δομημένο σχέδιο με αρχή, μέση και τέλος. "
    "Πιθανόν να χρειαστεί να αναδιατάξεις ή να συγχωνεύσεις ενότητες. Απέφυγε την επανάληψη ιδεών.\n\n"
    "--- ΜΕΡΟΣ Α (ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ) ---\n{plan_part_a}\n--- ΤΕΛΟΣ ΜΕΡΟΥΣ Α ---\n\n"
    "--- ΜΕΡΟΣ Β (ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ) ---\n{plan_part_b}\n--- ΤΕΛΟΣ ΜΕΡΟΥΣ Β ---\n\n"
    "Παρακαλώ παρείχε το ενιαίο, ολοκληρωμένο σχέδιο αφήγησης:"
)

STAGE3_NARRATIVE_EXPOSITION_PROMPT_TEMPLATE_INTRO = (
    "Σου παρέχονται: (1) μια Συνολική Περίληψη ενός νομοσχεδίου, (2) τα Κύρια Θέματα που αφορούν τους πολίτες, και (3) ένα Σχέδιο Αφήγησης.\n\n"
    "Η Συνολική Περίληψη είναι:\n'''\n{cohesive_summary}\n'''\n\n"
    "Τα Κύρια Θέματα είναι:\n'''\n{thematic_areas}\n'''\n\n"
    "Το Σχέδιο Αφήγησης είναι:\n'''\n{narrative_plan}\n'''\n\n"
    "Παρακαλώ, χρησιμοποίησε αυτά τα στοιχεία για να συνθέσεις ένα **ενημερωτικό και ευανάγνωστο κείμενο** για τους πολίτες. Το κείμενο πρέπει:\n"
    "- Να αναπτύσσει τα Κύρια Θέματα ακολουθώντας τη δομή του Σχεδίου Αφήγησης.\n"
    "- Να βασίζεται **αυστηρά στα γεγονότα και τις πληροφορίες που περιέχονται στη Συνολική Περίληψη**.\n"
    "- Να εστιάζει στην **ουσία του νομοσχεδίου**, εξηγώντας με σαφήνεια τι σκοπεύει να επιτύχει και πώς.\n"
    "- Να διατηρεί απόλυτη **ουδετερότητα και αντικειμενικότητα**.\n"
    "- Να αποδίδεις ισχυρισμούς ή στόχους **με σαφήνεια στην πηγή τους** (π.χ., 'Σύμφωνα με την κυβέρνηση...')."
)

CONCISE_CONTINUATION_PROMPT_TEMPLATE = (
    "Η προηγούμενη απάντησή σας στο παρακάτω αίτημα φαίνεται ότι διακόπηκε. "
    "Είναι πολύ σημαντικό να **ολοκληρώσετε την τρέχουσα σκέψη και να ολοκληρώσετε την απάντηση** όσο το δυνατόν πιο σύντομα. "
    "Η απάντησή σας πρέπει να ξεκινά ΑΜΕΣΩΣ με τις λέξεις που λείπουν. Μην προσθέσετε εισαγωγικές φράσεις.\n\n"
    "Αρχικό αίτημα:\n'''\n{original_task_instructions}\n'''\n\n"
    "Αρχικά δεδομένα εισόδου:\n'''\n{original_input_data}\n'''\n\n"
    "Η μερικώς ολοκληρωμένη απάντησή σας:\n'''\n{truncated_response}\n'''\n\n"
    "Παρακαλώ, συνεχίστε ΑΜΕΣΩΣ την απάντηση:"
)

ALL_PROMPT_TEMPLATES = {
    "STAGE1": STAGE1_PROMPT_TEMPLATE,
    "STAGE2_1": STAGE2_1_COHESIVE_PROMPT_TEMPLATE,
    "STAGE2_2": STAGE2_2_THEMATIC_PROMPT_TEMPLATE,
    "STAGE2_3": STAGE2_3_NARRATIVE_PLAN_PROMPT_TEMPLATE,
    "STAGE2_X_MULTI_PART_SUFFIX": STAGE2_X_MULTI_PART_SUFFIX,
    "REJOIN_STAGE2_1": REJOIN_STAGE2_1_PROMPT_TEMPLATE,
    "REJOIN_STAGE2_2": REJOIN_STAGE2_2_PROMPT_TEMPLATE,
    "REJOIN_STAGE2_3": REJOIN_STAGE2_3_PROMPT_TEMPLATE,
    "STAGE3_INTRO": STAGE3_NARRATIVE_EXPOSITION_PROMPT_TEMPLATE_INTRO,
    "CONCISE_CONTINUATION": CONCISE_CONTINUATION_PROMPT_TEMPLATE,
}

# --- Core Utility and Model Functions ---

def load_model_and_processor(model_id=MODEL_ID):
    logger.info(f"Attempting to load model and processor. Model ID: {model_id}")
    try:
        model = Gemma3ForConditionalGeneration.from_pretrained(
            model_id, device_map="auto", torch_dtype=torch.bfloat16, attn_implementation="sdpa"
        ).eval()
        processor = AutoProcessor.from_pretrained(model_id)
        logger.info("Model and processor loaded successfully.")
        return model, processor
    except Exception as e:
        logger.error(f"CRITICAL ERROR: {e}", exc_info=True)
        raise

def check_response_completeness(response_text):
    if not response_text: return False
    end_punctuation = ['.', '?', '!', '."', '?"', '!"', '.»', '?»', '! »', ':']
    return any(response_text.strip().endswith(punct) for punct in end_punctuation)

def get_token_count(text, processor):
    if not processor or not text: return 0
    try:
        return len(processor.tokenizer(text).input_ids)
    except Exception as e:
        logger.error(f"Error in get_token_count: {e}")
        return 0

def summarize_text(model, processor, stage_id: str, initial_llm_prompt_text: str,
                   core_input_data_for_correction: str, original_task_instructions_for_correction: str,
                   target_tokens_for_summary: int):
    reasoning_trace_logger.info(f"\n{'='*80}\nSTAGE {stage_id} - CALL\n{'='*80}\nPROMPT:\n{initial_llm_prompt_text}\n{'-'*40}")
    if not initial_llm_prompt_text or not initial_llm_prompt_text.strip():
        logger.warning(f"[{stage_id}] Skipping due to empty prompt.")
        return "[SKIPPED: EMPTY PROMPT]"

    messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]},
        {"role": "user", "content": [{"type": "text", "text": initial_llm_prompt_text}]}
    ]
    try:
        inputs = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[-1]
        with torch.inference_mode():
            outputs = model.generate(**inputs, max_new_tokens=target_tokens_for_summary, do_sample=False)
        decoded_summary = processor.decode(outputs[0][input_len:], skip_special_tokens=True)
        
        if not check_response_completeness(decoded_summary):
            logger.warning(f"[{stage_id}] Response may be truncated. Attempting continuation.")
            continuation_prompt = CONCISE_CONTINUATION_PROMPT_TEMPLATE.format(
                original_task_instructions=original_task_instructions_for_correction,
                original_input_data=core_input_data_for_correction,
                truncated_response=decoded_summary
            )
            cont_messages = [{"role": "user", "content": [{"type": "text", "text": continuation_prompt}]}]
            cont_inputs = processor.apply_chat_template(cont_messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
            cont_input_len = cont_inputs["input_ids"].shape[-1]
            with torch.inference_mode():
                cont_outputs = model.generate(**cont_inputs, max_new_tokens=200, do_sample=False)
            continuation_fragment = processor.decode(cont_outputs[0][cont_input_len:], skip_special_tokens=True)
            decoded_summary += continuation_fragment
        
        final_output = decoded_summary
    except Exception as e:
        logger.error(f"[{stage_id}] Error during summarization: {e}", exc_info=True)
        final_output = f"[ERROR SUMMARIZING: {e}]"

    reasoning_trace_logger.info(f"OUTPUT:\n{final_output}\n{'='*80}\n")
    return final_output

def summarize_chunk_stage1(model, processor, chunk_data: Dict[str, Any]):
    chunk_title = chunk_data.get("raw_header") or chunk_data.get("title_line", "N/A")
    content = chunk_data.get("content", "")
    if not content.strip():
        return f"Η περίληψη για το '{chunk_title}' παραλείφθηκε λόγω κενού περιεχομένου."
    prompt = f"{ALL_PROMPT_TEMPLATES['STAGE1']}\n\nΤίτλος Ενότητας: {chunk_title}\n\nΚείμενο Ενότητας:\n{content}"
    return summarize_text(model, processor, "1", prompt, content, ALL_PROMPT_TEMPLATES['STAGE1'], 300)

def fetch_articles_for_consultation(consultation_id, article_db_id=None):
    logger.info(f"Fetching DB articles for consultation_id: {consultation_id}")
    data = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            query = f"SELECT {ID_COLUMN_NAME}, {TITLE_COLUMN_NAME}, {TEXT_COLUMN_NAME} FROM {TABLE_NAME} WHERE consultation_id = ?"
            params = [consultation_id]
            if article_db_id:
                query += f" AND {ID_COLUMN_NAME} = ?"
                params.append(article_db_id)
            cursor.execute(query, params)
            for row in cursor.fetchall():
                data.append({'id': row[0], 'title': row[1], 'content': row[2]})
    except sqlite3.Error as e:
        logger.error(f"DB error: {e}", exc_info=True)
    return data

# --- Corrected Stage 0 Article Parsing Logic ---

def parse_db_article_title_range(db_article_title: str) -> List[int]:
    """Parses a numeric range (e.g., Άρθρα 1-5) from a DB article title string."""
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

    all_mentions_in_text = article_parser_utils.find_all_article_mentions(text_content))
    logger.debug(f"Found {len(all_mentions_in_text)} total mentions in text for gap filling.")

    for mention_details in all_mentions_in_text:
        parsed_mention_info = mention_details.get("parsed_details", {})
        article_num_of_mention = parsed_mention_info.get("main_number")

        if article_num_of_mention is None or article_num_of_mention not in needed_set:
            continue

        priority = 4
        if mention_details.get("is_start_of_line") and not mention_details.get("is_quoted"):
            priority = 1
        elif mention_details.get("is_start_of_line") and mention_details.get("is_quoted"):
            priority = 2
        elif not mention_details.get("is_start_of_line") and not mention_details.get("is_quoted"):
            priority = 3
        
        current_best_mention_for_num = candidate_mentions_for_needed_numbers.get(article_num_of_mention)
        if current_best_mention_for_num is None or priority < current_best_mention_for_num.get("priority", 5):
            mention_to_store = mention_details.copy()
            mention_to_store["priority"] = priority
            mention_to_store["parsed_info"] = parsed_mention_info 
            candidate_mentions_for_needed_numbers[article_num_of_mention] = mention_to_store
            logger.debug(f"Chose mention for article {article_num_of_mention} (Prio: {priority}): '{mention_details.get('match_text')}'")

    return list(candidate_mentions_for_needed_numbers.values())

def get_internally_completed_chunks_for_db_article(db_article_content: str, db_article_title: str) -> List[Dict[str, Any]]:
    """
    Processes a single DB article's content to find and complete internal article sequences,
    then returns structured chunks using the low-level functions from article_parser_utils.
    """
    if not db_article_content or not db_article_content.strip():
        logger.info("DB article content is empty. Returning no chunks.")
        return []

    logger.debug(f"Starting internal completion for DB article. Title: '{db_article_title}'")
    
    try:
        true_headers_locations = article_parser_utils._get_true_main_article_header_locations(db_article_content)
        initial_sequence_numbers = sorted({h_loc.get("article_number") for h_loc in true_headers_locations if h_loc.get("article_number") is not None})
        
        mentions_for_reconstruction = []
        expected_numbers_from_title = parse_db_article_title_range(db_article_title)
        
        if expected_numbers_from_title:
            missing_compared_to_title = sorted(list(set(expected_numbers_from_title) - set(initial_sequence_numbers)))
            if missing_compared_to_title:
                mentions_for_title_gaps = find_and_prioritize_mentions_for_gaps(db_article_content, missing_compared_to_title)
                mentions_for_reconstruction.extend(mentions_for_title_gaps)
                found_numbers = {m['parsed_info'].get('main_number') for m in mentions_for_title_gaps if m.get('parsed_info')}
                initial_sequence_numbers = sorted(list(set(initial_sequence_numbers).union(found_numbers)))

        internal_gaps_to_fill = []
        if len(initial_sequence_numbers) >= 2:
            for i in range(len(initial_sequence_numbers) - 1):
                start, end = initial_sequence_numbers[i], initial_sequence_numbers[i+1]
                if end > start + 1:
                    internal_gaps_to_fill.extend(range(start + 1, end))
        
        if internal_gaps_to_fill:
            current_mention_numbers = {m['parsed_info'].get('main_number') for m in mentions_for_reconstruction if m.get('parsed_info')}
            needed_gaps = sorted(list(set(internal_gaps_to_fill) - current_mention_numbers))
            if needed_gaps:
                mentions_for_internal_gaps = find_and_prioritize_mentions_for_gaps(db_article_content, needed_gaps)
                mentions_for_reconstruction.extend(mentions_for_internal_gaps)

        main_delimiters = []
        for h_loc in true_headers_locations:
            raw_line = h_loc.get("original_line_text", "")
            match_text = h_loc.get("match_text", "")
            main_delimiters.append({
                "line_num": h_loc.get("line_index", -1) + 1,
                "parsed_header": h_loc.get("parsed_header_details_copy", {}),
                "raw_header_line": match_text, 
                "char_offset_in_original_line": raw_line.find(match_text) if raw_line and match_text else 0
            })

        formatted_mentions = []
        for m in mentions_for_reconstruction:
            mention_copy = m.copy()
            mention_copy["line_number"] = m.get("line_index", -1) + 1
            formatted_mentions.append(mention_copy)
        
        reconstructed_chunks = article_parser_utils.reconstruct_article_chunks_with_prioritized_mentions(
            original_text=db_article_content,
            main_header_locations=main_delimiters,
            prioritized_mentions_input=formatted_mentions
        )

        if not reconstructed_chunks:
            if db_article_content.strip():
                logger.warning(f"Parser returned no chunks for '{db_article_title}', but content exists. Treating as a single fallback chunk.")
                return [{'raw_header': db_article_title, 'content': db_article_content, 'type': 'fallback'}]
            return []

        return reconstructed_chunks

    except Exception as e:
        logger.error(f"Error in article parsing for title '{db_article_title}': {e}", exc_info=True)
        return [{'raw_header': db_article_title, 'content': db_article_content, 'type': 'fallback'}]

# --- NEW HELPER FUNCTIONS FOR SCALABLE STAGE 2 PROCESSING ---

def smart_chunk_summaries(
    summaries_list: List[str], base_prompt_text: str, part_suffix_template: str,
    max_prompt_tokens: int, processor: Any, overlap: int = 1
) -> List[List[str]]:
    """Splits a list of summaries into the minimum number of chunks required."""
    if not summaries_list: return []
    
    system_prompt_tokens = get_token_count(SYSTEM_PROMPT, processor)
    placeholder_suffix = part_suffix_template.format(part_number=1, total_parts=1)
    prompt_overhead = system_prompt_tokens + get_token_count(base_prompt_text + placeholder_suffix, processor)
    max_content_tokens = max_prompt_tokens - prompt_overhead

    if max_content_tokens <= 0:
        logger.error("Prompt overhead exceeds max tokens per chunk. Cannot create chunks.")
        return []

    split_indices = [0]
    current_tokens = 0
    for i, summary in enumerate(summaries_list):
        summary_tokens = get_token_count(summary, processor) + get_token_count("\n\n---\n\n", processor)
        if current_tokens + summary_tokens > max_content_tokens and i > split_indices[-1]:
            split_indices.append(i)
            current_tokens = 0
        current_tokens += summary_tokens

    all_chunks = []
    for i in range(len(split_indices)):
        start_index = split_indices[i]
        if i > 0: start_index = max(0, start_index - overlap)
        end_index = split_indices[i+1] if i + 1 < len(split_indices) else len(summaries_list)
        all_chunks.append(summaries_list[start_index:end_index])

    logger.info(f"Smart chunking split {len(summaries_list)} summaries into {len(all_chunks)} chunks.")
    return all_chunks

def process_and_rejoin_stage(
    stage_id_prefix: str, all_individual_summaries: List[str], model: Any, processor: Any,
    all_templates: Dict[str, str], max_chunk_prompt_tokens: int, final_target_output_tokens: int, dry_run: bool = False
) -> str:
    """Orchestrates dynamic chunking and hierarchical rejoining for a Stage 2 sub-task."""
    stage_name = f"Stage {stage_id_prefix}"
    logger.info(f"--- Starting {stage_name} Processing ---")

    if dry_run: return f"[DRY RUN] Placeholder for {stage_name} output."
    if not all_individual_summaries: return ""

    base_prompt_key = f"STAGE{stage_id_prefix.replace('.', '_')}"
    base_prompt_text = all_templates[base_prompt_key]
    full_content_text = "\n\n---\n\n".join(all_individual_summaries)
    full_prompt_for_check = SYSTEM_PROMPT + base_prompt_text + full_content_text
    estimated_tokens = get_token_count(full_prompt_for_check, processor)

    if estimated_tokens <= max_chunk_prompt_tokens:
        logger.info(f"{stage_name} input ({estimated_tokens} tokens) is small enough. Processing as single part.")
        return summarize_text(model, processor, f"{stage_id_prefix}_single_pass", base_prompt_text + "\n\n" + full_content_text,
                              full_content_text, base_prompt_text, final_target_output_tokens)

    summary_chunks = smart_chunk_summaries(all_individual_summaries, base_prompt_text, all_templates["STAGE2_X_MULTI_PART_SUFFIX"],
                                           max_chunk_prompt_tokens, processor, overlap=1)
    
    if len(summary_chunks) <= 1:
        logger.info(f"{stage_name} chunking resulted in one chunk. Processing as single part.")
        return summarize_text(model, processor, f"{stage_id_prefix}_single_pass", base_prompt_text + "\n\n" + full_content_text,
                              full_content_text, base_prompt_text, final_target_output_tokens)
    
    processing_queue = []
    for i, chunk_list in enumerate(summary_chunks):
        part_number = i + 1
        chunk_content = "\n\n---\n\n".join(chunk_list)
        part_suffix = all_templates["STAGE2_X_MULTI_PART_SUFFIX"].format(part_number=part_number, total_parts=len(summary_chunks))
        prompt_for_part = base_prompt_text + part_suffix + "\n\n" + chunk_content
        processing_queue.append(summarize_text(model, processor, f"{stage_id_prefix}_part_{part_number}", prompt_for_part,
                                               chunk_content, base_prompt_text + part_suffix, TARGET_TOKENS_FOR_INITIAL_CHUNK))

    rejoin_round = 1
    rejoin_prompt_template = all_templates[f"REJOIN_STAGE{stage_id_prefix.replace('.', '_')}"]
    while len(processing_queue) > 1:
        logger.info(f"Starting {stage_name} Rejoining Round {rejoin_round} with {len(processing_queue)} items.")
        next_queue = []
        for i in range(0, len(processing_queue), 2):
            if i + 1 < len(processing_queue):
                part_a, part_b = processing_queue[i], processing_queue[i+1]
                rejoin_keys = {"2.1": {"summary_part_a": part_a, "summary_part_b": part_b}, "2.2": {"themes_part_a": part_a, "themes_part_b": part_b}, "2.3": {"plan_part_a": part_a, "plan_part_b": part_b}}
                rejoin_prompt = rejoin_prompt_template.format(**rejoin_keys[stage_id_prefix])
                next_queue.append(summarize_text(model, processor, f"{stage_id_prefix}_rejoin_r{rejoin_round}", rejoin_prompt,
                                                 f"Part A:{part_a}\nPart B:{part_b}", "Rejoin two parts.", final_target_output_tokens))
            else:
                next_queue.append(processing_queue[i])
        processing_queue = next_queue
        rejoin_round += 1

    final_result = processing_queue[0] if processing_queue else f"[ERROR: {stage_name} failed]"
    logger.info(f"--- Finished {stage_name} Processing ---")
    return final_result

# --- Main Workflow Orchestration ---
def run_narrative_summarization_workflow(consultation_id, article_db_id_to_process=None, dry_run=False):
    logger.info(f"Starting narrative workflow for consultation_id: {consultation_id}, dry_run: {dry_run}")
    results = {"consultation_id": consultation_id, "errors": [], "stages_completed": []}
    model, processor = load_model_and_processor()

    logger.info("--- Starting Stage 0: Article Fetching and Chunking ---")
    db_articles = fetch_articles_for_consultation(consultation_id, article_db_id_to_process)
    if not db_articles:
        results["errors"].append(f"No articles found for consultation_id {consultation_id}.")
        return results
    
    article_chunks_to_process = []
    for article in db_articles:
        chunks = get_internally_completed_chunks_for_db_article(article['content'], article['title'])
        article_chunks_to_process.extend(chunks)
    
    if not article_chunks_to_process:
        results["errors"].append("No processable article chunks found.")
        return results
    results["stages_completed"].append(f"Stage 0: Fetched and parsed into {len(article_chunks_to_process)} article chunks")

    logger.info("--- Starting Stage 1: Individual Summaries ---")
    all_individual_summaries = []
    for i, chunk in enumerate(article_chunks_to_process):
        logger.info(f"Summarizing chunk {i+1}/{len(article_chunks_to_process)}")
        all_individual_summaries.append(summarize_chunk_stage1(model, processor, chunk))
    results["all_individual_summaries_text"] = "\n\n---\n\n".join(all_individual_summaries)
    results["stages_completed"].append(f"Stage 1: Generated {len(all_individual_summaries)} summaries")

    results["cohesive_summary_stage2_1"] = process_and_rejoin_stage("2.1", all_individual_summaries, model, processor, ALL_PROMPT_TEMPLATES, MAX_SAFE_TOKENS_PER_CHUNK_PROMPT, TARGET_REJOINED_S2_1_TOKENS, dry_run)
    results["identified_themes_stage2_2"] = process_and_rejoin_stage("2.2", all_individual_summaries, model, processor, ALL_PROMPT_TEMPLATES, MAX_SAFE_TOKENS_PER_CHUNK_PROMPT, TARGET_REJOINED_S2_2_TOKENS, dry_run)
    results["narrative_plan_stage2_3"] = process_and_rejoin_stage("2.3", all_individual_summaries, model, processor, ALL_PROMPT_TEMPLATES, MAX_SAFE_TOKENS_PER_CHUNK_PROMPT, TARGET_REJOINED_S2_3_TOKENS, dry_run)

    logger.info("--- Starting Stage 3: Generating Final Narrative Exposition ---")
    if not dry_run:
        stage3_prompt = ALL_PROMPT_TEMPLATES["STAGE3_INTRO"].format(
            cohesive_summary=results["cohesive_summary_stage2_1"],
            thematic_areas=results["identified_themes_stage2_2"],
            narrative_plan=results["narrative_plan_stage2_3"]
        )
        core_input = f"Summary:\n{results['cohesive_summary_stage2_1']}\n\nThemes:\n{results['identified_themes_stage2_2']}\n\nPlan:\n{results['narrative_plan_stage2_3']}"
        results["final_narrative_stage3"] = summarize_text(model, processor, "3.0_final_narrative", stage3_prompt, core_input, ALL_PROMPT_TEMPLATES["STAGE3_INTRO"], 4096)
    else:
        results["final_narrative_stage3"] = "[DRY RUN] Placeholder for final Stage 3 narrative."
    results['stages_completed'].append("Stage 3: Final Narrative Exposition")
    
    logger.info(f"Workflow completed for consultation_id: {consultation_id}")
    return results

def main():
    global DB_PATH
    cli = argparse.ArgumentParser(description="Orchestrate Narrative Summarization Workflow.")
    cli.add_argument("--consultation_id", type=int, required=True, help="ID of the consultation to process.")
    cli.add_argument("--article_db_id", type=int, help="Optional: Specific DB article ID to process.")
    cli.add_argument("--dry_run", action='store_true', help="Dry run without calling the LLM.")
    cli.add_argument("--debug", action='store_true', help="Enable debug logging to console.")
    cli.add_argument("--db-path", type=str, default=DB_PATH, help=f"Path to SQLite DB. Default: {DB_PATH}")
    args = cli.parse_args()
    DB_PATH = args.db_path
    
    if args.debug:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        if not logger.handlers: logger.addHandler(console_handler)
        if not reasoning_trace_logger.handlers: reasoning_trace_logger.addHandler(console_handler)
        logger.info("DEBUG mode enabled.")

    logger.info(f"Script started with args: {args}")
    start_time = datetime.datetime.now()
    results = run_narrative_summarization_workflow(args.consultation_id, args.article_db_id, args.dry_run)
    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    logger.info(f"Script finished in {elapsed:.2f} seconds.")

    output_filename = f"narrative_results_{args.consultation_id}_{TIMESTAMP}.json"
    output_path = os.path.join(SCRIPT_DIR, output_filename)
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
        logger.info(f"Full results saved to {output_path}")
    except Exception as e:
        logger.error(f"Failed to save results to JSON: {e}")

if __name__ == "__main__":
    main()