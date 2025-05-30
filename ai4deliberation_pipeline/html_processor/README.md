# HTML Extraction Pipeline

This pipeline extracts text content from raw HTML stored in the `articles` table of the deliberation database using the `docling` library.

## Purpose

The main scraper (`../complete_scraper/`) is responsible for fetching consultation data, including the raw HTML of articles, and storing it in the database. However, it no longer attempts to extract formatted text content itself.

This pipeline takes the `raw_html` field populated by the scraper and uses the more sophisticated `docling` library to convert it into cleaned, structured text, which is then stored in the `content` field of the `articles` table.

## Prerequisites

- The main scraper (`../complete_scraper/`) must have been run to populate the `articles` table, specifically the `raw_html` column.
- The `docling` library and its dependencies must be installed in the Python environment (e.g., `/mnt/data/venv/`).

## Usage

Navigate to the `AI4Deliberation` directory and run the `html_to_text.py` script using the project's virtual environment:

```bash
cd /mnt/data/AI4Deliberation
./venv/bin/python html_pipeline/html_to_text.py --db-path path/to/your/database.db
```

### Options

- `--db-path`: (Required) Path to the SQLite database file (e.g., `deliberation_data_gr_updated.db`).
- `--limit`: (Optional) Limit the number of articles to process.
- `--batch-size`: (Optional) Number of articles to process in each batch (default: 100).
- `--quality-check-dir`: (Optional) Directory to save original HTML and extracted text side-by-side for manual quality review.

## Workflow

1.  Run the main scraper (`../complete_scraper/scrape_all_consultations.py` or `../complete_scraper/scrape_single_consultation.py`) to fetch data and `raw_html`.
2.  Run this pipeline (`html_pipeline/html_to_text.py`) to process the `raw_html` and populate the `content` column.
