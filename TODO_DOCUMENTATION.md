# TODO: Comprehensive Documentation Investigation

This document lists components, folders, and scripts that require comprehensive investigation for detailed documentation. The goal is to understand the purpose, functionality, inputs, outputs, and dependencies of each item.

## General Areas:
- [ ] Overall project structure and data flow between components.
- [ ] Setup, installation, and execution instructions for each major component and the project as a whole.
- [ ] Contribution guidelines.
- [ ] Licensing details for all included software and models.

## Specific Folders for Detailed Documentation:

### 1. `/mnt/data/AI4Deliberation/ai4deliberation_pipeline`
   - **Purpose:** Core pipeline for data ingestion and processing from opengov.gr.
   - **Sub-folders & Scripts to Investigate:**
     - [ ] `master/pipeline_orchestrator.py`: Deep dive into `PipelineOrchestrator` class, `run_pipeline_entry`, all private and public methods, modes of operation.
     - [ ] `scraper/`:
       - [ ] `scrape_single_consultation.py`: Detailed logic of `scrape_and_store`.
       - [ ] `list_consultations.py`: Discovery mechanism.
       - [ ] `content_scraper.py`, `metadata_scraper.py`: Specific scraping logic.
       - [ ] `db_models.py`: All SQLAlchemy models and relationships.
       - [ ] Other utility scripts.
     - [ ] `utils/`:
       - [ ] `data_flow.py`: `ContentProcessor` in detail - HTML processing, PDF processing (docling, glossapi integration), Rust cleaner integration. All methods.
       - [ ] `database.py`: Connection handling, stats.
       - [ ] `logging_utils.py`.
       - [ ] `db_migration.py`, `verify_migration.py` (if relevant to current state).
     - [ ] `config/`:
       - [ ] `config_manager.py`: Loading, validation, environment overrides.
       - [ ] `pipeline_config.yaml`: Document all configuration options and their effects.
     - [ ] `html_processor/`, `pdf_processor/`, `rust_processor/`: Confirm if these are standalone or fully integrated into `utils/data_flow.py`. Document any remaining standalone utility.
     - [ ] `tests_and_analysis/`: Document existing tests and analysis scripts.
     - [ ] `migration_support/`: Document purpose and scripts if still relevant.
     - [ ] `PIPELINE_WORKFLOW_CHECKLIST.md`: Review and update if necessary based on current implementation.
     - [ ] Root files: `query_consultation.py`, `inspect_docs.py`, `check_test_docs.py`.

### 2. `/mnt/data/AI4Deliberation/gemma_summarization_task`
   - **Purpose:** Summarization of consultation texts using Gemma models.
   - **Sub-folders & Scripts to Investigate:**
     - [ ] `orchestrate_summarization_v2.py`: Main workflow, logic, model interaction.
     - [ ] `run_summarization.py`: Purpose and usage.
     - [ ] `prompts.py` (if it exists or prompt logic is embedded): Prompt engineering aspects.
     - [ ] Any utility scripts (`utils.py`, etc.).
     - [ ] Input data format and sources.
     - [ ] Output format and storage.
     - [ ] Configuration parameters (model selection, length, etc.).
     - [ ] (Identify and document any other scripts or important files in this directory).

### 3. `/mnt/data/AI4Deliberation/cleaning`
   - **Purpose:** General text cleaning scripts.
   - **Sub-folders & Scripts to Investigate:**
     - [ ] Identify and document all scripts in this folder.
     - [ ] **`cleaning/nomoi/`**
       - **Purpose:** Specific cleaning/processing for legal texts (Nomoi).
       - [ ] `analyze_badness.py`, `analyze_sequences.py`.
       - [ ] `fek_nomoi_scraper.py`, `process_gazettes.py`.
       - [ ] `greek_numerals.py`.
       - [ ] `check_badness/`:
         - [ ] `clean_markdown_files.py`, `table_detector.py`, `table_processor.py`, `process_documents.py`, `pipeline_orchestrator.py` (if different from main pipeline).
         - [ ] `extraction_metrics_rs/`: Purpose and usage of the Rust project here.
       - [ ] (Identify and document any other scripts or important files).

### 4. `/mnt/data/AI4Deliberation/legal_text_analysis_scripts`
   - **Purpose:** Scripts for specific analysis of legal texts.
   - **Sub-folders & Scripts to Investigate:**
     - [ ] `export_consultations.py`
     - [ ] `process_legal_texts.py`
     - [ ] `regex_capture_groups.py`
     - [ ] `create_greek_laws_table.py`
     - [ ] `law_detection_summary.py`
     - [ ] `simplified_law_detection.py`
     - [ ] `README_law_detection.md`: Review and integrate.
     - [ ] (Identify and document any other scripts or important files). 