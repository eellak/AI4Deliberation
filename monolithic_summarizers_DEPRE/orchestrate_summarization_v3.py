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
ARTICLE_PARSER_UTILS_PATH = "/mnt/data/AI4Deliberation/article_extraction_analysis"  # Corrected to actual location
if ARTICLE_PARSER_UTILS_PATH not in sys.path:
    sys.path.append(ARTICLE_PARSER_UTILS_PATH)
import article_parser_utils # Now this should work at module level

# --- Logger Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE_NAME = f"narrative_workflow_reasoning_trace_{TIMESTAMP}.log" # Changed name for v3
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, LOG_FILE_NAME)

# Main logger for general script progress and errors
logger = logging.getLogger("NarrativeWorkflowLogger") # Changed name for v3
logger.setLevel(logging.DEBUG)
logger.propagate = False

# Reasoning trace logger for LLM prompts and outputs
reasoning_trace_logger = logging.getLogger("NarrativeReasoningTrace") # Changed name for v3
reasoning_trace_logger.setLevel(logging.DEBUG)
reasoning_trace_logger.propagate = False

if not logger.hasHandlers():
    # File handler for the main logger
    file_handler = logging.FileHandler(LOG_FILE_PATH, mode='w')
    general_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(general_formatter)
    logger.addHandler(file_handler)
    
    # File handler for the reasoning trace logger (appends to the same file)
    trace_file_handler = logging.FileHandler(LOG_FILE_PATH, mode='a') # Append mode
    reasoning_trace_formatter = logging.Formatter('%(message)s')  # Just the message
    trace_file_handler.setFormatter(reasoning_trace_formatter)
    reasoning_trace_logger.addHandler(trace_file_handler)
    
    logger.info(f"Narrative Workflow Logger initialized. Log file: {LOG_FILE_PATH}")

logger.info(f"TORCHDYNAMO_DISABLE set to: {os.environ.get('TORCHDYNAMO_DISABLE')}")

# --- Constants ---
DB_PATH = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db" # Corrected DB Path
TABLE_NAME = "articles"
CONSULTATIONS_TABLE_NAME = "consultations"
TEXT_COLUMN_NAME = "content"
TITLE_COLUMN_NAME = "title"
ID_COLUMN_NAME = "id"
MODEL_ID = "google/gemma-3-4b-it" 

TITLE_RANGE_RE = re.compile(r"\(\s*(\d{1,3})\s*[–-]\s*(\d{1,3})\s*\)") # Corrected to match v2

# --- Prompt Templates ---
STAGE1_PROMPT_TEMPLATE = (
    "Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω κειμένου στα Ελληνικά, σε απλή γλώσσα, "
    "κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως 3 προτάσεις.\n"
    "Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες αν πρόκειται για νομοθετικό άρθρο.\n"
    "Οι περιλήψεις πρέπει να είναι όσο πιο σύντομες γίνεται, διατηρώνοντας την ουσία του κειμένου και να μην είναι παραπάνω απο 3 προτάσεις σε μήκος.\n"
    "Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης, μη βάζεις εισαγωγή στην περίληψη απλώς γράψε την:"
)

# V3 - Stage 2.1 (formerly Stage 2 in v2 script)
STAGE2_1_COHESIVE_PROMPT_TEMPLATE = (
    "Οι παρακάτω είναι ατομικές περιλήψεις πολλαπλών άρθρων από μία ενιαία διαβούλευση. "
    "Παρακαλώ συνδυάστε τις σε ένα ενιαίο, συνεκτικό και **λεπτομερές** κείμενο στα Ελληνικά που αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου. "
    "Στοχεύστε σε μια **αναλυτική επισκόπηση περίπου 1500 tokens**. Βεβαιωθείτε ότι καλύπτονται όλες οι σημαντικές πτυχές που αναφέρονται στις επιμέρους περιλήψεις."
)

# V3 - Stage 2.2
STAGE2_2_THEMATIC_PROMPT_TEMPLATE = (
    "Βάσει των παρακάτω περιλήψεων άρθρων ενός νομοσχεδίου, προσδιόρισε τα **γενικά θέματα** της νομοθεσίας που θα είχαν **ιδιαίτερο ενδιαφέρον για τους πολίτες**. "
    "Κατάγραψε αυτά τα θέματα με σαφήνεια και συντομία, το καθένα σε νέα γραμμή (π.χ., ξεκινώντας με παύλα). Στόχος είναι να κατανοήσουμε τις κύριες θεματικές ενότητες που αφορούν την καθημερινότητα και τα δικαιώματα των πολιτών."
)

# V3 - Stage 2.3
STAGE2_3_NARRATIVE_PLAN_PROMPT_TEMPLATE = (
    "Με βάση τις παρακάτω περιλήψεις άρθρων, σκιαγράφησε ένα **ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ** για ένα ενημερωτικό άρθρο δημοσιογραφικού ύφους, που θα εξηγεί το νομοσχέδιο στους πολίτες. "
    "Το σχέδιο πρέπει να περιλαμβάνει **6-7 ενότητες**, όπου κάθε ενότητα έχει έναν τίτλο και μια σύντομη περιγραφή (1-2 προτάσεις) του περιεχομένου της. "
    "Η δομή της αφήγησης πρέπει να έχει αρχή, μέση και τέλος. Κάθε ενότητα πρέπει να εστιάζει στα εξής: το πρόβλημα που αναγνωρίζει η νομοθεσία, τις αλλαγές που σκοπεύει να επιφέρει, και τα αναμενόμενα αποτελέσματα. "
    "Η προσέγγιση πρέπει να είναι **αποκλειστικά βασισμένη στα παρεχόμενα στοιχεία, λιτή και αντικειμενική**, σαν ένα εξαιρετικό δημοσιογραφικό κείμενο. "
    "**Προσοχή: Δημιούργησε μόνο το σχέδιο της αφήγησης (τίτλοι και περιγραφές ενοτήτων), όχι την ίδια την αφήγηση.**"
)

# V3 - Stage 3
STAGE3_NARRATIVE_EXPOSITION_PROMPT_TEMPLATE_INTRO = (
    "Σου παρέχονται: (1) μια Συνολική Περίληψη ενός νομοσχεδίου (Στάδιο 2.1), (2) τα Κύρια Θέματα που αφορούν τους πολίτες (Στάδιο 2.2), και (3) ένα Σχέδιο Αφήγησης (Στάδιο 2.3).\n"
    "Παρακαλώ, χρησιμοποίησε αυτά τα στοιχεία για να συνθέσεις ένα **ενημερωτικό και ευανάγνωστο κείμενο** για τους πολίτες. Το κείμενο πρέπει:\n"
    "- Να αναπτύσσει τα Κύρια Θέματα ακολουθώντας τη δομή του Σχεδίου Αφήγησης.\n"
    "- Να βασίζεται **αυστηρά στα γεγονότα και τις πληροφορίες που περιέχονται στη Συνολική Περίληψη (Στάδιο 2.1)**.\n"
    "- Να εστιάζει στην **ουσία του νομοσχεδίου**, εξηγώντας με σαφήνεια τι σκοπεύει να επιτύχει και πώς.\n"
    "- Να διατηρεί απόλυτη **ουδετερότητα και αντικειμενικότητα**. Απόφυγε προσωπικές απόψεις ή αξιολογικές κρίσεις.\n"
    "- Εάν αναφέρεσαι σε δηλώσεις, ισχυρισμούς ή στόχους (π.χ., από την κυβέρνηση, υπουργούς, ή την αιτιολογική έκθεση), **απόδωσέ τους με σαφήνεια στην πηγή τους**. Για παράδειγμα, χρησιμοποίησε φράσεις όπως: 'Σύμφωνα με την κυβέρνηση...', 'Ο υπουργός δήλωσε ότι...', 'Η αιτιολογική έκθεση αναφέρει πως ο στόχος είναι να επιτευχθεί...', ή 'Το νομοσχέδιο φιλοδοξεί να...'. Μην παρουσιάζεις ισχυρισμούς ως τετελεσμένα γεγονότα, εκτός αν υποστηρίζονται από αδιαμφισβήτητα δεδομένα εντός των παρεχόμενων κειμένων.\n"
    "Ο στόχος είναι η δημιουργία ενός κειμένου που βοηθά τους πολίτες να κατανοήσουν πλήρως το προτεινόμενο νομοσχέδιο, βασιζόμενοι σε ακριβείς και αντικειμενικές πληροφορίες."
)

# New V3 prompt for concise continuation
CONCISE_CONTINUATION_PROMPT_TEMPLATE = (
    "Η προηγούμενη απάντησή σας στο παρακάτω αίτημα φαίνεται ότι διακόπηκε, πιθανώς στη μέση μιας πρότασης ή σκέψης. "
    "Είναι πολύ σημαντικό να **ολοκληρώσετε την τρέχουσα πρόταση/σκέψη και να ολοκληρώσετε την απάντηση** όσο το δυνατόν πιο σύντομα, "
    "χρησιμοποιώντας **ελάχιστες επιπλέον λέξεις/tokens**. \\n"
    "**Οδηγία: Η απάντησή σας σε αυτό το αίτημα πρέπει να ξεκινά ΑΜΕΣΩΣ με τις λέξεις που λείπουν για να ολοκληρωθεί η τελευταία, ημιτελής πρόταση της προηγούμενης απάντησης. Μην προσθέσετε εισαγωγικές φράσεις. Απλώς συνεχίστε την πρόταση. Αν η πρόταση ολοκληρώθηκε, μπορείτε να προσθέσετε το πολύ μία ακόμη σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά.**\\n"
    "Μην επαναλαμβάνετε πληροφορίες που έχουν ήδη δοθεί στην παρακάτω μερικώς ολοκληρωμένη απάντηση.\\n\\n"
    "Το αρχικό αίτημα ήταν:\\n"
    "'''\\n{original_task_instructions}\\n'''\\n\\n"
    "Τα αρχικά δεδομένα εισόδου που δόθηκαν ήταν:\\n"
    "'''\\n{original_input_data}\\n'''\\n\\n"
    "Η μερικώς ολοκληρωμένη απάντησή σας μέχρι στιγμής είναι:\\n"
    "'''\\n{truncated_response}\\n'''\\n\\n"
    "Παρακαλώ, παρέχετε **μόνο τις λέξεις που ακολουθούν ΑΜΕΣΩΣ** για να ολοκληρωθεί η τελευταία πρόταση της παραπάνω απάντησης, και αν χρειάζεται, μία (το πολύ) επιπλέον σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά:"
)

# Existing shortening prompt (ensure it remains for Stage 1)
SHORTENING_CORRECTION_PROMPT_TEMPLATE_EL = (
    "Η προηγούμενη περίληψη που δημιουργήσατε για το παρακάτω κείμενο φαίνεται να είναι ατελής ή να διακόπηκε απότομα. \\n\\n"
    "ΑΡΧΙΚΟ ΚΕΙΜΕΝΟ ΠΡΟΣ ΠΕΡΙΛΗΨΗ:\\n{core_input_text}\\n\\n"
    "ΑΡΧΙΚΕΣ ΟΔΗΓΙΕΣ ΠΕΡΙΛΗΨΗΣ:\\n{original_task_instructions}\\n\\n"
    "ΜΕΡΙΚΩΣ ΟΛΟΚΛΗΡΩΜΕΝΗ (Ή ΕΝΔΕΧΟΜΕΝΩΣ ΛΑΝΘΑΣΜΕΝΗ) ΠΕΡΙΛΗΨΗ:\\n{truncated_summary}\\n\\n"
    "Παρακαλώ δημιουργήστε μια **νέα, πλήρη και συνεκτική περίληψη** του ΑΡΧΙΚΟΥ ΚΕΙΜΕΝΟΥ, ακολουθώντας τις ΑΡΧΙΚΕΣ ΟΔΗΓΙΕΣ. \\n\\n"
    "Η νέα περίληψη πρέπει να είναι **σημαντικά πιο σύντομη** από την προηγούμενη προσπάθεια, για να αποφευχθεί η εκ νέου διακοπή. Εστιάστε στα πιο κρίσιμα σημεία. {specific_constraints}"
)

def load_model_and_processor(model_id=MODEL_ID):
    logger.info(f"Attempting to load model and processor. Model ID: {model_id}")
    try:
        logger.info("Attempting to load Gemma3ForConditionalGeneration...")
        model = Gemma3ForConditionalGeneration.from_pretrained(
            model_id,
            device_map="auto",
            torch_dtype=torch.bfloat16,
            attn_implementation="sdpa"
        ).eval()
        logger.info("Gemma3ForConditionalGeneration loaded successfully.")
        
        logger.info("Attempting to load AutoProcessor...")
        processor = AutoProcessor.from_pretrained(model_id)
        logger.info("AutoProcessor loaded successfully.")
        
        logger.info("Model and processor loaded successfully overall.")
        return model, processor
    except Exception as e:
        logger.error(f"CRITICAL ERROR during model or processor loading: {e}", exc_info=True)
        # Try to ensure these messages get out if there's a catastrophic failure
        print(f"CRITICAL ERROR during model or processor loading: {e}", file=sys.stderr)
        sys.stderr.flush()
        logging.shutdown() # Attempt to flush all handlers
        raise

# --- Article Chunking Helper Functions (Retained from v2) ---
def parse_db_article_title_range(db_article_title: str) -> List[int]:
    # Simplified from v2, direct use of the specific regex.
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
    logger.debug(f"Found {len(all_mentions_in_text)} total mentions in text for gap filling.") # Using 'logger'

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
            mention_to_store["parsed_info"] = parsed_mention_info 
            candidate_mentions_for_needed_numbers[article_num_of_mention] = mention_to_store
            logger.debug(f"Chose mention for article {article_num_of_mention} (Prio: {priority}): '{mention_details.get('match_text')}' at line {mention_details.get('line_index')}") # Using 'logger'

    return list(candidate_mentions_for_needed_numbers.values())

def get_internally_completed_chunks_for_db_article(db_article_content: str, db_article_title: str) -> List[Dict[str, Any]]:
    """Processes a single DB article's content to find and complete internal article sequences, then returns structured chunks."""
    if not db_article_content or not db_article_content.strip():
        logger.info("DB article content is empty. Returning no chunks.") # Using 'logger'
        return []

    logger.debug(f"Starting internal completion for DB article. Title: '{db_article_title}'") # Using 'logger'
    
    true_headers_locations = article_parser_utils._get_true_main_article_header_locations(db_article_content)
    initial_sequence_numbers = sorted({h_loc["article_number"] for h_loc in true_headers_locations if h_loc.get("article_number") is not None}) # Added None check
    logger.debug(f"Initial 'true' header sequence numbers: {initial_sequence_numbers}") # Using 'logger'

    mentions_for_reconstruction = []

    expected_numbers_from_title = parse_db_article_title_range(db_article_title)
    if expected_numbers_from_title:
        logger.debug(f"Numbers expected from DB article title '{db_article_title}': {expected_numbers_from_title}") # Using 'logger'
        missing_compared_to_title = sorted(list(set(expected_numbers_from_title) - set(initial_sequence_numbers)))
        if missing_compared_to_title:
            logger.debug(f"Numbers missing from initial sequence compared to title range: {missing_compared_to_title}") # Using 'logger'
            mentions_for_title_gaps = find_and_prioritize_mentions_for_gaps(db_article_content, missing_compared_to_title)
            mentions_for_reconstruction.extend(mentions_for_title_gaps)
            found_numbers_for_title_gaps = {m['parsed_info'].get('main_number') for m in mentions_for_title_gaps if m.get('parsed_info')} # Added None check
            initial_sequence_numbers = sorted(list(set(initial_sequence_numbers).union(found_numbers_for_title_gaps)))
            logger.debug(f"Sequence after attempting to fill title gaps: {initial_sequence_numbers}") # Using 'logger'
        else:
            logger.debug("Initial sequence already satisfies title range (if any).") # Using 'logger'
    else:
        logger.debug("No numeric range found in DB article title.") # Using 'logger'

    internal_gaps_to_fill = []
    if len(initial_sequence_numbers) >= 2:
        for i in range(len(initial_sequence_numbers) - 1):
            start_num, end_num = initial_sequence_numbers[i], initial_sequence_numbers[i+1]
            if end_num > start_num + 1:
                internal_gaps_to_fill.extend(range(start_num + 1, end_num))
    
    if internal_gaps_to_fill:
        current_mention_numbers = {m['parsed_info'].get('main_number') for m in mentions_for_reconstruction if m.get('parsed_info')} # Added None check
        internal_gaps_to_fill = sorted(list(set(internal_gaps_to_fill) - current_mention_numbers))
        logger.debug(f"Remaining internal numeric gaps to fill: {internal_gaps_to_fill}") # Using 'logger'
        if internal_gaps_to_fill:
            mentions_for_internal_gaps = find_and_prioritize_mentions_for_gaps(db_article_content, internal_gaps_to_fill)
            mentions_for_reconstruction.extend(mentions_for_internal_gaps)
            logger.debug(f"Added {len(mentions_for_internal_gaps)} mentions for internal gaps.") # Using 'logger'
    else:
        logger.debug("No further internal numeric gaps identified in the sequence.") # Using 'logger'

    main_delimiters_for_reconstruction = []
    for h_loc in true_headers_locations:
        raw_line = h_loc.get("original_line_text", "")
        match_text = h_loc.get("match_text", "")
        char_offset = raw_line.find(match_text) if raw_line and match_text else 0
        
        main_delimiters_for_reconstruction.append({
            "line_num": h_loc["line_index"] + 1,
            "parsed_header": h_loc.get("parsed_header_details_copy", h_loc.get("parsed_details")), # Ensure parsed_header exists
            "raw_header_line": match_text, 
            "char_offset_in_original_line": max(0, char_offset)
        })

    formatted_mentions_for_reconstruction = []
    for m in mentions_for_reconstruction:
        formatted_mention = m.copy()
        formatted_mention["line_number"] = m["line_index"] + 1
        formatted_mentions_for_reconstruction.append(formatted_mention)

    logger.debug(f"Reconstructing chunks with {len(main_delimiters_for_reconstruction)} main delimiters and {len(formatted_mentions_for_reconstruction)} prioritized mentions.") # Using 'logger'
    
    reconstructed_chunks = article_parser_utils.reconstruct_article_chunks_with_prioritized_mentions(
        original_text=db_article_content,
        main_header_locations=main_delimiters_for_reconstruction,
        prioritized_mentions_input=formatted_mentions_for_reconstruction
    )

    if not reconstructed_chunks:
        logger.warning(f"Chunk reconstruction returned empty for DB article title: '{db_article_title}'.") # Using 'logger'
        if db_article_content and db_article_content.strip():
            logger.debug("Treating non-empty content as a single fallback chunk.") # Using 'logger'
            return [{'type': 'preamble', 'content': db_article_content, 'article_number': None, 
                     'raw_header': 'N/A - Fallback single chunk', 'chunk_index_within_db_article': 0, 
                     'db_article_title_for_chunk': db_article_title}]
        return []

    final_chunks_for_summarization = []
    for i, chunk in enumerate(reconstructed_chunks):
        chunk_content = chunk.get('content_text') or chunk.get('content')
        if chunk_content and chunk_content.strip():
            chunk['chunk_index_within_db_article'] = i
            chunk['db_article_title_for_chunk'] = db_article_title
            final_chunks_for_summarization.append(chunk)
        else:
            logger.debug(f"Skipping empty chunk (index {i}) after reconstruction.") # Using 'logger'
            
    logger.info(f"Processed DB article '{db_article_title}', resulted in {len(final_chunks_for_summarization)} non-empty chunks for summarization.") # Using 'logger'
    return final_chunks_for_summarization

# --- Core DB and Utility Functions (Retained from v2) ---
def fetch_articles_for_consultation(consultation_id, article_db_id=None, db_path=DB_PATH, table_name=TABLE_NAME, content_column=TEXT_COLUMN_NAME):
    logger.info(f"Fetching articles for consultation_id: {consultation_id}{f', article_db_id: {article_db_id}' if article_db_id else ''}") # Using 'logger'
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
        logger.info(f"Fetched {len(articles_data)} articles for consultation_id {consultation_id}{f', article_db_id: {article_db_id}' if article_db_id else ''}.") # Using 'logger'
    except sqlite3.Error as e:
        logger.error(f"Database error fetching articles: {e}", exc_info=True) # Using 'logger'
    except Exception as e:
        logger.error(f"Unexpected error fetching articles: {e}", exc_info=True) # Using 'logger'
    finally:
        if conn:
            conn.close()
    return articles_data

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
            logger.warning(f"No consultation details found for consultation_id {consultation_id}") # Using 'logger'
    except sqlite3.Error as e:
        logger.error(f"Database error fetching consultation details: {e}", exc_info=True) # Using 'logger'
    except Exception as e:
        logger.error(f"Error fetching consultation details: {e}", exc_info=True) # Using 'logger'
    return consultation_title, consultation_url

def check_response_completeness(response_text):
    if not response_text:
        return False
    end_punctuation = ['.', '?', '!', '."', '?"', '!"', '.»', '?»', '! »'] # Corrected '! »'
    is_complete = any(response_text.strip().endswith(punct) for punct in end_punctuation)
    return is_complete

def get_token_count(text, processor):
    """Count tokens in text using the processor's tokenizer."""
    if not text or not isinstance(text, str) or text.strip() == "":
        return 0
    if processor is None or processor.tokenizer is None: # Added check for processor and tokenizer
        logger.error("Tokenizer (processor) not available for get_token_count.")
        return 0
    try:
        inputs = processor.tokenizer(text, return_tensors=None, add_special_tokens=True)
        return len(inputs["input_ids"])
    except Exception as e:
        logger.error(f"Error tokenizing text for count: {e}") # Using 'logger'
        return 0

# --- Summarization Function (Adapted from v2) ---
def summarize_text(model, processor, stage_id: str, initial_llm_prompt_text: str,
                   core_input_data_for_correction: str, original_task_instructions_for_correction: str,
                   target_tokens_for_summary: int, retry_if_truncated=True):
    reasoning_trace_logger.info(f"\n{'='*80}")
    reasoning_trace_logger.info(f"STAGE {stage_id} - SUMMARIZATION CALL")
    reasoning_trace_logger.info(f"{'='*80}")
    reasoning_trace_logger.info(f"PROMPT:\n{initial_llm_prompt_text}")
    reasoning_trace_logger.info(f"\n{'-'*40}")
    
    final_returned_value_for_log = ""
    if not initial_llm_prompt_text or not isinstance(initial_llm_prompt_text, str) or initial_llm_prompt_text.strip() == "":
        logger.warning(f"[Stage {stage_id}] Skipping summarization due to empty or invalid initial_llm_prompt_text.")
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
        logger.debug(f"[Stage {stage_id}] Attempting initial LLM call.")
        inputs = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[-1]
        with torch.inference_mode():
            generation = model.generate(**inputs, max_new_tokens=target_tokens_for_summary, do_sample=False)
            generation = generation[0][input_len:]
        decoded_summary = processor.decode(generation, skip_special_tokens=True)
        is_complete_initial = check_response_completeness(decoded_summary)
        logger.debug(f"[Stage {stage_id}] Initial LLM call completed. Completeness: {is_complete_initial}")

        if retry_if_truncated and not is_complete_initial:
            logger.warning(f"[Stage {stage_id}] Generated response appears to be truncated: '{decoded_summary[-50:]}...'")
            final_returned_value_for_log = decoded_summary # Initialize with truncated before retry

            if stage_id in ["2.1", "2.2", "2.3", "3"]:
                logger.info(f"[Stage {stage_id}] Attempting CONCISE CONTINUATION for truncated response.")
                
                continuation_prompt_text = CONCISE_CONTINUATION_PROMPT_TEMPLATE.format(
                    original_task_instructions=original_task_instructions_for_correction,
                    original_input_data=core_input_data_for_correction, 
                    truncated_response=decoded_summary 
                )
                
                reasoning_trace_logger.info(f"\n--- [Stage {stage_id}] CONCISE CONTINUATION ATTEMPT ---")
                reasoning_trace_logger.info(f"CONTINUATION PROMPT:\n{continuation_prompt_text}")

                messages_continuation = [
                    {"role": "system", "content": [{"type": "text", "text": default_system_prompt_text}]},
                    {"role": "user", "content": [{"type": "text", "text": continuation_prompt_text}]}
                ]
                
                try:
                    inputs_continuation = processor.apply_chat_template(messages_continuation, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
                    input_len_continuation = inputs_continuation["input_ids"].shape[-1]
                    max_tokens_for_continuation = 75 # Keep this relatively small
                    
                    with torch.inference_mode():
                        generation_continuation = model.generate(**inputs_continuation, max_new_tokens=max_tokens_for_continuation, do_sample=False)
                        generation_continuation = generation_continuation[0][input_len_continuation:]
                    
                    continuation_fragment = processor.decode(generation_continuation, skip_special_tokens=True)
                    
                    logger.info(f"[Stage {stage_id}] Initial truncated response: '{decoded_summary}'")
                    logger.info(f"[Stage {stage_id}] Received continuation fragment: '{continuation_fragment}'")
                    reasoning_trace_logger.info(f"CONTINUATION FRAGMENT:\n{continuation_fragment}")

                    if continuation_fragment:
                        original_ending_char = decoded_summary[-1] if decoded_summary else ""
                        processed_fragment = continuation_fragment.lstrip()
                        fragment_starting_char = processed_fragment[0] if processed_fragment else ""

                        if not processed_fragment:
                            logger.info(f"[Stage {stage_id}] Continuation fragment was effectively empty after lstrip.")
                        elif original_ending_char.isspace() and fragment_starting_char and not fragment_starting_char.isspace():
                            decoded_summary += processed_fragment
                        elif original_ending_char and not original_ending_char.isspace() and fragment_starting_char and not fragment_starting_char.isspace():
                            decoded_summary += " " + processed_fragment
                        elif original_ending_char and not original_ending_char.isspace() and fragment_starting_char.isspace():
                            decoded_summary += processed_fragment
                        elif original_ending_char.isspace() and fragment_starting_char.isspace():
                            decoded_summary += processed_fragment[1:] if len(processed_fragment) > 1 else ""
                        elif not decoded_summary:
                            decoded_summary = processed_fragment
                        else:
                            decoded_summary += processed_fragment
                        logger.info(f"[Stage {stage_id}] Combined response after continuation: '{decoded_summary[:200]}...'")
                    else:
                        logger.warning(f"[Stage {stage_id}] Continuation fragment was empty. No changes to response.")

                    is_complete_after_continuation = check_response_completeness(decoded_summary)
                    if not is_complete_after_continuation:
                        logger.warning(f"[Stage {stage_id}] Response STILL incomplete after concise continuation attempt. Final output might be truncated: '{decoded_summary[-50:]}...'")
                        decoded_summary += " [Σημείωση: Η απόπειρα συνέχισης ενδέχεται να μην ολοκλήρωσε πλήρως την απάντηση.]"
                    else:
                        logger.info(f"[Stage {stage_id}] Response complete after concise continuation attempt.")
                    final_returned_value_for_log = decoded_summary

                except Exception as e_cont:
                    logger.error(f"[Stage {stage_id}] Error during concise continuation attempt: {e_cont}", exc_info=True)
                    final_returned_value_for_log = f"{decoded_summary} [Continuation Error: {e_cont}]"
            
            else: # Existing logic for Stage 1 (and any other stages not specified above)
                logger.info(f"[Stage {stage_id}] Using existing shortening correction logic for this stage.")
                specific_constraints_for_stage = ""
                if stage_id == "1":
                    specific_constraints_for_stage = (
                        "- Η περίληψη πρέπει να είναι έως 2-3 προτάσεις το μέγιστο.\\n"
                        "- Πρέπει να περιλαμβάνει τις βασικές αλλαγές σε νόμους, θεσμούς, ή διαδικασίες που αναφέρονται στο άρθρο."
                    )
                # Old stage constraints (2, 3.1, 3.2) removed as they are not relevant for v3's Stage 1 shortening
                # and stages 2.1, 2.2, 2.3, 3 now use continuation.

                # Using the existing dynamic prompt construction for shortening
                correction_prompt_header = (
                    "Η παρακάτω απόκριση που παρήγαγες κόπηκε επειδή πιθανόν ξεπέρασες το όριο των επιτρεπτών χαρακτήρων (tokens):\\n\\n"
                    "--- ΑΡΧΗ ΑΠΟΚΟΜΜΕΝΗΣ ΑΠΟΚΡΙΣΗΣ ---\\n"
                )
                correction_prompt_instructions_header = (
                    "\\n--- ΤΕΛΟΣ ΑΠΟΚΟΜΜΕΝΗΣ ΑΠΟΚΡΙΣΗΣ ---\\n\\n"
                    "Για να δημιουργήσεις αυτή την απόκριση, σου δόθηκαν οι παρακάτω οδηγίες και δεδομένα εισόδου:\\n\\n"
                    "--- ΑΡΧΙΚΕΣ ΟΔΗΓΙΕΣ ΕΡΓΑΣΙΑΣ ---\\n"
                )
                correction_prompt_input_data_header = (
                    "\\n--- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΟΔΗΓΙΩΝ ΕΡΓΑΣΙΑΣ ---\\n\\n"
                    "--- ΑΡΧΙΚΑ ΔΕΔΟΜΕΝΑ ΕΙΣΟΔΟΥ ---\\n"
                )
                correction_prompt_footer = (
                    "\\n--- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΔΕΔΟΜΕΝΩΝ ΕΙΣΟΔΟΥ ---\\n\\n"
                    "ΠΑΡΑΚΑΛΩ ΔΗΜΙΟΥΡΓΗΣΕ ΜΙΑ ΝΕΑ, ΣΥΝΤΟΜΟΤΕΡΗ ΕΚΔΟΧΗ:\\n"
                    "Μελέτησε προσεκτικά την αποκομμένη απόκριση, τις αρχικές οδηγίες και τα αρχικά δεδομένα.\\n"
                    "Η νέα σου απόκριση πρέπει:\\n"
                    "- Να είναι σημαντικά συντομότερη από την προηγούμενη προσπάθεια.\\n"
                    "- Να διατηρεί τα πιο κρίσιμα σημεία σε σχέση με τις αρχικές οδηγίες.\\n"
                    "- Να ολοκληρώνεται σωστά με κατάλληλο σημείο στίξης (π.χ., τελεία).\\n"
                )
                correction_prompt_final_instruction = "\\nΠαρακαλώ γράψε μόνο τη νέα, διορθωμένη απόκριση."
                
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
                
                reasoning_trace_logger.info(f"TRUNCATION DETECTED (Stage {stage_id}) - RETRY PROMPT (SHORTEN):\\n{correction_prompt}")
                reasoning_trace_logger.info(f"\\n{'-'*40}")
                
                logger.debug(f"[Stage {stage_id}] Attempting truncation correction (shortening) retry LLM call.")
                try:
                    retry_inputs = processor.apply_chat_template(retry_messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(model.device)
                    retry_input_len = retry_inputs["input_ids"].shape[-1]
                    max_tokens_for_shortened_summary = max(150, int(target_tokens_for_summary * 0.8)) 
                    
                    with torch.inference_mode():
                        retry_generation = model.generate(**retry_inputs, max_new_tokens=max_tokens_for_shortened_summary, do_sample=False)
                        retry_generation = retry_generation[0][retry_input_len:]
                    retry_summary = processor.decode(retry_generation, skip_special_tokens=True)
                    is_complete_retry = check_response_completeness(retry_summary)
                    logger.debug(f"[Stage {stage_id}] Truncation correction (shortening) retry completed. Completeness: {is_complete_retry}")
                    reasoning_trace_logger.info(f"RETRY (SHORTENED) OUTPUT:\\n{retry_summary}")

                    if is_complete_retry:
                        logger.info(f"[Stage {stage_id}] Shortening retry successful, got a complete response.")
                        decoded_summary = retry_summary + " [Σημείωση: Αυτή η περίληψη συντομεύτηκε αυτόματα λόγω ορίων tokens και προηγούμενης ατελούς απόκρισης.]"
                    else:
                        logger.warning(f"[Stage {stage_id}] Even the shortening retry attempt resulted in a truncated response: '{retry_summary[-50:]}...'")
                        decoded_summary = decoded_summary + " [Σημείωση: Η απόκριση εντοπίστηκε ως πιθανώς ατελής και η προσπάθεια διόρθωσης απέτυχε να την ολοκληρώσει πλήρως.]"
                    final_returned_value_for_log = decoded_summary
                except Exception as e_corr:
                    logger.error(f"[Stage {stage_id}] Error during shortening correction attempt: {e_corr}", exc_info=True)
                    final_returned_value_for_log = f"{decoded_summary} [Shortening Correction Error: {e_corr}]"
        else: # Not retry_if_truncated or is_complete_initial
            final_returned_value_for_log = decoded_summary
            reasoning_trace_logger.info(f"OUTPUT: {final_returned_value_for_log}") # Log initial complete response
            reasoning_trace_logger.info(f"{'='*80}\n")
            return final_returned_value_for_log # Return initial complete response

    except Exception as e:
        logger.error(f"[Stage {stage_id}] Error during summarization: {e}", exc_info=True)
        final_returned_value_for_log = f"Error during summarization: {e}"
        reasoning_trace_logger.info(f"ERROR OUTPUT: {final_returned_value_for_log}")
        reasoning_trace_logger.info(f"{'='*80}\n")
        return None
    
    # This part should only be reached if retry logic modified decoded_summary
    reasoning_trace_logger.info(f"FINAL OUTPUT (after potential retry/continuation): {final_returned_value_for_log}")
    reasoning_trace_logger.info(f"{'='*80}\n")
    return final_returned_value_for_log

# Stage 1 summarization function (largely retained from v2)
def summarize_chunk_stage1(model, processor, chunk_title_line: str, text_chunk_content: str, prompt_template: str):
    if not text_chunk_content or text_chunk_content.strip() == "":
        logger.warning("Empty text chunk content provided to summarize_chunk_stage1.")
        return "Το περιεχόμενο αυτής της ενότητας ήταν κενό."
    
    full_prompt = f"{prompt_template}\n\nΤίτλος Ενότητας: {chunk_title_line}\n\nΚείμενο Ενότητας:\n{text_chunk_content}"
    
    logger.info("Starting Stage 1 model.generate()...") # Changed logger
    import time
    start_time = time.time()
    
    summary = summarize_text(
        model=model,
        processor=processor,
        stage_id="1", # Stage ID for Stage 1
        initial_llm_prompt_text=full_prompt,
        core_input_data_for_correction=text_chunk_content,
        original_task_instructions_for_correction=prompt_template,
        target_tokens_for_summary=300,
        retry_if_truncated=True
    )
    
    end_time = time.time()
    logger.info(f"Stage 1 model.generate() completed in {end_time - start_time:.2f} seconds.") # Changed logger
    
    if summary is None:
        logger.error("Stage 1 summarization failed, returning error message.") # Changed logger
        return "Η περίληψη αυτής της ενότητας απέτυχε."
    
    return summary

# --- Main Narrative Workflow Orchestration Function (New for V3) ---
def run_narrative_summarization_workflow(consultation_id, article_db_id_to_process=None, dry_run=False):
    logger.info(f"=== Starting Narrative Summarization Workflow for consultation_id: {consultation_id} ===")
    
    # Load model (skip if dry run)
    model, processor = None, None
    if not dry_run:
        logger.info("Not a dry run. Proceeding to load model and processor.")
        try:
            model, processor = load_model_and_processor()
            if model is None or processor is None: # Should be caught by raise in load_model_and_processor
                logger.error("Model/processor is None after loading attempt without an exception. This is unexpected.")
                # Handle this unlikely case, though the raise in load_model_and_processor should prevent reaching here
                return { 
                    "individual_article_details": [],
                    "cohesive_summary_stage2_1": "Error: Model load returned None.",
                    "identified_themes_stage2_2": [],
                    "narrative_plan_stage2_3": "Error: Model load returned None.",
                    "final_narrative_summary": "Error: Model load returned None."
                }
            logger.info("Model and processor loading step completed.")
        except Exception as e:
            logger.error(f"Exception caught while trying to load model/processor in workflow: {e}", exc_info=True)
            # Also print to stderr for immediate visibility if logs aren't flushed
            print(f"Exception caught during model/processor loading in workflow: {e}", file=sys.stderr)
            sys.stderr.flush()
            logging.shutdown()
            return { # Return a dictionary for consistent output structure
                "individual_article_details": [],
                "cohesive_summary_stage2_1": f"Error: Model loading failed: {e}",
                "identified_themes_stage2_2": [],
                "narrative_plan_stage2_3": f"Error: Model loading failed: {e}",
                "final_narrative_summary": f"Error: Model loading failed: {e}"
            }

    # === STAGE 1: Individual Article Summarization (largely from v2) ===
    logger.info(f"--- STAGE 1: Individual Article Summarization --- C_ID: {consultation_id}")
    db_article_entries = fetch_articles_for_consultation(consultation_id, article_db_id_to_process, db_path=DB_PATH)
    if not db_article_entries:
        logger.warning(f"No articles found for consultation_id {consultation_id}. Exiting.")
        return { 
            "individual_article_details": [],
            "cohesive_summary_stage2_1": "No articles found.",
            "identified_themes_stage2_2": [],
            "narrative_plan_stage2_3": "No articles found.",
            "final_narrative_summary": "No articles found."
        }
    logger.info(f"Found {len(db_article_entries)} DB articles for C_ID {consultation_id}")

    individual_article_details_for_report = []
    all_individual_summaries_text = []
    dry_run_csv_data = [] # Retained for Stage 1 dry run output

    consultation_title_for_dry_run, consultation_url_for_dry_run = "N/A", "N/A"
    if dry_run:
        conn_details = None
        try:
            conn_details = sqlite3.connect(DB_PATH)
            consultation_title_for_dry_run, consultation_url_for_dry_run = fetch_consultation_details_for_dry_run(conn_details, consultation_id)
        finally:
            if conn_details:
                conn_details.close()

    for db_article_entry in db_article_entries:
        original_db_id = db_article_entry['id']
        original_db_title = db_article_entry['title']
        original_db_content = db_article_entry['content']
        logger.info(f"Processing DB Article ID: {original_db_id}, Title: '{original_db_title}'")

        if not original_db_content or not original_db_content.strip():
            logger.warning(f"DB Article ID: {original_db_id} has empty content. Skipping summarization, adding placeholder.")
            summary_text = "(Εσωτερική σημείωση: Το αρχικό περιεχόμενο αυτής της ενότητας της διαβούλευσης ήταν κενό.)"
            all_individual_summaries_text.append(summary_text)
            # ... (rest of the empty content handling for individual_article_details_for_report & dry_run_csv_data as in v2) ...
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

        sub_article_chunks = get_internally_completed_chunks_for_db_article(original_db_content, original_db_title)
        if not sub_article_chunks:
            logger.warning(f"No processable sub-article chunks for DB Article ID: {original_db_id}. Treating as single block if content existed.")
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
                logger.debug(f"DB Article ID: {original_db_id} - No sub_article_chunks and no fallback content. Continuing.")
                continue 

        for chunk in sub_article_chunks:
            chunk_content_to_summarize = chunk.get('content_text') or chunk.get('content')
            chunk_title_for_log = chunk.get('raw_header') or chunk.get('title_line') or original_db_title
            chunk_article_num_for_log = chunk.get('article_number', 'N/A')
            chunk_idx_for_log = chunk.get('chunk_index_within_db_article', 'N/A')
            logger.info(f"Summarizing chunk: DB_ID={original_db_id}, ChunkIdx={chunk_idx_for_log}, Title='{chunk_title_for_log}', ArtNo={chunk_article_num_for_log}")
            
            wc = article_parser_utils.count_words(chunk_content_to_summarize)
            logger.debug(f"Word count for current chunk: {wc}")

            summary_text = ""
            if dry_run:
                summary_text = f"[Dry Run Stage 1 Summary for DB_ID:{original_db_id}/ChunkIdx:{chunk_idx_for_log}/ArtNo:{chunk_article_num_for_log}]"
                logger.info("Dry run: Skipping actual Stage 1 summarization call.")
            else:
                if model and processor:
                    summary_text = summarize_chunk_stage1(model, processor, chunk_title_for_log, chunk_content_to_summarize, STAGE1_PROMPT_TEMPLATE)
                else:
                    summary_text = "[Error: Model not loaded, cannot summarize Stage 1]"
                    logger.error("Model/processor not available for Stage 1 summarization.")
            
            all_individual_summaries_text.append(summary_text)
            # ... (rest of detail_entry population for individual_article_details_for_report & dry_run_csv_data as in v2) ...
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

    logger.info(f"--- Stage 1 Complete: Generated {len(all_individual_summaries_text)} individual summaries. ---")

    # Prepare concatenated summaries for Stages 2.1, 2.2, 2.3
    valid_stage1_summaries = [s for s in all_individual_summaries_text if s and 
                              "Dry Run Stage 1 Summary" not in s and 
                          "Error: Model not loaded" not in s and 
                          "Το περιεχόμενο αυτής της ενότητας ήταν κενό" not in s and
                          "Η περίληψη αυτής της ενότητας απέτυχε" not in s and
                          "αρχικό περιεχόμενο αυτής της ενότητας της διαβούλευσης ήταν κενό" not in s]
        
    concatenated_stage1_summaries_for_stage2 = ""
    if valid_stage1_summaries:
        concatenated_stage1_summaries_for_stage2 = "\n\n---\n\n".join(valid_stage1_summaries)
        logger.info(f"Concatenated {len(valid_stage1_summaries)} valid Stage 1 summaries for Stage 2 input.")
    else:
        logger.warning("No valid Stage 1 summaries to use for Stage 2. Subsequent stages will be affected.")
        # Initialize placeholder values for subsequent stages if Stage 1 had no valid output
        cohesive_summary_stage2_1 = "No valid Stage 1 summaries available for Stage 2.1."
        identified_themes_stage2_2 = []
        narrative_plan_stage2_3 = "No valid Stage 1 summaries available for Stage 2.3."
        final_narrative_summary = "No valid Stage 1 summaries, cannot generate final narrative."
        # Early exit or return structure reflecting this failure
        return {
            "individual_article_details": individual_article_details_for_report,
            "cohesive_summary_stage2_1": cohesive_summary_stage2_1,
            "identified_themes_stage2_2": identified_themes_stage2_2,
            "narrative_plan_stage2_3": narrative_plan_stage2_3,
            "final_narrative_summary": final_narrative_summary
        }

    # === STAGE 2.1: Cohesive Summary Generation ===
    logger.info(f"--- STAGE 2.1: Cohesive Summary Generation --- C_ID: {consultation_id}")
    cohesive_summary_stage2_1 = ""
    if dry_run:
        cohesive_summary_stage2_1 = f"[Dry Run Stage 2.1 Cohesive Summary for C_ID: {consultation_id}]"
        logger.info("Dry run: Skipping actual Stage 2.1 summarization.")
    else:
        if model and processor:
            logger.info("Starting Stage 2.1 model.generate() for cohesive summary...")
            stage2_1_full_prompt = f"{STAGE2_1_COHESIVE_PROMPT_TEMPLATE}\n\n---\n{concatenated_stage1_summaries_for_stage2}"
            cohesive_summary_stage2_1 = summarize_text(
                        model=model,
                        processor=processor,
                stage_id="2.1",
                initial_llm_prompt_text=stage2_1_full_prompt,
                core_input_data_for_correction=concatenated_stage1_summaries_for_stage2,
                original_task_instructions_for_correction=STAGE2_1_COHESIVE_PROMPT_TEMPLATE,
                target_tokens_for_summary=1500, # As per TODO
                        retry_if_truncated=True
                    )
            if cohesive_summary_stage2_1 is None:
                cohesive_summary_stage2_1 = "Failed to generate Stage 2.1 cohesive summary."
                logger.warning("Stage 2.1 cohesive summary generation failed.")
            else:
                logger.info("Stage 2.1 cohesive summary generated successfully.")
        else:
            cohesive_summary_stage2_1 = "[Error: Model not loaded, cannot generate Stage 2.1 summary]"
            logger.error("Model/processor not available for Stage 2.1 summarization.")
    logger.info(f"--- Stage 2.1 Complete. --- Output length: {len(cohesive_summary_stage2_1)}")

    # === STAGE 2.2: Thematic Identification ===
    logger.info(f"--- STAGE 2.2: Thematic Identification --- C_ID: {consultation_id}")
    identified_themes_stage2_2 = []
    if dry_run:
        identified_themes_stage2_2 = [f"[Dry Run Theme 1 for C_ID: {consultation_id}]", f"[Dry Run Theme 2 for C_ID: {consultation_id}]"]
        logger.info("Dry run: Skipping actual Stage 2.2 thematic identification.")
    else:
        if model and processor:
            logger.info("Starting Stage 2.2 model.generate() for thematic identification...")
            stage2_2_full_prompt = f"{STAGE2_2_THEMATIC_PROMPT_TEMPLATE}\n\n---\n{concatenated_stage1_summaries_for_stage2}"
            themes_text = summarize_text(
                model=model,
                processor=processor,
                stage_id="2.2",
                initial_llm_prompt_text=stage2_2_full_prompt,
                core_input_data_for_correction=concatenated_stage1_summaries_for_stage2,
                original_task_instructions_for_correction=STAGE2_2_THEMATIC_PROMPT_TEMPLATE,
                target_tokens_for_summary=500, # As per TODO
                retry_if_truncated=True
            )
            if themes_text:
                identified_themes_stage2_2 = [theme.strip().lstrip('- ') for theme in themes_text.split('\n') if theme.strip()] # Remove leading hyphens/spaces
                logger.info(f"Stage 2.2 thematic identification successful. Found {len(identified_themes_stage2_2)} themes.")
            else:
                identified_themes_stage2_2 = []
                logger.warning("Stage 2.2 thematic identification failed or returned empty.")
        else:
            identified_themes_stage2_2 = ["[Error: Model not loaded, cannot identify themes]"]
            logger.error("Model/processor not available for Stage 2.2 thematic identification.")
    logger.info(f"--- Stage 2.2 Complete. --- Themes identified: {len(identified_themes_stage2_2)}")

    # === STAGE 2.3: Narrative Planning ===
    logger.info(f"--- STAGE 2.3: Narrative Planning --- C_ID: {consultation_id}")
    narrative_plan_stage2_3 = ""
    if dry_run:
        narrative_plan_stage2_3 = f"[Dry Run Stage 2.3 Narrative Plan for C_ID: {consultation_id}]\n- Section 1: Intro\n- Section 2: Problem\n- Section 3: Solution"
        logger.info("Dry run: Skipping actual Stage 2.3 narrative planning.")
    else:
        if model and processor:
            logger.info("Starting Stage 2.3 model.generate() for narrative planning...")
            stage2_3_full_prompt = f"{STAGE2_3_NARRATIVE_PLAN_PROMPT_TEMPLATE}\n\n---\n{concatenated_stage1_summaries_for_stage2}"
            narrative_plan_stage2_3 = summarize_text(
                model=model,
                processor=processor,
                stage_id="2.3",
                initial_llm_prompt_text=stage2_3_full_prompt,
                core_input_data_for_correction=concatenated_stage1_summaries_for_stage2,
                original_task_instructions_for_correction=STAGE2_3_NARRATIVE_PLAN_PROMPT_TEMPLATE,
                target_tokens_for_summary=700, # As per TODO
                retry_if_truncated=True
            )
            if narrative_plan_stage2_3 is None:
                narrative_plan_stage2_3 = "Failed to generate Stage 2.3 narrative plan."
                logger.warning("Stage 2.3 narrative planning failed.")
            else:
                logger.info("Stage 2.3 narrative plan generated successfully.")
        else:
            narrative_plan_stage2_3 = "[Error: Model not loaded, cannot generate narrative plan]"
            logger.error("Model/processor not available for Stage 2.3 narrative planning.")
    logger.info(f"--- Stage 2.3 Complete. --- Plan length: {len(narrative_plan_stage2_3)}")

    # === STAGE 3: Narrative Exposition ===
    logger.info(f"--- STAGE 3: Narrative Exposition --- C_ID: {consultation_id}")
    final_narrative_summary = ""

    # Check if inputs for Stage 3 are valid
    can_proceed_to_stage3 = True
    if not cohesive_summary_stage2_1 or "Failed to generate" in cohesive_summary_stage2_1 or "Error: Model not loaded" in cohesive_summary_stage2_1 or "No valid Stage 1 summaries" in cohesive_summary_stage2_1:
        logger.warning(f"Cannot proceed to Stage 3: Stage 2.1 summary is invalid or missing. Content: '{cohesive_summary_stage2_1[:100]}...' ")
        can_proceed_to_stage3 = False
    if not identified_themes_stage2_2 and not dry_run : # Allow empty themes in dry run as it's placeholder
        logger.warning("Cannot proceed to Stage 3: Stage 2.2 identified themes are missing.")
        # can_proceed_to_stage3 = False # Decided to allow if plan is present
    if not narrative_plan_stage2_3 or "Failed to generate" in narrative_plan_stage2_3 or "Error: Model not loaded" in narrative_plan_stage2_3 or "No valid Stage 1 summaries" in narrative_plan_stage2_3:
        logger.warning(f"Cannot proceed to Stage 3: Stage 2.3 narrative plan is invalid or missing. Content: '{narrative_plan_stage2_3[:100]}...' ")
        can_proceed_to_stage3 = False

    if not can_proceed_to_stage3 and not dry_run:
        final_narrative_summary = "Skipping Stage 3 due to missing or invalid inputs from previous stages."
        logger.error(final_narrative_summary)
    elif dry_run:
        final_narrative_summary = f"[Dry Run Stage 3 Final Narrative Summary for C_ID: {consultation_id}]"
        logger.info("Dry run: Skipping actual Stage 3 narrative exposition.")
    else:
        if model and processor:
            logger.info("Starting Stage 3 model.generate() for narrative exposition...")
            themes_str_for_prompt = "\n- ".join(identified_themes_stage2_2) if identified_themes_stage2_2 else "Δεν προσδιορίστηκαν συγκεκριμένα θέματα."
            if identified_themes_stage2_2 and not themes_str_for_prompt.startswith("- ") and themes_str_for_prompt:
                 themes_str_for_prompt = "- " + themes_str_for_prompt # Ensure leading hyphen if not already there
            
            stage3_full_prompt = (
                f"{STAGE3_NARRATIVE_EXPOSITION_PROMPT_TEMPLATE_INTRO}\n\n"
                f"--- ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2.1): ---\n{cohesive_summary_stage2_1}\n\n"
                f"--- ΚΥΡΙΑ ΘΕΜΑΤΑ (ΣΤΑΔΙΟ 2.2): ---\n{themes_str_for_prompt}\n\n"
                f"--- ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ (ΣΤΑΔΙΟ 2.3): ---\n{narrative_plan_stage2_3}\n\n"
                f"--- ΤΕΛΙΚΟ ΕΝΗΜΕΡΩΤΙΚΟ ΚΕΙΜΕΝΟ ΠΡΟΣ ΠΟΛΙΤΕΣ: ---"
            )
            
            core_input_for_stage3_correction = (
                f"Summary (Stage 2.1):\n{cohesive_summary_stage2_1}\n\n"
                f"Themes (Stage 2.2):\n{themes_str_for_prompt}\n\n"
                f"Narrative Plan (Stage 2.3):\n{narrative_plan_stage2_3}"
            )

            final_narrative_summary = summarize_text(
            model=model,
            processor=processor,
                stage_id="3",
                initial_llm_prompt_text=stage3_full_prompt,
                core_input_data_for_correction=core_input_for_stage3_correction,
                original_task_instructions_for_correction=STAGE3_NARRATIVE_EXPOSITION_PROMPT_TEMPLATE_INTRO,
                target_tokens_for_summary=2000, # As per TODO
            retry_if_truncated=True
            )
            if final_narrative_summary is None:
                final_narrative_summary = "Failed to generate Stage 3 final narrative summary."
                logger.warning("Stage 3 final narrative summary generation failed.")
            else:
                logger.info("Stage 3 final narrative summary generated successfully.")
        else:
            final_narrative_summary = "[Error: Model not loaded, cannot generate Stage 3 summary]"
            logger.error("Model/processor not available for Stage 3 summarization.")
    logger.info(f"--- Stage 3 Complete. --- Final summary length: {len(final_narrative_summary)}")

    # === Output File Generation (Adapted for V3) ===
    output_dir_name = f"narrative_output_C{consultation_id}_{TIMESTAMP}"
    consultation_output_dir = os.path.join(SCRIPT_DIR, "outputs", output_dir_name) # Centralized outputs folder
    os.makedirs(consultation_output_dir, exist_ok=True)
    logger.info(f"Outputting files to directory: {consultation_output_dir}")

    # Save Stage 1 Dry Run CSV if applicable
    if dry_run and dry_run_csv_data:
        csv_output_filename = os.path.join(consultation_output_dir, f"stage1_dry_run_report_C{consultation_id}_{TIMESTAMP}.csv")
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
            logger.info(f"Stage 1 Dry run CSV report generated: {csv_output_filename}")
        except IOError as e:
            logger.error(f"Error writing Stage 1 dry run CSV: {e}", exc_info=True)
    
    # Save all key outputs to text files
    outputs_to_save = {
        f"final_narrative_summary_C{consultation_id}_{TIMESTAMP}.txt": final_narrative_summary,
        f"stage2_1_cohesive_summary_C{consultation_id}_{TIMESTAMP}.txt": cohesive_summary_stage2_1,
        f"stage2_2_themes_C{consultation_id}_{TIMESTAMP}.txt": "\n".join(identified_themes_stage2_2) if isinstance(identified_themes_stage2_2, list) else str(identified_themes_stage2_2),
        f"stage2_3_narrative_plan_C{consultation_id}_{TIMESTAMP}.txt": narrative_plan_stage2_3,
    }

    for filename, content in outputs_to_save.items():
        try:
            with open(os.path.join(consultation_output_dir, filename), 'w', encoding='utf-8') as f:
                f.write(str(content)) # Ensure content is string
            logger.info(f"Successfully wrote: {filename}")
        except IOError as e:
            logger.error(f"Error writing output file {filename}: {e}", exc_info=True)
    
    # Save Stage 1 detailed report as JSON
    stage1_report_filename = os.path.join(consultation_output_dir, f"stage1_individual_summaries_report_C{consultation_id}_{TIMESTAMP}.json")
    try:
        with open(stage1_report_filename, 'w', encoding='utf-8') as f:
            json.dump(individual_article_details_for_report, f, ensure_ascii=False, indent=4)
        logger.info(f"Stage 1 detailed report JSON saved: {stage1_report_filename}")
    except IOError as e:
        logger.error(f"Error writing Stage 1 report JSON: {e}", exc_info=True)
    except TypeError as e:
        logger.error(f"TypeError writing Stage 1 report JSON (check data types): {e}", exc_info=True)

    logger.info(f"=== Narrative Summarization Workflow Complete for C_ID: {consultation_id} ===")
    
    return {
        "individual_article_details": individual_article_details_for_report,
        "cohesive_summary_stage2_1": cohesive_summary_stage2_1,
        "identified_themes_stage2_2": identified_themes_stage2_2,
        "narrative_plan_stage2_3": narrative_plan_stage2_3,
        "final_narrative_summary": final_narrative_summary
    }

def main():
    global DB_PATH, SCRIPT_DIR
    cli = argparse.ArgumentParser(description="Orchestrate Narrative Summarization Workflow for a given consultation.") # Updated desc
    cli.add_argument("--consultation_id", type=int, required=True, help="ID of the consultation to process.")
    cli.add_argument("--article_db_id", type=int, default=None, help="Optional: Specific DB article ID to process within the consultation.")
    cli.add_argument("--dry_run", action='store_true', help="Perform a dry run: process data, log, generate placeholders, but don't call external model.")
    cli.add_argument("--debug", action='store_true', help="Enable debug level logging to console.") # Simplified debug help
    cli.add_argument("--db-path", type=str, default=DB_PATH, help=f"Path to the SQLite database file. Default: {DB_PATH}")
    # SCRIPT_DIR will be the root for the 'outputs' subfolder and the main log file.
    # No explicit --output-root-dir, as it's derived from script location and an 'outputs' subdir is created.
    args = cli.parse_args()

    DB_PATH = args.db_path
    # SCRIPT_DIR is already defined globally based on __file__
    
    # Configure console handler for debug mode
    if args.debug:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - Func: %(funcName)s - Line: %(lineno)d - %(message)s')
        console_handler.setFormatter(formatter)
        if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
            logger.addHandler(console_handler)
            logger.info("DEBUG mode enabled: Logging to console.")
        if not any(isinstance(h, logging.StreamHandler) for h in reasoning_trace_logger.handlers): # Also add to reasoning logger if desired
            reasoning_trace_logger.addHandler(console_handler) 

    logger.info(f"Script 'orchestrate_summarization_v3.py' started with args: {args}")
    logger.info(f"Using database: {DB_PATH}")
    logger.info(f"Main log file: {LOG_FILE_PATH}")

    start_time_main = datetime.datetime.now()
    # Call the new main workflow function
    results = run_narrative_summarization_workflow(args.consultation_id, article_db_id_to_process=args.article_db_id, dry_run=args.dry_run)
    end_time_main = datetime.datetime.now()
    elapsed_time_main = (end_time_main - start_time_main).total_seconds()

    logger.info(f"Script finished after {elapsed_time_main:.2f} seconds.")

    if args.debug and results:
        logger.info("Workflow Results Preview:")
        logger.info(f"  Cohesive Summary (2.1) Preview: {str(results.get('cohesive_summary_stage2_1'))[:200]}...")
        logger.info(f"  Identified Themes (2.2) Preview: {results.get('identified_themes_stage2_2')[:3]}...")
        logger.info(f"  Narrative Plan (2.3) Preview: {str(results.get('narrative_plan_stage2_3'))[:200]}...")
        logger.info(f"  Final Narrative Summary (3) Preview: {str(results.get('final_narrative_summary'))[:200]}...")

if __name__ == "__main__":
    main() 