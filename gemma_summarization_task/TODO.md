# TODO List for Article Sequence Analysis and Data Quality

1.  **Refine Article Sequence Detection and Extraction:**
    *   Further investigate and improve the logic in `detect_multiple_articles_in_db.py` to accurately identify all articles within a single database entry, especially when they are "crammed."
        *   **DONE (Initial Version):** A centralized article header parsing utility, `gemma_summarization_task/article_extraction_analysis/article_parser_utils.py`, has been created with restrictive, case-sensitive parsing rules based on observed data.
        *   **TODO:** Refactor `detect_multiple_articles_in_db.py` to use `article_parser_utils.py` for header identification.
    *   Ensure the correct extraction of content for each sub-article.
        *   **TODO:** Refactor `gemma_summarization_task/article_extraction_analysis/quantify_improper_extractions.py` to use `article_parser_utils.py` for identifying sub-article boundaries and extracting their content.
    *   Strengthen the "overall sequence continuity" check to robustly handle various numbering schemes and potential gaps or out-of-order articles, based on the defined criteria (start of line, ascending order with step 1).
        *   **TODO:** After refactoring `detect_multiple_articles_in_db.py`, re-evaluate the sequence continuity logic based on the new parsing.
        *   **ONGOING:** Investigate causes for `is_overall_sequence_continuous = FALSE` in `crammed_articles_report.csv` using `gemma_summarization_task/article_extraction_analysis/investigate_non_continuous_sequences.py`. This will inform regex/parser improvements and identify data quality issues.
    *   Address edge cases observed during testing to improve accuracy.

2.  **Improve Scraper for Complete Article Sequences:**
    *   Review and enhance the web scraping process responsible for populating the `deliberation_data_gr_updated_better_extraction.db` database.
    *   Focus on sources like [http://www.opengov.gr/ministryofjustice/?p=17662](http://www.opengov.gr/ministryofjustice/?p=17662) to ensure that the full and complete text of all articles within a consultation is captured.
    *   The goal is to achieve 100% completeness for article sequences at the scraping stage to provide high-quality input for the analysis script. This might involve better handling of pagination, dynamic content loading, or variations in website structure.
    *   An analysis has been performed to quantify sub-articles that appear to have missing text (specifically, where word count after removing "Άρθρο X" headers is very low, e.g., 0 using word_count_method1). This can help identify systemic issues in scraping or initial extraction.
        *   Script for detailed sub-article analysis and word count generation: `/mnt/data/AI4Deliberation/gemma_summarization_task/article_extraction_analysis/quantify_improper_extractions.py`
        *   Detailed CSV output with word counts: `/mnt/data/AI4Deliberation/gemma_summarization_task/article_extraction_analysis/improper_sub_article_extractions_quantified.csv` (Generated with older parsing logic).
        *   Script for consultation-level summary of empty articles (based on `word_count_method1` from the above CSV): `/mnt/data/AI4Deliberation/gemma_summarization_task/article_extraction_analysis/analyze_empty_articles_by_consultation.py`
        *   Consultation-level summary CSV: `/mnt/data/AI4Deliberation/gemma_summarization_task/article_extraction_analysis/consultation_empty_article_report_wc1.csv` (Generated with older parsing logic).
        *   **ONGOING:** Investigate why some sub-articles have very low/zero word counts (potential empty extractions). This feeds back into scraper improvement.

3.  **Article Header Parsing Logic (`article_parser_utils.py`):**
    *   The current parser in `gemma_summarization_task/article_extraction_analysis/article_parser_utils.py` has been intentionally made restrictive to prioritize accuracy for known patterns and avoid false positives.
    *   Current parsing rules:
        *   Matches literal, case-sensitive "Άρθρο".
        *   Matches digit-based article numbers (e.g., "1", "12").
        *   Matches lowercase Greek ordinal words for article numbers (e.g., "πρώτο", "δεύτερο") based on an internal dictionary.
        *   Optionally matches paragraphs only in the format "παρ. \d+" (e.g., "παρ. 1").
        *   Does NOT use `re.IGNORECASE` globally.
        *   Does NOT currently support other "Άρθρο" capitalizations (e.g., "άρθρο", "ΑΡΘΡΟ"), uppercase Greek numeral words (e.g., "ΠΡΩΤΟ"), other paragraph keywords (e.g., "Μέρος", "Ενότητα"), lettered/alphanumeric paragraph IDs (e.g., "παρ. α"), or sub-paragraphs (e.g., "εδ. α").
    *   This parser should be revisited and potentially expanded if analysis of data reveals other common, valid article header formats that need to be supported. The goal is to balance precision with recall based on observed data.
    *   **TODO:** After refactoring scripts to use this utility, "everything" (see below) needs to be rerun to generate updated reports.

4.  **Rerun Analysis Pipeline ("Everything"):**
    *   **Step 1:** Rerun `detect_multiple_articles_in_db.py` (once refactored) to produce an updated `crammed_articles_report.csv`.
    *   **Step 2:** Rerun `gemma_summarization_task/article_extraction_analysis/quantify_improper_extractions.py` (once refactored) using the new `crammed_articles_report.csv` to produce an updated `improper_sub_article_extractions_quantified.csv`.
    *   **Step 3:** Rerun `gemma_summarization_task/analyze_word_count_differences.py` using the updated `improper_sub_article_extractions_quantified.csv`.
    *   **Step 4:** Rerun `gemma_summarization_task/article_extraction_analysis/analyze_empty_articles_by_consultation.py` using the updated `improper_sub_article_extractions_quantified.csv`.
    *   **Step 5:** Rerun `gemma_summarization_task/article_extraction_analysis/investigate_non_continuous_sequences.py` using the updated `crammed_articles_report.csv` to analyze reasons for non-continuity with the new parsing logic. 

- [x] ~~Integrate improved scraping/extraction pipeline (e.g., from extract_article_markdownify.py or similar efforts).~~ (Assuming new_html_extraction work is the standard now)
- [x] ~~Enhance handling of very long articles for Stage 1 summarization (potential truncation).~~ (Resolved by existing retry logic and token limits per stage)
- [ ] Explore alternative Stage 2 approaches for combining summaries (e.g., map-reduce style with intermediate summaries).
- [ ] Implement a more robust check for "no significant omissions found" in Stage 3.1 notes (e.g., semantic similarity).
- [x] ~~Parse articles from DB entries before summarization to handle "crammed" articles and ensure consistent input chunks.~~ (Addressed by current integration plan)
- [ ] Develop evaluation metrics for summary quality at each stage.
- [x] ~~Implement changes in `run_summarization.py` to pre-process DB entries using `extract_all_main_articles_with_content`.~~ (Completed)
- [x] ~~Adjust Stage 1 loop in `run_summarization.py` to use the `processed_articles_for_summarization` list.~~ (Completed as part of pre-processing integration)
- [x] ~~Ensure `individual_article_details` structure correctly stores `original_source_text_for_stage3_1` for each processed part.~~ (Completed as part of pre-processing integration)
- [x] ~~Verify Stage 3.1 and output file generation use the new granular IDs correctly.~~ (Completed as part of pre-processing integration)
- [ ] Thoroughly test the modified `run_summarization.py` with known "crammed" and regular articles. 