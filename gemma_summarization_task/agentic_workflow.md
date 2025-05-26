# Gemma Summarization Task: Agentic Workflow

## Overview
This document maps the agentic workflow of the summarization task using the Gemma 3-4B-IT model, including the prompts used at each stage, decision points, and branching logic.

## Workflow with Decision Points

```
Database Extraction
└── Extract articles for target consultation_id
    └── Process each article for Stage 1
```

### Stage 1: Individual Article Summarization
```
FOR each article in consultation_id:
    IF article content is empty:
        Set summary = "Το αρχικό περιεχόμενο του άρθρου ήταν κενό ή μη έγκυρο."
    ELSE:
        Generate summary with Stage 1 prompt
        
        IF check_response_completeness(summary) == FALSE:
            // Truncation detected
            Generate shorter summary with truncation correction prompt
            
            IF check_response_completeness(shorter_summary):
                Set summary = shorter_summary + "[Note: This summary was automatically shortened due to token limits]"
            ELSE:
                Set summary = original_summary + "[Note: Response was identified as potentially truncated]"
                
    Add summary to individual_article_details
    Add summary to all_individual_summaries_text
```

### Stage 2: Cohesive Summary Generation
```
IF no valid summaries in all_individual_summaries_text:
    Set final_cohesive_summary = "No valid individual summaries were available"
ELSE:
    concatenated_summaries = join valid individual summaries
    Generate final_cohesive_summary with Stage 2 prompt
    
    IF check_response_completeness(final_cohesive_summary) == FALSE:
        // Truncation detected
        Generate shorter cohesive_summary with truncation correction prompt
        
        IF check_response_completeness(shorter_cohesive_summary):
            Set final_cohesive_summary = shorter_cohesive_summary + "[Note: This summary was automatically shortened due to token limits]"
        ELSE:
            Set final_cohesive_summary = original_cohesive_summary + "[Note: Response was identified as potentially truncated]"
```

### Stage 3.1: Missing Information Detection
```
IF final_cohesive_summary is invalid or failed:
    Skip Stage 3.1
ELSE:
    FOR each article_detail in individual_article_details:
        IF article content is empty OR stage1_summary is invalid:
            Set note_text = appropriate error message
        ELSE:
            Generate note_text with Stage 3.1 prompt
            
            IF check_response_completeness(note_text) == FALSE:
                // Truncation detected
                Generate shorter note_text with truncation correction prompt
                
                IF check_response_completeness(shorter_note_text):
                    Set note_text = shorter_note_text + "[Note: This note was automatically shortened due to token limits]"
                ELSE:
                    Set note_text = original_note_text + "[Note: Response was identified as potentially truncated]"
        
        IF note_text is not empty AND note_text != "Δεν εντοπίστηκαν σημαντικές παραλείψεις σε σχέση με αυτό το άρθρο":
            Add note_text to missing_info_notes
```

### Stage 3.2: Final Summary Refinement
```
IF missing_info_notes is empty:
    Set refined_final_summary = final_cohesive_summary
ELSE:
    Prepare notes_for_refinement_input
    
    IF notes_for_refinement_input has content AND final_cohesive_summary is valid:
        Generate refined_final_summary with Stage 3.2 prompt
        
        IF check_response_completeness(refined_final_summary) == FALSE:
            // Truncation detected
            Generate shorter refined_final_summary with truncation correction prompt
            
            IF check_response_completeness(shorter_refined_final_summary):
                Set refined_final_summary = shorter_refined_final_summary + "[Note: This summary was automatically shortened due to token limits]"
            ELSE:
                Set refined_final_summary = original_refined_final_summary + "[Note: Response was identified as potentially truncated]"
    ELSE:
        Set refined_final_summary = final_cohesive_summary
```

## Visual Workflow Diagram with Context Flow

```
┌───────────────────────┐
│    Database Query     │
│  Extract Articles by  │
│    consultation_id    │
└──────────┬────────────┘
           │
           │ article content
           ▼
┌───────────────────────┐
│       STAGE 1         │
│  Individual Article   │──┐
│     Summarization     │  │
└──────────┬────────────┘  │
           │               │ Store in individual_article_details
           │ individual    │ {id, content, summary}
           │ summaries     │
           ▼               │
┌───────────────────────┐  │
│       STAGE 2         │  │
│   Cohesive Summary    │  │
│      Generation       │  │
└──────────┬────────────┘  │
           │               │
           │ cohesive      │
           │ summary       │
           ▼               │
┌───────────────────────┐  │
│      STAGE 3.1        │◄─┘
│  Missing Information  │
│      Detection        │
│                       │
│  ┌─────────────────┐  │
│  │ For each article│  │
│  │┌───────────────┐│  │
│  ││ Original Text ││  │
│  │└───────┬───────┘│  │
│  │        │        │  │
│  │        ▼        │  │
│  │┌───────────────┐│  │
│  ││Stage 1 Summary││  │
│  │└───────┬───────┘│  │
│  │        │        │  │
│  │        ▼        │  │
│  │┌───────────────┐│  │
│  ││Stage 2 Summary││  │
│  │└───────┬───────┘│  │
│  │        │        │  │
│  │        ▼        │  │
│  │┌───────────────┐│  │
│  ││Missing Info   ││  │
│  ││    Note       ││  │
│  │└───────────────┘│  │
│  └─────────────────┘  │
└──────────┬────────────┘
           │
           │ missing info notes
           │ (filtered - only non-empty)
           ▼
┌───────────────────────┐
│      STAGE 3.2        │
│      Refinement       │
│                       │
│  ┌─────────────────┐  │
│  │    Context:     │  │
│  │┌───────────────┐│  │
│  ││Stage 2 Summary││  │
│  │└───────┬───────┘│  │
│  │        │        │  │
│  │        ▼        │  │
│  │┌───────────────┐│  │
│  ││Stage 1 + Notes││  │
│  │└───────────────┘│  │
│  └─────────────────┘  │
└──────────┬────────────┘
           │
           │ refined final summary
           ▼
┌───────────────────────┐
│     Final Output      │
│ (summary_output.txt)  │
└───────────────────────┘
```

### Decision Flow Diagram

```
┌─────────────┐     ┌──────────────────┐
│ Extract     │────►│ For each article │
│ Articles    │     └────────┬─────────┘
└─────────────┘              │
                             ▼
                      ┌─────────────┐
                      │ Empty       │
                      │ Content?    │
                      └──┬───────┬──┘
                         │       │
                      Yes│       │No
                         │       │
                         ▼       ▼
┌───────────────┐    ┌─────────────────────┐
│ Error Message │    │ Generate Stage 1    │
│               │    │ Summary             │
└───────┬───────┘    └─────────┬───────────┘
        │                      │
        │                      ▼
        │             ┌─────────────────┐
        │             │ Is summary      │
        │             │ truncated?      │
        │             └────┬────────┬───┘
        │                  │        │
        │               Yes│        │No
        │                  │        │
        │                  ▼        │
        │      ┌───────────────────┐│
        │      │ Generate shorter  ││
        │      │ summary           ││
        │      └──────┬────────────┘│
        │             │             │
        │             ▼             │
        │    ┌─────────────────┐    │
        │    │ Retry truncated?│    │
        │    └────┬────────┬───┘    │
        │         │        │        │
        │      Yes│        │No      │
        │         │        │        │
        │         ▼        ▼        │
        │ ┌───────────┐ ┌────────┐  │
        │ │Shorter    │ │Mark as │  │
        │ │with note  │ │truncated│ │
        │ └───────────┘ └────────┘  │
        │         │        │        │
        └─────────┼────────┼────────┘
                  │        │
                  ▼        ▼
         ┌─────────────────────────┐
         │ Collect all Stage 1     │
         │ summaries               │
         └───────────┬─────────────┘
                     │
                     ▼
              ┌─────────────┐
              │ Any valid   │
              │ summaries?  │
              └──┬───────┬──┘
                 │       │
               No│       │Yes
                 │       │
                 ▼       ▼
  ┌───────────────┐   ┌────────────────────┐
  │ Error message │   │ Generate Stage 2   │
  │               │   │ cohesive summary   │
  └───────────────┘   └──────────┬─────────┘
                                 │
                                 ▼
                      ┌────────────────────┐
                      │ Check truncation & │
                      │ retry if needed    │
                      └──────────┬─────────┘
                                 │
                                 ▼
                      ┌────────────────────┐
                      │Stage 3.1: For each │
                      │article, check for  │
                      │missing information │
                      └──────────┬─────────┘
                                 │
                                 ▼
                      ┌────────────────────┐
                      │ Filter out empty   │
                      │ notes              │
                      └──────────┬─────────┘
                                 │
                                 ▼
                      ┌────────────────────┐
                      │ Any substantive    │
                      │ notes?             │
                      └───┬────────────┬───┘
                          │            │
                        No│            │Yes
                          │            │
                          │            ▼
                          │   ┌────────────────────┐
                          │   │ Generate Stage 3.2 │
                          │   │ refined summary    │
                          │   └──────────┬─────────┘
                          │              │
                          │              ▼
                          │   ┌────────────────────┐
                          │   │ Check truncation & │
                          │   │ retry if needed    │
                          │   └──────────┬─────────┘
                          │              │
                          └──────────────┼──────────┐
                                         │          │
                                         ▼          │
                             ┌────────────────────┐ │
                             │ Write all to       │◄┘
                             │ summary_output.txt │
                             └────────────────────┘
```

## Prompts by Stage

### Stage 1: Individual Articles Summarization
**Description**: Summarizes each article individually to create concise summaries (up to 3 sentences)
**Model**: Gemma 3-4B-IT
**Target**: 300 tokens max per summary

**Prompt (Greek)**:
```
Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω άρθρου στα Ελληνικά, σε απλή γλώσσα, 
κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως 3 προτάσεις.
Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες.
Οι περιλήψεις πρέπει να είναι όσο πιο σύντομες γίνεται, διατηρώντας την ουσία του κειμένου και να μην είναι παραπάνω απο 3 προτάσεις σε μήκος.
Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης, μη βάζεις εισαγωγή στη περίψη απλώς γράψε την:

[Original Article Content]
```

**Truncation Correction Prompt (Greek)**:
```
Η περίληψή σου κόπηκε επειδή ξεπέρασες το όριο λέξεων. Παρακαλώ εξέταση τη περίληψη σου και τα δεδομένα που χρησιμοποίησες για να την παράξεις και κάνε τη συντομότερη για να χωρέσει μέσα στο κείμενο. Διατήρησε τα ουσιαστικά σημεία του κειμένου, αλλά γράψε τα με λιγότερες λέξεις από τη προηγούμενου σου προσπάθεια.
```

### Stage 2: Cohesive Summary Generation
**Description**: Combines all individual article summaries into a coherent overall summary
**Model**: Gemma 3-4B-IT 
**Target**: 1100 tokens max

**Prompt (Greek)**:
```
Οι παρακάτω είναι ατομικές περιλήψεις πολλαπλών άρθρων από μία ενιαία διαβούλευση. 
Παρακαλώ συνδυάστε τις σε ένα ενιαίο, συνεκτικό και περιεκτικό κείμενο στα Ελληνικά που αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου. 
Στοχεύστε σε μια περιεκτική επισκόπηση περίπου 350 λέξεων και 6-7 παραγράφων.

---
[Concatenated Stage 1 Summaries]
```

**Truncation Correction Prompt (Greek)**:
```
Η περίληψή σου κόπηκε στη μέση. Παρακαλώ δώσε μια συντομότερη περίληψη που ολοκληρώνεται σωστά και τελειώνει με τελεία. Διατήρησε τα κύρια σημεία, αλλά μείωσε την έκταση.
```

### Stage 3.1: Missing Information Detection
**Description**: Identifies any important information that may be missing from the Stage 2 summary
**Model**: Gemma 3-4B-IT
**Target**: 300 tokens max per note

**Prompt (Greek)**:
```
Είσαι ένας βοηθός ανάλυσης κειμένων. Σου παρέχονται τρία κείμενα: ένα 'Αρχικό Άρθρο', η 'Περίληψη Άρθρου (Στάδιο 1)' γι' αυτό το άρθρο, 
και μια 'Τελική Συνολική Περίληψη (Στάδιο 2)' που συνοψίζει πολλά άρθρα, συμπεριλαμβανομένου αυτού.

Ο σκοπός σου είναι να ελέγξεις αν υπάρχει κάποια σημαντική πληροφορία στο 'Αρχικό Άρθρο' που πιστεύεις ότι λείπει από την 'Τελική Συνολική Περίληψη (Στάδιο 2)'. 
Εστίασε σε βασικά σημεία, αλλαγές σε νόμους, θεσμούς, ή σημαντικές επιπτώσεις που αναφέρονται στο 'Αρχικό Άρθρο' αλλά δεν καλύπτονται επαρκώς στην 'Τελική Συνολική Περίληψη (Στάδιο 2)'.

Αν εντοπίσεις τέτοια σημαντική πληροφορία που λείπει, διατύπωσε μια σύντομη σημείωση στα Ελληνικά. Η σημείωση πρέπει να είναι μία πρόταση και να μην υπερβαίνει τους 300 τόκενς. 
Αν δεν εντοπίσεις κάποια σημαντική παράλειψη, απάντησε ακριβώς: 'Δεν εντοπίστηκαν σημαντικές παραλείψεις σε σχέση με αυτό το άρθρο.'

ΑΡΧΙΚΟ ΑΡΘΡΟ:
--- ΑΡΧΗ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---
[Original Article Content]
--- ΤΕΛΟΣ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---

ΠΕΡΙΛΗΨΗ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1):
--- ΑΡΧΗ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---
[Stage 1 Summary for this article]
--- ΤΕΛΟΣ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---

ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):
--- ΑΡΧΗ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---
[Stage 2 Cohesive Summary]
--- ΤΕΛΟΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---

Σημείωση σχετικά με πιθανές σημαντικές παραλείψεις (1 πρόταση, έως 300 τόκενς):
```

**Truncation Correction Prompt (Greek)**:
```
Η σημείωσή σου κόπηκε στη μέση. Παρακαλώ δώσε μια συντομότερη σημείωση που ολοκληρώνεται σωστά και τελειώνει με τελεία. Διατήρησε τα κύρια σημεία, αλλά μείωσε την έκταση.
```

### Stage 3.2: Final Cohesive Summary Refinement
**Description**: Uses the notes from Stage 3.1 to refine the Stage 2 summary
**Model**: Gemma 3-4B-IT
**Target**: Same token limit as Stage 2 (1100 tokens)

**Prompt (Greek)**:
```
Είσαι ένας βοηθός συγγραφής και επιμέλειας κειμένων. Σου παρέχονται τα εξής:
1. Μια 'Αρχική Τελική Συνολική Περίληψη (Στάδιο 2)' μιας διαβούλευσης.
2. Ένα σύνολο από 'Συνδυασμένες Περιλήψεις Άρθρων (Στάδιο 1) και Σημειώσεις'. Κάθε σημείωση υποδεικνύει πιθανές σημαντικές πληροφορίες από το αρχικό άρθρο που ενδέχεται να λείπουν ή να μην τονίζονται επαρκώς στην 'Αρχική Τελική Συνολική Περίληψη (Στάδιο 2)'.

Ο σκοπός σου είναι να αναθεωρήσεις την 'Αρχική Τελική Συνολική Περίληψη (Στάδιο 2)' λαμβάνοντας υπόψη τις πληροφορίες και τις παρατηρήσεις που περιέχονται στις 'Συνδυασμένες Περιλήψεις Άρθρων (Στάδιο 1) και Σημειώσεις'. 
Η αναθεωρημένη περίληψη πρέπει να ενσωματώνει τα σημαντικά σημεία που επισημάνθηκαν, διατηρώντας τη συνοχή, την ακρίβεια και τη συντομία. Το τελικό κείμενο πρέπει να είναι στα Ελληνικά.

ΑΡΧΙΚΗ ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):
--- ΑΡΧΗ ΑΡΧΙΚΗΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---
[Stage 2 Cohesive Summary]
--- ΤΕΛΟΣ ΑΡΧΙΚΗΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---

ΣΥΝΔΥΑΣΜΕΝΕΣ ΠΕΡΙΛΗΨΕΙΣ ΑΡΘΡΩΝ (ΣΤΑΔΙΟ 1) ΚΑΙ ΣΗΜΕΙΩΣΕΙΣ:
--- ΑΡΧΗ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---
[Combined Stage 1 Summaries with Stage 3.1 Notes]
--- ΤΕΛΟΣ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---

ΠΑΡΑΚΑΛΩ ΠΑΡΕΧΕΤΕ ΤΗΝ ΑΝΑΘΕΩΡΗΜΕΝΗ ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ:
```

**Truncation Correction Prompt (Greek)**:
```
Η αναθεωρημένη περίληψή σου κόπηκε στη μέση. Παρακαλώ δώσε μια συντομότερη περίληψη που ολοκληρώνεται σωστά και τελειώνει με τελεία. Διατήρησε τα κύρια σημεία, αλλά μείωσε την έκταση.
```

## Key Validation Function

### check_response_completeness(response_text)
This function checks if a response ends properly with a sentence terminator:
```python
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
```

## Truncation Handling and Correction Prompts (Revised Structure)

The system now uses a `stage_id` (e.g., "1", "2", "3.1", "3.2") passed to the `summarize_text` function to explicitly track the current workflow stage. This allows for precise context provision and instruction tailoring during truncation correction.

When a response is detected as truncated, a detailed correction prompt is generated. This prompt provides the model with comprehensive context to help it produce a valid, shorter response.

### General Structure of Truncation Correction Prompts

The correction prompt systematically presents the following information to the model:

1.  **The Truncated Output**: Shows the model its previous, incomplete attempt.
2.  **The Original Task Instructions**: Reminds the model of the specific goal for the current stage.
3.  **The Core Input Data**: Provides the exact data the model was working with when it produced the truncated output.
4.  **New Corrective Guidance**: Instructs the model to create a shorter, complete version, including stage-specific length and content constraints.

**Generic Template (Derived from `run_summarization.py` logic):**

```
Η παρακάτω απόκριση που παρήγαγες κόπηκε επειδή πιθανόν ξεπέρασες το όριο των επιτρεπτών χαρακτήρων (tokens):

--- ΑΡΧΗ ΑΠΟΚΟΜΜΕΝΗΣ ΑΠΟΚΡΙΣΗΣ ---
[Truncated Output - placeholder for {decoded_summary}]
--- ΤΕΛΟΣ ΑΠΟΚΟΜΜΕΝΗΣ ΑΠΟΚΡΙΣΗΣ ---

Για να δημιουργήσεις αυτή την απόκριση, σου δόθηκαν οι παρακάτω οδηγίες και δεδομένα εισόδου:

--- ΑΡΧΙΚΕΣ ΟΔΗΓΙΕΣ ΕΡΓΑΣΙΑΣ ---
[Original Task Instructions - placeholder for {original_task_instructions_for_correction}]
--- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΟΔΗΓΙΩΝ ΕΡΓΑΣΙΑΣ ---

--- ΑΡΧΙΚΑ ΔΕΔΟΜΕΝΑ ΕΙΣΟΔΟΥ ---
[Core Input Data - placeholder for {core_input_data_for_correction}]
--- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΔΕΔΟΜΕΝΩΝ ΕΙΣΟΔΟΥ ---

ΠΑΡΑΚΑΛΩ ΔΗΜΙΟΥΡΓΗΣΕ ΜΙΑ ΝΕΑ, ΣΥΝΤΟΜΟΤΕΡΗ ΕΚΔΟΧΗ:
Μελέτησε προσεκτικά την αποκομμένη απόκριση, τις αρχικές οδηγίες και τα αρχικά δεδομένα.
Η νέα σου απόκριση πρέπει:
- Να είναι σημαντικά συντομότερη από την προηγούμενη προσπάθεια.
- Να διατηρεί τα πιο κρίσιμα σημεία σε σχέση με τις αρχικές οδηγίες.
- Να ολοκληρώνεται σωστά με κατάλληλο σημείο στίξης (π.χ., τελεία).
[Stage-Specific Constraints - placeholder for {specific_constraints_for_stage}]
Παρακαλώ γράψε μόνο τη νέα, διορθωμένη απόκριση.
```

**System Prompt for Retry:**
`Είσαι ένας εξυπηρετικός βοηθός. Η προηγούμενη απόκρισή σου ήταν ατελής (αποκομμένη). Παρακαλώ διόρθωσέ την ακολουθώντας τις νέες οδηγίες και λαμβάνοντας υπόψη το παρεχόμενο πλαίσιο.`

### Justification for Context Elements in Correction Prompts:

*   **Truncated Output (`{decoded_summary}`):**
    *   **Why:** Allows the model to see its own error and understand what "went wrong" (i.e., where it got cut off). This provides a direct reference point for what needs to be fixed.
*   **Original Task Instructions (`{original_task_instructions_for_correction}`):**
    *   **Why:** Reinforces the primary goal of the summarization/note generation task for the current stage. This ensures the model doesn't deviate from the original purpose while trying to shorten the response.
*   **Core Input Data (`{core_input_data_for_correction}`):**
    *   **Why:** Provides the exact source material the model used for its initial, truncated attempt. This is crucial for the model to re-evaluate the content and select the most important information to fit within a shorter limit, ensuring factual consistency.
*   **New Corrective Guidance & Stage-Specific Constraints (`{specific_constraints_for_stage}`):**
    *   **Why:** Gives explicit instructions on *how* to fix the problem (be shorter, end properly) and provides concrete, stage-relevant targets (e.g., sentence count, word count, key content focus). This guides the model towards a successful correction.

## Improvement Process Flow

1. **Truncation Detection and Correction**
   - Applied to all generated responses (Stage 1, 2, 3.1, and 3.2)
   - When a response is truncated (doesn't end with proper punctuation):
     - Make a second attempt with reduced token limit
     - If still truncated, mark it as such for transparency
   
2. **Empty Notes Filtering**
   - In Stage 3.1, only non-empty notes that indicate actual missing information are kept
   - Notes stating "Δεν εντοπίστηκαν σημαντικές παραλείψεις" are filtered out
   - This ensures Stage 3.2 only receives meaningful feedback for refinement 

### Stage-Specific Details for Truncation Correction:

#### Stage 1: Individual Article Summary Correction (`stage_id="1"`)

*   **Original Task Instructions (`stage1_task_instructions_el` from `run_summarization.py`):** The initial prompt asking for a 3-sentence summary of an article.
    ```
    Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω άρθρου στα Ελληνικά, σε απλή γλώσσα, 
    κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως 3 προτάσεις.
    Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες.
    Οι περιλήψεις πρέπει να είναι όσο πιο σύντομες γίνεται, διατηρώντας την ουσία του κειμένου και να μην είναι παραπάνω απο 3 προτάσεις σε μήκος.
    Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης, μη βάζεις εισαγωγή στη περίψη απλώς γράψε την:
    ```
*   **Core Input Data (`current_core_input_s1` from `run_summarization.py`):** The content of the individual article (`article_content`). This would be framed within the correction prompt as:
    ```
    --- ΑΡΧΙΚΑ ΔΕΔΟΜΕΝΑ ΕΙΣΟΔΟΥ ---
    [Content of the specific article]
    --- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΔΕΔΟΜΕΝΩΝ ΕΙΣΟΔΟΥ ---
    ```
*   **Stage-Specific Constraints (`specific_constraints_for_stage` from `run_summarization.py`):**
    ```
    - Η περίληψη πρέπει να είναι έως 2-3 προτάσεις το μέγιστο.
    - Πρέπει να περιλαμβάνει τις βασικές αλλαγές σε νόμους, θεσμούς, ή διαδικασίες που αναφέρονται στο άρθρο.
    ```

#### Stage 2: Cohesive Summary Correction (`stage_id="2"`)

*   **Original Task Instructions (`stage2_task_instructions_el` from `run_summarization.py`):** The initial prompt asking to combine individual summaries into a cohesive text.
    ```
    Οι παρακάτω είναι ατομικές περιλήψεις πολλαπλών άρθρων από μία ενιαία διαβούλευση. 
    Παρακαλώ συνδυάστε τις σε ένα ενιαίο, συνεκτικό και περιεκτικό κείμενο στα Ελληνικά που αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου. 
    Στοχεύστε σε μια περιεκτική επισκόπηση περίπου 350 λέξεων και 6-7 παραγράφων.
    ```
*   **Core Input Data (`current_core_input_s2` from `run_summarization.py`):** The concatenated string of all valid Stage 1 summaries (`concatenated_summaries`). This would be framed as:
    ```
    --- ΑΡΧΙΚΑ ΔΕΔΟΜΕΝΑ ΕΙΣΟΔΟΥ ---
    [Concatenated Stage 1 Summaries with "\n\n---\n\n" separators]
    --- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΔΕΔΟΜΕΝΩΝ ΕΙΣΟΔΟΥ ---
    ```
*   **Stage-Specific Constraints (`specific_constraints_for_stage` from `run_summarization.py`):**
    ```
    - Η συνολική περίληψη πρέπει να αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου.
    - Πρέπει να περιορίζεται σε περίπου 200-250 λέξεις και 3-4 παραγράφους το μέγιστο.
    - Πρέπει να διατηρεί τη συνοχή και την περιεκτικότητα.
    - Πρέπει να είναι κατανοητή σε πολίτες χωρίς εξειδικευμένες νομικές γνώσεις.
    ```

#### Stage 3.1: Missing Information Note Correction (`stage_id="3.1"`)

*   **Original Task Instructions (`original_task_instructions_for_correction_s3_1` which is `stage3_1_task_instructions_template_el` from `run_summarization.py`):** The *template* of the initial prompt for identifying missing info. This template shows the structure and the roles of the three input texts.
    ```
    Είσαι ένας βοηθός ανάλυσης κειμένων. Σου παρέχονται τρία κείμενα: ένα 'Αρχικό Άρθρο', η 'Περίληψη Άρθρου (Στάδιο 1)' γι' αυτό το άρθρο, 
    και μια 'Τελική Συνολική Περίληψη (Στάδιο 2)' που συνοψίζει πολλά άρθρα, συμπεριλαμβανομένου αυτού.

    Ο σκοπός σου είναι να ελέγξεις αν υπάρχει κάποια σημαντική πληροφορία στο 'Αρχικό Άρθρο' που πιστεύεις ότι λείπει από την 'Τελική Συνολική Περίληψη (Στάδιο 2)'. 
    Εστίασε σε βασικά σημεία, αλλαγές σε νόμους, θεσμούς, ή σημαντικές επιπτώσεις που αναφέρονται στο 'Αρχικό Άρθρο' αλλά δεν καλύπτονται επαρκώς στην 'Τελική Συνολική Περίληψη (Στάδιο 2)'.

    Αν εντοπίσεις τέτοια σημαντική πληροφορία που λείπει, διατύπωσε μια σύντομη σημείωση στα Ελληνικά. Η σημείωση πρέπει να είναι μία πρόταση και να μην υπερβαίνει τους 300 τόκενς. 
    Αν δεν εντοπίσεις κάποια σημαντική παράλειψη, απάντησε ακριβώς: 'Δεν εντοπίστηκαν σημαντικές παραλείψεις σε σχέση με αυτό το άρθρο.'

    ΑΡΧΙΚΟ ΑΡΘΡΟ:
    --- ΑΡΧΗ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---
    {original_article_content_placeholder}
    --- ΤΕΛΟΣ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---

    ΠΕΡΙΛΗΨΗ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1):
    --- ΑΡΧΗ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---
    {stage1_summary_placeholder}
    --- ΤΕΛΟΣ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---

    ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):
    --- ΑΡΧΗ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---
    {final_cohesive_summary_placeholder}
    --- ΤΕΛΟΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---

    Σημείωση σχετικά με πιθανές σημαντικές παραλείψεις (1 πρόταση, έως 300 τόκενς):
    ```
*   **Core Input Data (`current_core_input_s3_1` from `run_summarization.py`):** A concatenated string containing the `original_article_content`, the `stage1_summary` for that article, and the `final_cohesive_summary` (Stage 2), each clearly labeled with start/end markers. This would be framed as:
    ```
    --- ΑΡΧΙΚΑ ΔΕΔΟΜΕΝΑ ΕΙΣΟΔΟΥ ---
    ΑΡΧΙΚΟ ΑΡΘΡΟ:
    --- ΑΡΧΗ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---
    [Content of the specific Original Article]
    --- ΤΕΛΟΣ ΑΡΧΙΚΟΥ ΑΡΘΡΟΥ ---

    ΠΕΡΙΛΗΨΗ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1):
    --- ΑΡΧΗ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---
    [Content of Stage 1 Summary for this article]
    --- ΤΕΛΟΣ ΠΕΡΙΛΗΨΗΣ ΑΡΘΡΟΥ (ΣΤΑΔΙΟ 1) ---

    ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):
    --- ΑΡΧΗ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---
    [Content of the Stage 2 Cohesive Summary]
    --- ΤΕΛΟΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---
    --- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΔΕΔΟΜΕΝΩΝ ΕΙΣΟΔΟΥ ---
    ```
*   **Stage-Specific Constraints (`specific_constraints_for_stage` from `run_summarization.py`):**
    ```
    - Η σημείωση πρέπει να εστιάζει μόνο στην πιο σημαντική πληροφορία που λείπει από την Τελική Συνολική Περίληψη (Στάδιο 2) σε σχέση με το συγκεκριμένο άρθρο.
    - Πρέπει να είναι μία μόνο πρόταση, έως 150-200 τόκενς.
    ```

#### Stage 3.2: Refined Final Summary Correction (`stage_id="3.2"`)

*   **Original Task Instructions (`original_task_instructions_for_correction_s3_2` which is `stage3_2_task_instructions_template_el` from `run_summarization.py`):** The *template* of the initial prompt for refining the Stage 2 summary based on notes.
    ```
    Είσαι ένας βοηθός συγγραφής και επιμέλειας κειμένων. Σου παρέχονται τα εξής:
    1. Μια 'Αρχική Τελική Συνολική Περίληψη (Στάδιο 2)' μιας διαβούλευσης.
    2. Ένα σύνολο από 'Συνδυασμένες Περιλήψεις Άρθρων (Στάδιο 1) και Σημειώσεις'. Κάθε σημείωση υποδεικνύει πιθανές σημαντικές πληροφορίες από το αρχικό άρθρο που ενδέχεται να λείπουν ή να μην τονίζονται επαρκώς στην 'Αρχική Τελική Συνολική Περίληψη (Στάδιο 2)'.

    Ο σκοπός σου είναι να αναθεωρήσεις την 'Αρχική Τελική Συνολική Περίληψη (Στάδιο 2)' λαμβάνοντας υπόψη τις πληροφορίες και τις παρατηρήσεις που περιέχονται στις 'Συνδυασμένες Περιλήψεις Άρθρων (Στάδιο 1) και Σημειώσεις'. 
    Η αναθεωρημένη περίληψη πρέπει να ενσωματώνει τα σημαντικά σημεία που επισημάνθηκαν, διατηρώντας τη συνοχή, την ακρίβεια και τη συντομία. Το τελικό κείμενο πρέπει να είναι στα Ελληνικά.

    ΑΡΧΙΚΗ ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):
    --- ΑΡΧΗ ΑΡΧΙΚΗΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---
    {stage2_cohesive_summary_placeholder}
    --- ΤΕΛΟΣ ΑΡΧΙΚΗΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---

    ΣΥΝΔΥΑΣΜΕΝΕΣ ΠΕΡΙΛΗΨΕΙΣ ΑΡΘΡΩΝ (ΣΤΑΔΙΟ 1) ΚΑΙ ΣΗΜΕΙΩΣΕΙΣ:
    --- ΑΡΧΗ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---
    {combined_stage1_summaries_and_notes_placeholder}
    --- ΤΕΛΟΣ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---

    ΠΑΡΑΚΑΛΩ ΠΑΡΕΧΕΤΕ ΤΗΝ ΑΝΑΘΕΩΡΗΜΕΝΗ ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ:
    ```
*   **Core Input Data (`current_core_input_s3_2` from `run_summarization.py`):** A concatenated string containing the `final_cohesive_summary` (Stage 2) and the `concatenated_summaries_and_notes`, each clearly labeled. This would be framed as:
    ```
    --- ΑΡΧΙΚΑ ΔΕΔΟΜΕΝΑ ΕΙΣΟΔΟΥ ---
    ΑΡΧΙΚΗ ΤΕΛΙΚΗ ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2):
    --- ΑΡΧΗ ΑΡΧΙΚΗΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---
    [Content of the Stage 2 Cohesive Summary]
    --- ΤΕΛΟΣ ΑΡΧΙΚΗΣ ΤΕΛΙΚΗΣ ΣΥΝΟΛΙΚΗΣ ΠΕΡΙΛΗΨΗΣ (ΣΤΑΔΙΟ 2) ---

    ΣΥΝΔΥΑΣΜΕΝΕΣ ΠΕΡΙΛΗΨΕΙΣ ΑΡΘΡΩΝ (ΣΤΑΔΙΟ 1) ΚΑΙ ΣΗΜΕΙΩΣΕΙΣ:
    --- ΑΡΧΗ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---
    [Content of Combined Stage 1 Summaries with Stage 3.1 Notes]
    --- ΤΕΛΟΣ ΣΥΝΔΥΑΣΜΕΝΩΝ ΠΕΡΙΛΗΨΕΩΝ ΚΑΙ ΣΗΜΕΙΩΣΕΩΝ ---
    --- ΤΕΛΟΣ ΑΡΧΙΚΩΝ ΔΕΔΟΜΕΝΩΝ ΕΙΣΟΔΟΥ ---
    ```
*   **Stage-Specific Constraints (`specific_constraints_for_stage` from `run_summarization.py`):**
    ```
    - Η αναθεωρημένη τελική περίληψη πρέπει να ενσωματώνει τα σημαντικότερα σημεία που επισημάνθηκαν στις σημειώσεις.
    - Πρέπει να διατηρεί τη συνοχή, την ακρίβεια και τη συντομία.
    - Πρέπει να περιορίζεται σε περίπου 200-250 λέξεις και 3-4 παραγράφους το μέγιστο.
    - Πρέπει να είναι κατανοητή σε πολίτες χωρίς εξειδικευμένες νομικές γνώσεις.
    ```

## Improvement Process Flow

1. **Truncation Detection and Correction**
   - Applied to all generated responses (Stage 1, 2, 3.1, and 3.2)
   - When a response is truncated (doesn't end with proper punctuation):
     - Make a second attempt with reduced token limit
     - If still truncated, mark it as such for transparency
   
2. **Empty Notes Filtering**
   - In Stage 3.1, only non-empty notes that indicate actual missing information are kept
   - Notes stating "Δεν εντοπίστηκαν σημαντικές παραλείψεις" are filtered out
   - This ensures Stage 3.2 only receives meaningful feedback for refinement 