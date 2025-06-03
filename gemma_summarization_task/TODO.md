# TODO List for Gemma Summarization Workflow and Article Parsing

## I. Article Parsing & Data Quality (Upstream Analysis)

1.  **Refine Article Sequence Detection and Extraction (Using `article_parser_utils.py`):**
    *   Further investigate and improve the logic in `detect_multiple_articles_in_db.py` to accurately identify all articles within a single database entry, especially when they are "crammed."
        *   **DONE (Initial Version):** A centralized article header parsing utility, `new_html_extraction/article_extraction_analysis/article_parser_utils.py`, has been created.
        *   **TODO:** Refactor `detect_multiple_articles_in_db.py` to use `article_parser_utils.py` for header identification.
    *   Ensure the correct extraction of content for each sub-article in analysis scripts.
        *   **TODO:** Refactor `new_html_extraction/article_extraction_analysis/quantify_improper_extractions.py` to use `article_parser_utils.py` for identifying sub-article boundaries and extracting their content.
    *   Strengthen the "overall sequence continuity" check in analysis scripts.
        *   **TODO:** After refactoring `detect_multiple_articles_in_db.py`, re-evaluate the sequence continuity logic based on the new parsing.
        *   **ONGOING:** Investigate causes for `is_overall_sequence_continuous = FALSE` in `crammed_articles_report.csv` (once regenerated) using `new_html_extraction/article_extraction_analysis/investigate_non_continuous_sequences.py`.
    *   Address edge cases observed during testing to improve parsing accuracy.

2.  **Improve Scraper for Complete Article Sequences:**
    *   Review and enhance the web scraping process responsible for populating the `deliberation_data_gr_updated_better_extraction.db` database.
    *   Focus on sources like [http://www.opengov.gr/ministryofjustice/?p=17662](http://www.opengov.gr/ministryofjustice/?p=17662) to ensure that the full and complete text of all articles within a consultation is captured.
    *   The goal is to achieve 100% completeness for article sequences at the scraping stage to provide high-quality input for the analysis script. This might involve better handling of pagination, dynamic content loading, or variations in website structure.
    *   An analysis has been performed to quantify sub-articles that appear to have missing text (specifically, where word count after removing "Άρθρο X" headers is very low, e.g., 0 using word_count_method1). This can help identify systemic issues in scraping or initial extraction.
        *   Script for detailed sub-article analysis and word count generation: `/mnt/data/AI4Deliberation/new_html_extraction/article_extraction_analysis/quantify_improper_extractions.py`
        *   Detailed CSV output with word counts: `/mnt/data/AI4Deliberation/new_html_extraction/article_extraction_analysis/improper_sub_article_extractions_quantified.csv` (Generated with older parsing logic).
        *   Script for consultation-level summary of empty articles (based on `word_count_method1` from the above CSV): `/mnt/data/AI4Deliberation/new_html_extraction/article_extraction_analysis/analyze_empty_articles_by_consultation.py`
        *   Consultation-level summary CSV: `/mnt/data/AI4Deliberation/new_html_extraction/article_extraction_analysis/consultation_empty_article_report_wc1.csv` (Generated with older parsing logic).
    *   **ONGOING:** Investigate why some sub-articles have very low/zero word counts (potential empty extractions). This feeds back into scraper improvement.

3.  **Article Header Parsing Logic (`article_parser_utils.py`):**
    *   The current parser in `new_html_extraction/article_extraction_analysis/article_parser_utils.py` has been intentionally made restrictive to prioritize accuracy for known patterns and avoid false positives.
    *   Current parsing rules:
        *   Matches literal, case-sensitive "Άρθρο".
        *   Matches digit-based article numbers (e.g., "1", "12").
        *   Matches lowercase Greek ordinal words for article numbers (e.g., "πρώτο", "δεύτερο") based on an internal dictionary.
        *   Optionally matches paragraphs only in the format "παρ. \d+" (e.g., "παρ. 1").
        *   Does NOT use `re.IGNORECASE` globally.
        *   Does NOT currently support other "Άρθρο" capitalizations (e.g., "άρθρο", "ΑΡΘΡΟ"), uppercase Greek numeral words (e.g., "ΠΡΩΤΟ"), other paragraph keywords (e.g., "Μέρος", "Ενότητα"), lettered/alphanumeric paragraph IDs (e.g., "παρ. α"), or sub-paragraphs (e.g., "εδ. α").
    *   This parser should be revisited and potentially expanded if analysis of data reveals other common, valid article header formats that need to be supported. The goal is to balance precision with recall based on observed data.
    *   **TODO:** After refactoring analysis scripts to use this utility, "everything" (see section 4) needs to be rerun to generate updated reports.

4.  **Rerun Analysis Pipeline ("Everything" for Data Quality Assessment):**
    *   **Step 1:** Rerun `detect_multiple_articles_in_db.py` (once refactored) to produce an updated `crammed_articles_report.csv`.
    *   **Step 2:** Rerun `new_html_extraction/article_extraction_analysis/quantify_improper_extractions.py` (once refactored) using the new `crammed_articles_report.csv` to produce an updated `improper_sub_article_extractions_quantified.csv`.
    *   **Step 3:** Rerun `gemma_summarization_task/analyze_word_count_differences.py` using the updated `improper_sub_article_extractions_quantified.csv`.
    *   **Step 4:** Rerun `new_html_extraction/article_extraction_analysis/analyze_empty_articles_by_consultation.py` using the updated `improper_sub_article_extractions_quantified.csv`.
    *   **Step 5:** Rerun `new_html_extraction/article_extraction_analysis/investigate_non_continuous_sequences.py` using the updated `crammed_articles_report.csv` to analyze reasons for non-continuity with the new parsing logic.

## II. Summarization Workflow Implementation (Using `orchestrate_summarization_v2.py`)

- [x] ~~Integrate improved scraping/extraction pipeline (e.g., from extract_article_markdownify.py or similar efforts).~~ (Assuming `new_html_extraction` work is the standard now, and DB is populated correctly)
- [x] ~~Enhance handling of very long articles for Stage 1 summarization (potential truncation).~~ (Addressed by retry logic in `summarize_chunk_stage1` within `orchestrate_summarization_v2.py` and prompt design in `run_summarization.py`)

**Core Workflow Tasks for `orchestrate_summarization_v2.py` (Based on `agentic_workflow.md`):**

- **Stage 1: Individual Article/Chunk Summarization**
    - [x] Parse articles/chunks from DB entries using `article_parser_utils.extract_all_main_articles_with_content` within `orchestrate_summarization_v2.py`.
    - [x] Loop through parsed chunks and generate individual summaries (Stage 1 prompt).
    - [x] Store individual results, including original chunk content, type, article number, title, and summary. (Largely done via `all_stage1_results` structure and dry-run CSV in `orchestrate_summarization_v2.py`).
    - [ ] **TODO:** Ensure `all_stage1_results` in `orchestrate_summarization_v2.py` captures all necessary fields robustly for live runs (e.g., `original_db_id`, `chunk_type`, `article_number_in_chunk`, `title_line`, `original_chunk_content`, `stage1_summary`). This is crucial for Stage 3.1 input.

- **Stage 2: Cohesive Summary Generation**
    - [ ] **TODO:** Implement Stage 2 in `orchestrate_summarization_v2.py`.
        - Gather all valid Stage 1 summaries from `all_stage1_results`.
        - Concatenate these summaries to form the input for the Stage 2 prompt (defined in `agentic_workflow.md`).
        - Call the LLM to generate a cohesive summary.
        - Implement truncation checks and retry logic for the cohesive summary (can adapt from `run_summarization.py`'s `summarize_text` function or `orchestrate_summarization_v2.py`'s Stage 1).
        - Store the final cohesive summary.

- **Stage 3.1: Missing Information Detection**
    - [ ] **TODO:** Implement Stage 3.1 in `orchestrate_summarization_v2.py`.
        - For each article chunk processed in Stage 1 (iterate through `all_stage1_results`):
            - If original chunk content was empty or its Stage 1 summary is invalid/placeholder, create an appropriate error note.
            - Otherwise, construct the prompt for Stage 3.1 (defined in `agentic_workflow.md`) using:
                - The original content of the current chunk.
                - The Stage 1 summary of the current chunk.
                - The cohesive summary from Stage 2.
            - Call the LLM to generate a "missing information" note for this chunk.
            - Implement truncation checks and retry logic for these notes.
            - Collect all generated notes, especially those that are not the generic "Δεν εντοπίστηκαν σημαντικές παραλείψεις..."
    - [ ] Implement a more robust check for "no significant omissions found" in Stage 3.1 notes (e.g., semantic similarity, keyword check, or a specific instruction in the prompt to be terse if nothing is found).

- **Stage 3.2: Final Summary Refinement**
    - [ ] **TODO:** Implement Stage 3.2 in `orchestrate_summarization_v2.py`.
        - If significant missing information notes were collected in Stage 3.1:
            - Prepare the input for the Stage 3.2 prompt (defined in `agentic_workflow.md`) using the Stage 2 cohesive summary and the collected (significant) notes.
            - Call the LLM to generate the refined final summary.
            - Implement truncation checks and retry logic.
        - If no significant notes were found in Stage 3.1, the Stage 2 cohesive summary can be considered the final summary.
        - Store the refined (or final) summary.

**General Workflow Enhancements & Testing:**

- [ ] Explore alternative Stage 2 approaches if direct concatenation of many Stage 1 summaries leads to context length issues or poor cohesive summaries (e.g., hierarchical summarization / map-reduce style).
- [ ] Develop evaluation metrics and a testing framework for summary quality at each stage (Stage 1, Stage 2, Stage 3.2).
- [ ] Thoroughly test the complete `orchestrate_summarization_v2.py` workflow (once Stages 2 and 3 are implemented) with diverse consultation data:
    - Consultations with a large number of articles/chunks.
    - Consultations with very few articles/chunks.
    - DB entries that are "crammed" (multiple articles in one entry).
    - DB entries with preambles, annexes, etc.
    - Articles/chunks with empty or very short content.
- [ ] **TODO:** Define the final output structure and persistence strategy for a live run of `orchestrate_summarization_v2.py`.
    - How and where should the Stage 1 summaries (per chunk), the Stage 2 cohesive summary, the Stage 3.1 notes, and the Stage 3.2 final refined summary be stored? (e.g., new database tables, JSON files). The current dry-run CSV in `orchestrate_summarization_v2.py` is a good start for reporting Stage 1 details.

**Obsolete tasks (related to `run_summarization.py` as the primary orchestrator for these specific sub-points):**
- [-] ~~Implement changes in `run_summarization.py` to pre-process DB entries using `extract_all_main_articles_with_content`.~~ (Superseded by `orchestrate_summarization_v2.py`)
- [-] ~~Adjust Stage 1 loop in `run_summarization.py` to use the `processed_articles_for_summarization` list.~~ (Superseded by `orchestrate_summarization_v2.py`)
- [-] ~~Ensure `individual_article_details` structure correctly stores `original_source_text_for_stage3_1` for each processed part.~~ (This concept is now part of the "TODO" for `all_stage1_results` in `orchestrate_summarization_v2.py`)
- [-] ~~Verify Stage 3.1 and output file generation use the new granular IDs correctly.~~ (This will be part of implementing Stages 3.1/3.2 in `orchestrate_summarization_v2.py`) 