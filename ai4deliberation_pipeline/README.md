# AI4Deliberation Pipeline Documentation

This document provides a detailed overview of the AI4Deliberation pipeline, its components, workflow, and programmatic usage.

## 1. Overview
The pipeline is designed to automate the collection, processing, and storage of Greek online public consultation data from opengov.gr.

Key functionalities include:
- Comprehensive web scraping of consultation metadata, articles, comments, and official documents.
- HTML to Markdown conversion for web content.
- PDF document download and text extraction (utilizing `docling`).
- Rust-based text cleaning for document content.
- Database integration using SQLAlchemy for persistent storage.
- Modular orchestration of the entire workflow.

## 2. Core Components & Workflow
The pipeline is primarily orchestrated by `master/pipeline_orchestrator.py`.

### Main Workflow Steps:
1.  **Discovery:** (`scraper/list_consultations.py`) Identifies new and existing consultations.
2.  **Scraping:** (`scraper/scrape_single_consultation.py`) Fetches raw data for each consultation.
3.  **Content Processing:** (`utils/data_flow.py` - `ContentProcessor`)
    *   HTML articles/comments: `markdownify` conversion.
    *   Documents (PDFs, etc.): Download, text extraction (`docling`), and then cleaning (`text_cleaner_rs`).
4.  **Storage:** Data is stored in an SQLite database using models defined in `scraper/db_models.py`.

### Key Modules:
-   **`master/`**: Orchestration and main pipeline entry points.
    -   `pipeline_orchestrator.py`: Contains the `PipelineOrchestrator` class.
-   **`scraper/`**: Handles all web scraping tasks.
    -   `scrape_single_consultation.py`: Scrapes a single consultation.
    -   `list_consultations.py`: Discovers consultations.
    -   `db_models.py`: SQLAlchemy database models.
-   **`html_processor/`**: Converts HTML to Markdown. (Note: Main logic seems integrated into `utils.data_flow.ContentProcessor`)
-   **`pdf_processor/`**: Handles PDF downloading and coordinates extraction. (Note: Main logic seems integrated into `utils.data_flow.ContentProcessor` using `docling`).
-   **`rust_processor/`**: Interface for the Rust-based text cleaner (`text_cleaner_rs`). (Note: Main logic seems integrated into `utils.data_flow.ContentProcessor`).
-   **`utils/`**: Shared utilities.
    -   `data_flow.py`: `ContentProcessor` for HTML, PDF, and cleaning operations.
    -   `database.py`: Database connection utilities.
-   **`config/`**: Configuration management.
    -   `config_manager.py`: Loads `pipeline_config.yaml`.
-   **`tests_and_analysis/`**: (Placeholder for tests and analysis scripts related to the pipeline).
-   **`requirements.txt`**: Python dependencies.

## 3. Programmatic Usage
(Details on how to run the pipeline, e.g., using `run_pipeline_entry` from `master.pipeline_orchestrator`, different modes of operation, configuration options).

```python
# Example (conceptual)
# from ai4deliberation_pipeline.master import run_pipeline_entry
#
# # Process a single consultation
# run_pipeline_entry(mode='single', url='https://example.com/consultation/123')
#
# # Update with new consultations
# run_pipeline_entry(mode='update')
```

## 4. Configuration
The pipeline is configured via `config/pipeline_config.yaml`. Key settings include database paths, API keys (if any), and processing parameters.

## 5. Dependencies
See `requirements.txt`. Key dependencies include:
- `sqlalchemy`
- `requests`
- `markdownify`
- `pandas`
- `docling`
- `PyYAML`
- `text-cleaner-rs` (custom Rust bindings)

## 6. Future Enhancements & TODOs
(List of planned improvements or areas needing work, can refer to `PIPELINE_WORKFLOW_CHECKLIST.md` and the main `TODO_DOCUMENTATION.md`). 