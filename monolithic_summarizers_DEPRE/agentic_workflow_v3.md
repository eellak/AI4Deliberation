# Agentic Workflow for Narrative-Focused Legislative Summarization (v2)

## 1. Overview
This document outlines an enhanced agentic workflow for summarizing legislative texts. The primary goal of this v2 workflow is to produce summaries that are not only accurate and comprehensive but also possess a strong narrative quality, making them more engaging, understandable, and enjoyable for citizens.

The workflow progresses through several stages:
-   **Initial Processing:** Extracting and chunking articles from the database.
-   **Stage 1:** Summarizing individual article chunks.
-   **Stage 2 (Multi-part):**
    -   **Stage 2.1:** Generating a cohesive, detailed summary from Stage 1 outputs.
    -   **Stage 2.2:** Identifying key themes relevant to citizens.
    -   **Stage 2.3:** Creating a structured plan for a narrative exposition.
-   **Stage 3:** Synthesizing the outputs from Stage 2 into a final, narrative-driven summary for citizens.

Each stage involving LLM interaction includes logic for checking response completeness and attempting corrections for truncated outputs.

## 2. Workflow Stages

### Input: Database Extraction
-   **Process:** Articles for a target `consultation_id` are extracted from the database.
-   **Article Chunking:** Each extracted database article entry (which might contain multiple logical articles) is processed to identify and separate individual article chunks. This uses the same logic as in `orchestrate_summarization_v2.py` (`get_internally_completed_chunks_for_db_article`).
-   **Output:** A list of text chunks, where each chunk represents an individual article or a logical segment of one.

---

### Stage 1: Individual Article/Chunk Summarization
-   **Input:** Each individual text chunk from the database extraction and parsing phase.
-   **Process:**
    -   If a chunk's content is empty, a placeholder message is used as its summary.
    -   Otherwise, the chunk is summarized using an LLM.
    -   Truncation check: If the summary is incomplete, a retry is attempted with instructions for a shorter, complete summary.
-   **Prompt Focus (Stage 1):**
    -   Generate a brief summary (e.g., up to 3 sentences) in simple Greek, suitable for citizens without legal expertise.
    -   Highlight changes to laws, institutions, or procedures if it's a legislative article.
    -   **Prompt (Greek):**
        ```
        Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω κειμένου στα Ελληνικά, σε απλή γλώσσα, 
        κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως 3 προτάσεις.
        Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες αν πρόκειται για νομοθετικό άρθρο.
        Οι περιλήψεις πρέπει να είναι όσο πιο σύντομες γίνεται, διατηρώνοντας την ουσία του κειμένου και να μην είναι παραπάνω απο 3 προτάσεις σε μήκος.
        Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης, μη βάζεις εισαγωγή στη περίψη απλώς γράψε την:

        [Original Article Content]
        ```
    -   **Truncation Correction Prompt (Shortening - Greek):**
        ```
        Η προηγούμενη περίληψη που δημιουργήσατε για το παρακάτω κείμενο φαίνεται να είναι ατελής ή να διακόπηκε απότομα. \\\\n\\\\n
        ΑΡΧΙΚΟ ΚΕΙΜΕΝΟ ΠΡΟΣ ΠΕΡΙΛΗΨΗ:\\\\n{core_input_text}\\\\n\\\\n
        ΑΡΧΙΚΕΣ ΟΔΗΓΙΕΣ ΠΕΡΙΛΗΨΗΣ:\\\\n{original_task_instructions}\\\\n\\\\n
        ΜΕΡΙΚΩΣ ΟΛΟΚΛΗΡΩΜΕΝΗ (Ή ΕΝΔΕΧΟΜΕΝΩΣ ΛΑΝΘΑΣΜΕΝΗ) ΠΕΡΙΛΗΨΗ:\\\\n{truncated_summary}\\\\n\\\\n
        Παρακαλώ δημιουργήστε μια **νέα, πλήρη και συνεκτική περίληψη** του ΑΡΧΙΚΟΥ ΚΕΙΜΕΝΟΥ, ακολουθώντας τις ΑΡΧΙΚΕΣ ΟΔΗΓΙΕΣ. \\\\n\\\\n
        Η νέα περίληψη πρέπει να είναι **σημαντικά πιο σύντομη** από την προηγούμενη προσπάθεια, για να αποφευχθεί η εκ νέου διακοπή. Εστιάστε στα πιο κρίσιμα σημεία. {specific_constraints}
        ```
-   **Output:** A list of `individual_chunk_details`, where each entry contains the original chunk, its generated summary, and relevant metadata. These summaries are also collected into a list of `all_individual_summaries_text`.

---

### Stage 2.1: Cohesive Summary Generation
-   **Input:** `all_individual_summaries_text` (concatenated valid summaries from Stage 1).
-   **Process:**
    -   If no valid Stage 1 summaries exist, this stage is skipped or a placeholder is generated.
    -   Otherwise, the concatenated Stage 1 summaries are provided to an LLM to generate a single, cohesive, and comprehensive summary.
    -   **Target Length:** Aim for a detailed overview, approximately 1500 tokens.
    -   Truncation check: Implemented as in Stage 1, adjusting for the higher token limit.
-   **Prompt Focus (Stage 2.1):**
    -   Combine individual summaries into a unified, coherent, and **detailed** text.
    -   Capture main points and the broader legislative goal.
    -   Emphasize comprehensiveness and the target length (e.g., 1500 tokens).
    -   **Prompt (Greek):**
        ```
        Οι παρακάτω είναι ατομικές περιλήψεις πολλαπλών άρθρων από μία ενιαία διαβούλευση. 
        Παρακαλώ συνδυάστε τις σε ένα ενιαίο, συνεκτικό και **λεπτομερές** κείμενο στα Ελληνικά που αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου. 
        Στοχεύστε σε μια **αναλυτική επισκόπηση περίπου 1500 tokens**. Βεβαιωθείτε ότι καλύπτονται όλες οι σημαντικές πτυχές που αναφέρονται στις επιμέρους περιλήψεις.

        ---
        [Concatenated Stage 1 Summaries]
        ```
    -   **Truncation Correction Prompt (Concise Continuation - Greek):**
        ```
        Η προηγούμενη απάντησή σας στο παρακάτω αίτημα φαίνεται ότι διακόπηκε, πιθανώς στη μέση μιας πρότασης ή σκέψης. 
        Είναι πολύ σημαντικό να **ολοκληρώσετε την τρέχουσα πρόταση/σκέψη και να ολοκληρώσετε την απάντηση** όσο το δυνατόν πιο σύντομα, 
        χρησιμοποιώντας **ελάχιστες επιπλέον λέξεις/tokens**. \\\\n
        **Οδηγία: Η απάντησή σας σε αυτό το αίτημα πρέπει να ξεκινά ΑΜΕΣΩΣ με τις λέξεις που λείπουν για να ολοκληρωθεί η τελευταία, ημιτελής πρόταση της προηγούμενης απάντησης. Μην προσθέσετε εισαγωγικές φράσεις. Απλώς συνεχίστε την πρόταση. Αν η πρόταση ολοκληρώθηκε, μπορείτε να προσθέσετε το πολύ μία ακόμη σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά.**\\\\n
        Μην επαναλαμβάνετε πληροφορίες που έχουν ήδη δοθεί στην παρακάτω μερικώς ολοκληρωμένη απάντηση.\\\\n\\\\n
        Το αρχικό αίτημα ήταν:\\\\n
        \'\'\'\\\\n{original_task_instructions}\\\\n\'\'\'\\\\n\\\\n
        Τα αρχικά δεδομένα εισόδου που δόθηκαν ήταν:\\\\n
        \'\'\'\\\\n{original_input_data}\\\\n\'\'\'\\\\n\\\\n
        Η μερικώς ολοκληρωμένη απάντησή σας μέχρι στιγμής είναι:\\\\n
        \'\'\'\\\\n{truncated_response}\\\\n\'\'\'\\\\n\\\\n
        Παρακαλώ, παρέχετε **μόνο τις λέξεις που ακολουθούν ΑΜΕΣΩΣ** για να ολοκληρωθεί η τελευταία πρόταση της παραπάνω απάντησης, και αν χρειάζεται, μία (το πολύ) επιπλέον σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά:
        ```
-   **Output:** `cohesive_summary_stage2_1` (a single text string).

---

### Stage 2.2: Thematic Identification
-   **Input:** The same `all_individual_summaries_text` (concatenated valid summaries from Stage 1) used as input for Stage 2.1.
-   **Process:**
    -   The concatenated Stage 1 summaries are provided to an LLM.
    -   The LLM is asked to identify general themes of the legislation that would be of particular interest to citizens.
    -   Truncation check: Implemented.
-   **Prompt Focus (Stage 2.2):**
    -   Identify **general themes** from the provided summaries.
    -   Focus on aspects that have **particular relevance and interest for citizens**.
    -   The goal is to understand the main thematic areas impacting citizens' daily lives and rights.
    -   **Prompt (Greek):**
        ```
        Βάσει των παρακάτω περιλήψεων άρθρων ενός νομοσχεδίου, προσδιόρισε τα **γενικά θέματα** της νομοθεσίας που θα είχαν **ιδιαίτερο ενδιαφέρον για τους πολίτες**. 
        Κατάγραψε αυτά τα θέματα με σαφήνεια και συντομία, το καθένα σε νέα γραμμή (π.χ., ξεκινώντας με παύλα). Στόχος είναι να κατανοήσουμε τις κύριες θεματικές ενότητες που αφορούν την καθημερινότητα και τα δικαιώματα των πολιτών.

        ---
        [Concatenated Stage 1 Summaries]
        ```
    -   **Truncation Correction Prompt (Concise Continuation - Greek):** (Same as Stage 2.1)
        ```
        Η προηγούμενη απάντησή σας στο παρακάτω αίτημα φαίνεται ότι διακόπηκε, πιθανώς στη μέση μιας πρότασης ή σκέψης. 
        Είναι πολύ σημαντικό να **ολοκληρώσετε την τρέχουσα πρόταση/σκέψη και να ολοκληρώσετε την απάντηση** όσο το δυνατόν πιο σύντομα, 
        χρησιμοποιώντας **ελάχιστες επιπλέον λέξεις/tokens**. \\\\n
        **Οδηγία: Η απάντησή σας σε αυτό το αίτημα πρέπει να ξεκινά ΑΜΕΣΩΣ με τις λέξεις που λείπουν για να ολοκληρωθεί η τελευταία, ημιτελής πρόταση της προηγούμενης απάντησης. Μην προσθέσετε εισαγωγικές φράσεις. Απλώς συνεχίστε την πρόταση. Αν η πρόταση ολοκληρώθηκε, μπορείτε να προσθέσετε το πολύ μία ακόμη σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά.**\\\\n
        Μην επαναλαμβάνετε πληροφορίες που έχουν ήδη δοθεί στην παρακάτω μερικώς ολοκληρωμένη απάντηση.\\\\n\\\\n
        Το αρχικό αίτημα ήταν:\\\\n
        \'\'\'\\\\n{original_task_instructions}\\\\n\'\'\'\\\\n\\\\n
        Τα αρχικά δεδομένα εισόδου που δόθηκαν ήταν:\\\\n
        \'\'\'\\\\n{original_input_data}\\\\n\'\'\'\\\\n\\\\n
        Η μερικώς ολοκληρωμένη απάντησή σας μέχρι στιγμής είναι:\\\\n
        \'\'\'\\\\n{truncated_response}\\\\n\'\'\'\\\\n\\\\n
        Παρακαλώ, παρέχετε **μόνο τις λέξεις που ακολουθούν ΑΜΕΣΩΣ** για να ολοκληρωθεί η τελευταία πρόταση της παραπάνω απάντησης, και αν χρειάζεται, μία (το πολύ) επιπλέον σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά:
        ```
-   **Output:** `identified_themes_stage2_2` (e.g., a list of themes as text strings).

---

### Stage 2.3: Narrative Planning
-   **Input:** The same `all_individual_summaries_text` (concatenated valid summaries from Stage 1) used for Stages 2.1 and 2.2.
-   **Process:**
    -   The concatenated Stage 1 summaries are provided to an LLM.
    -   The LLM is instructed to identify the large-scale narrative of the legislation and create a **PLAN** for a narrative/story.
    -   The plan should outline 6-7 sections, structured with a beginning, middle, and end.
    -   Narrative elements for the plan:
        1.  The problem the legislation addresses.
        2.  The intended changes.
        3.  The expected outcomes/impact.
    -   The style of the plan should be sparse, factual, and strictly based on the provided evidence, akin to high-quality journalistic work.
    -   **Crucially, the output is a plan, not the narrative itself.**
    -   Truncation check: Implemented.
-   **Prompt Focus (Stage 2.3):**
    -   "Create a **NARRATIVE PLAN** or **STORY OUTLINE**."
    -   Specify "6-7 sections" with "beginning, middle, end."
    -   Define narrative components: "problem identified," "intended changes," "expected outcome."
    -   Emphasize: "**sparse and factual**," "**based precisely on the given evidence**," "like a great piece of **journalistic work**."
    -   Reiterate: "**This is a PLAN for a narrative, not the narrative itself.**"
    -   **Prompt (Greek):**
        ```
        Με βάση τις παρακάτω περιλήψεις άρθρων, σκιαγράφησε ένα **ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ** για ένα ενημερωτικό άρθρο δημοσιογραφικού ύφους, που θα εξηγεί το νομοσχέδιο στους πολίτες. 
        Το σχέδιο πρέπει να περιλαμβάνει **6-7 ενότητες**, όπου κάθε ενότητα έχει έναν τίτλο και μια σύντομη περιγραφή (1-2 προτάσεις) του περιεχομένου της. 
        Η δομή της αφήγησης πρέπει να έχει αρχή, μέση και τέλος. Κάθε ενότητα πρέπει να εστιάζει στα εξής: το πρόβλημα που αναγνωρίζει η νομοθεσία, τις αλλαγές που σκοπεύει να επιφέρει, και τα αναμενόμενα αποτελέσματα. 
        Η προσέγγιση πρέπει να είναι **αποκλειστικά βασισμένη στα παρεχόμενα στοιχεία, λιτή και αντικειμενική**, σαν ένα εξαιρετικό δημοσιογραφικό κείμενο. 
        **Προσοχή: Δημιούργησε μόνο το σχέδιο της αφήγησης (τίτλοι και περιγραφές ενοτήτων), όχι την ίδια την αφήγηση.**

        ---
        [Concatenated Stage 1 Summaries]
        ```
    -   **Truncation Correction Prompt (Concise Continuation - Greek):** (Same as Stage 2.1)
        ```
        Η προηγούμενη απάντησή σας στο παρακάτω αίτημα φαίνεται ότι διακόπηκε, πιθανώς στη μέση μιας πρότασης ή σκέψης. 
        Είναι πολύ σημαντικό να **ολοκληρώσετε την τρέχουσα πρόταση/σκέψη και να ολοκληρώσετε την απάντηση** όσο το δυνατόν πιο σύντομα, 
        χρησιμοποιώντας **ελάχιστες επιπλέον λέξεις/tokens**. \\\\n
        **Οδηγία: Η απάντησή σας σε αυτό το αίτημα πρέπει να ξεκινά ΑΜΕΣΩΣ με τις λέξεις που λείπουν για να ολοκληρωθεί η τελευταία, ημιτελής πρόταση της προηγούμενης απάντησης. Μην προσθέσετε εισαγωγικές φράσεις. Απλώς συνεχίστε την πρόταση. Αν η πρόταση ολοκληρώθηκε, μπορείτε να προσθέσετε το πολύ μία ακόμη σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά.**\\\\n
        Μην επαναλαμβάνετε πληροφορίες που έχουν ήδη δοθεί στην παρακάτω μερικώς ολοκληρωμένη απάντηση.\\\\n\\\\n
        Το αρχικό αίτημα ήταν:\\\\n
        \'\'\'\\\\n{original_task_instructions}\\\\n\'\'\'\\\\n\\\\n
        Τα αρχικά δεδομένα εισόδου που δόθηκαν ήταν:\\\\n
        \'\'\'\\\\n{original_input_data}\\\\n\'\'\'\\\\n\\\\n
        Η μερικώς ολοκληρωμένη απάντησή σας μέχρι στιγμής είναι:\\\\n
        \'\'\'\\\\n{truncated_response}\\\\n\'\'\'\\\\n\\\\n
        Παρακαλώ, παρέχετε **μόνο τις λέξεις που ακολουθούν ΑΜΕΣΩΣ** για να ολοκληρωθεί η τελευταία πρόταση της παραπάνω απάντησης, και αν χρειάζεται, μία (το πολύ) επιπλέον σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά:
        ```
-   **Output:** `narrative_plan_stage2_3` (a structured plan, e.g., list of section titles with brief descriptions).

---

### Stage 3: Narrative Exposition
-   **Input:**
    1.  `cohesive_summary_stage2_1` (from Stage 2.1)
    2.  `identified_themes_stage2_2` (from Stage 2.2)
    3.  `narrative_plan_stage2_3` (from Stage 2.3)
-   **Process:**
    -   The LLM is provided with the cohesive summary, themes, and narrative plan.
    -   It is tasked to synthesize these into a final "based exposition."
    -   The exposition must use the `cohesive_summary_stage2_1` as its factual foundation.
    -   It should develop the `identified_themes_stage2_2` following the structure laid out in the `narrative_plan_stage2_3`.
    -   The aim is an informative, easy-to-read piece that clearly explains what the legislation intends to accomplish and how, focusing on its essence.
    -   Truncation check: Implemented.
-   **Prompt Focus (Stage 3):**
    -   "Create an **informative and easy-to-read exposition/article** for citizens."
    -   "Develop the **main themes** (provided) through the **narrative structure/plan** (provided)."
    -   "**Strictly utilize the facts and information from the Cohesive Summary** (provided)."
    -   "Focus on the **essence of the legislation**."
    -   "Explain clearly **what the legislation intends to accomplish and how**."
    -   **Prompt (Greek):**
        ```
        Σου παρέχονται: (1) μια Συνολική Περίληψη ενός νομοσχεδίου (Στάδιο 2.1), (2) τα Κύρια Θέματα που αφορούν τους πολίτες (Στάδιο 2.2), και (3) ένα Σχέδιο Αφήγησης (Στάδιο 2.3).\\n
        Παρακαλώ, χρησιμοποίησε αυτά τα στοιχεία για να συνθέσεις ένα **ενημερωτικό και ευανάγνωστο κείμενο** για τους πολίτες. Το κείμενο πρέπει:\\n
        - Να αναπτύσσει τα Κύρια Θέματα ακολουθώντας τη δομή του Σχεδίου Αφήγησης.\\n
        - Να βασίζεται **αυστηρά στα γεγονότα και τις πληροφορίες που περιέχονται στη Συνολική Περίληψη (Στάδιο 2.1)**.\\n
        - Να εστιάζει στην **ουσία του νομοσχεδίου**, εξηγώντας με σαφήνεια τι σκοπεύει να επιτύχει και πώς.\\n
        Ο στόχος είναι η δημιουργία ενός κειμένου που βοηθά τους πολίτες να κατανοήσουν πλήρως το προτεινόμενο νομοσχέδιο.

        ---
        ΣΥΝΟΛΙΚΗ ΠΕΡΙΛΗΨΗ (ΣΤΑΔΙΟ 2.1):
        [cohesive_summary_stage2_1]
        ---
        ΚΥΡΙΑ ΘΕΜΑΤΑ (ΣΤΑΔΙΟ 2.2):
        [identified_themes_stage2_2]
        ---
        ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ (ΣΤΑΔΙΟ 2.3):
        [narrative_plan_stage2_3]
        ---
        ΠΑΡΑΚΑΛΩ ΠΑΡΕΧΕΤΕ ΤΟ ΤΕΛΙΚΟ ΕΝΗΜΕΡΩΤΙΚΟ ΚΕΙΜΕΝΟ:
        ```
    -   **Truncation Correction Prompt (Concise Continuation - Greek):** (Same as Stage 2.1)
        ```
        Η προηγούμενη απάντησή σας στο παρακάτω αίτημα φαίνεται ότι διακόπηκε, πιθανώς στη μέση μιας πρότασης ή σκέψης. 
        Είναι πολύ σημαντικό να **ολοκληρώσετε την τρέχουσα πρόταση/σκέψη και να ολοκληρώσετε την απάντηση** όσο το δυνατόν πιο σύντομα, 
        χρησιμοποιώντας **ελάχιστες επιπλέον λέξεις/tokens**. \\\\n
        **Οδηγία: Η απάντησή σας σε αυτό το αίτημα πρέπει να ξεκινά ΑΜΕΣΩΣ με τις λέξεις που λείπουν για να ολοκληρωθεί η τελευταία, ημιτελής πρόταση της προηγούμενης απάντησης. Μην προσθέσετε εισαγωγικές φράσεις. Απλώς συνεχίστε την πρόταση. Αν η πρόταση ολοκληρώθηκε, μπορείτε να προσθέσετε το πολύ μία ακόμη σύντομη πρόταση για να ολοκληρώσετε την απάντηση συνολικά:
        ```
-   **Output:** `final_narrative_summary` (the polished, narrative-driven summary for citizen consumption).

---

## 3. Visual Workflow Diagram (Simplified)

'''
┌───────────────────────┐
│    Database Query     │
│  Extract & Chunk      │
│      Articles         │
└──────────┬────────────┘
           │ `article_chunks`
           ▼
┌───────────────────────┐
│       STAGE 1         │
│  Individual Chunk     │
│     Summarization     │
└──────────┬────────────┘
           │ `all_individual_summaries_text`
           │ (Concatenated Summaries from Stage 1)
           │ (This is the common input for Stages 2.1, 2.2, AND 2.3)
           │
           ├───► Processed by STAGE 2.1 ───► `cohesive_summary_stage2_1` ──┐
           │                                                               │
           ├───► Processed by STAGE 2.2 ───► `identified_themes_stage2_2`──│
           │                                                               │
           └───► Processed by STAGE 2.3 ───► `narrative_plan_stage2_3` ────┘
                                                                           │
                                                                           ▼
                                                                  ┌───────────────────────┐
                                                                  │       STAGE 3         │
                                                                  │ Narrative Exposition  │
                                                                  │ (Combines Outputs of  │
                                                                  │  2.1, 2.2, and 2.3)   │
                                                                  └──────────┬────────────┘
                                                                             │
                                                                     `final_narrative_summary`
                                                                             |
                                                                             ▼
                                                                    ┌───────────────────────┐
                                                                    │     Final Output      │
                                                                    │(Narrative for Citizen)│
                                                                    └───────────────────────┘
'''

## 4. General Considerations
-   **Truncation Handling:** Each stage involving an LLM call must implement robust truncation detection and retry mechanisms. The retry prompts should guide the model to produce a complete response, potentially by asking for a more concise version that still meets the core objectives of that stage.
-   **Error Handling:** The workflow should gracefully handle cases where inputs to a stage are missing or invalid (e.g., no valid Stage 1 summaries).
-   **Logging:** Detailed logging for each stage, including prompts, LLM responses (or placeholders in dry runs), and errors, is crucial for debugging and analysis.
-   **Prompt Engineering:** The success of this workflow heavily relies on carefully crafted prompts for each new stage (2.2, 2.3, 3). These prompts need to be clear, specific, and strongly guide the LLM towards the desired output style and content. Iterative testing and refinement of prompts will be essential. 