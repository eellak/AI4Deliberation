# AI4Deliberation

A Python library for scraping and analyzing public deliberation data from the OpenGov.gr platform, specifically targeting the Greek Ministries' public consultations at https://www.opengov.gr/home/category/consultations.

## 🤗 Dataset

**[Greek Public Consultations Dataset on HuggingFace](https://huggingface.co/datasets/glossAPI/opengov.gr-diaboyleuseis/tree/main)**

[![HuggingFace Dataset](https://img.shields.io/badge/🤗-HuggingFace%20Dataset-yellow)](https://huggingface.co/datasets/glossAPI/opengov.gr-diaboyleuseis/tree/main)

## Overview

This project provides tools to extract, analyze, and process data from Greece's public consultation platform. Since OpenGov.gr does not provide an official API, this library implements web scraping techniques to access:

- Consultation documents (Νομοσχέδια)
- Public comments (Σχόλια)
- Explanatory reports (Εκθέσεις)
- Consultation metadata (dates, status, ministry, etc.)

The project has been enhanced with an improved document classification system that accurately categorizes documents into six different types based on their content and purpose.

## Complete Dataset Access

The complete database of scraped consultations is available on the HuggingFace repository. This SQLite database contains all consultations from OpenGov.gr with the improved document classification system and extracted PDF content.

You can download the `deliberation_data_gr_updated.db` file directly from the repository for immediate use in your research or applications.

## Project Structure

```
AI4Deliberation/
├── README.md                    # This documentation file
├── complete_scraper/            # Main scraper implementation
│   ├── content_scraper.py       # Scraper for article content and comments
│   ├── db_models.py             # SQLAlchemy database models
│   ├── db_population_report.py  # Tool to analyze database population
│   ├── list_consultations.py    # Tool to list all consultations to CSV
│   ├── metadata_scraper.py      # Scraper for consultation metadata
│   ├── scrape_all_consultations.py # Scrape multiple consultations
│   ├── scrape_single_consultation.py # Scrape a single consultation
│   ├── TODO.md                  # Project roadmap and completed features
│   └── utils.py                 # Utility functions for all scrapers
└── pdf_pipeline/                # PDF processing pipeline implementation
    ├── export_documents_to_parquet.py  # Export documents for processing
    ├── process_document_redirects.py   # Resolve URL redirects for PDFs
    ├── process_pdfs_with_glossapi.py   # Extract content using GlossAPI
    ├── run_pdf_pipeline.py             # End-to-end pipeline orchestrator
    └── update_database_with_content.py # Update DB with extracted content
```

## Features

- **Comprehensive scraping**: Extract data from all public consultations on OpenGov.gr
- **Metadata extraction**: Capture consultation titles, dates, ministry information, and status
- **Deep content retrieval**: Extract article text, comments, and structured discussion data
- **Document links**: Gather links to official PDF documents (draft laws, reports, etc.)
- **Incremental updates**: Skip already scraped consultations unless forced to re-scrape
- **PDF document processing**: Extract and analyze content from linked PDF documents using [GlossAPI](https://github.com/eellak/glossAPI)
- **Extraction quality assessment**: Evaluate and record the quality of PDF content extraction
- **Robust error handling**: Multiple fallback methods for data extraction
- **Database storage**: Store all data in a normalized SQLite database
- **Analytics**: Generate reports on database population and data quality
- **Document classification**: Categorize documents into six distinct types using a data-driven approach

## Using the Scraper

### Scraping All Consultations

The `scrape_all_consultations.py` script provides a powerful tool to scrape multiple consultations from OpenGov.gr. Below are examples of how to use it:

```bash
# Basic usage - scrape all consultations and store in the default database
python3 complete_scraper/scrape_all_consultations.py

# Scrape a limited number of consultations
python3 complete_scraper/scrape_all_consultations.py --max-count 10

# Scrape a specific page range
python3 complete_scraper/scrape_all_consultations.py --start-page 5 --end-page 10

# Force re-scrape of consultations already in the database
python3 complete_scraper/scrape_all_consultations.py --force-scrape

# Use a different database file
python3 complete_scraper/scrape_all_consultations.py --db-path "sqlite:///path/to/custom_db.db"

# Commit changes to database in smaller batches
python3 complete_scraper/scrape_all_consultations.py --batch-size 5
```

### Scraping a Single Consultation

To scrape a single consultation, use `scrape_single_consultation.py`:

```bash
python3 complete_scraper/scrape_single_consultation.py "https://www.opengov.gr/ministry_code/?p=consultation_id"
```

### Processing PDF Documents

The project includes a dedicated PDF processing pipeline for extracting content from document links:

```bash
# Run the complete PDF processing pipeline
python3 pdf_pipeline/run_pdf_pipeline.py

# Run specific steps of the pipeline (1=export, 2=redirects, 3=processing, 4=database update)
python3 pdf_pipeline/run_pdf_pipeline.py --start=2 --end=4

# Run individual components for more control
python3 pdf_pipeline/export_documents_to_parquet.py  # Step 1: Export document URLs
python3 pdf_pipeline/process_document_redirects.py   # Step 2: Resolve URL redirects
python3 pdf_pipeline/process_pdfs_with_glossapi.py   # Step 3: Process PDFs with GlossAPI
python3 pdf_pipeline/update_database_with_content.py # Step 4: Update database with content
```

The pipeline intelligently processes only documents that need content extraction, manages its own workspace, and provides detailed logs of the process. PDF content extraction is performed using [GlossAPI](https://github.com/eellak/glossAPI), an advanced document processing library developed for extracting and analyzing Greek text from PDFs.

## Database Schema

The scraped data is stored in a SQLite database with the following structure:

### Tables

1. **ministries**
   - `id`: Primary key
   - `code`: Ministry code used in URLs
   - `name`: Full ministry name
   - `url`: URL to ministry's main page

2. **consultations**
   - `id`: Primary key
   - `post_id`: OpenGov.gr internal post ID
   - `title`: Consultation title
   - `start_date`: Start date of the consultation
   - `end_date`: End date of the consultation
   - `url`: Full URL to the consultation
   - `ministry_id`: Foreign key to ministries table
   - `is_finished`: Whether the consultation has ended
   - `accepted_comments`: Number of accepted comments
   - `total_comments`: Total comment count

3. **documents**
   - `id`: Primary key
   - `consultation_id`: Foreign key to consultations table
   - `title`: Document title
   - `url`: URL to the document file
   - `type`: Document type (see classification below)

4. **articles**
   - `id`: Primary key
   - `consultation_id`: Foreign key to consultations table
   - `post_id`: Internal post ID for the article
   - `title`: Article title
   - `content`: Full text content of the article
   - `url`: URL to the article page

5. **comments**
   - `id`: Primary key
   - `article_id`: Foreign key to articles table
   - `comment_id`: Internal comment ID
   - `username`: Name of commenter
   - `date`: Comment submission date
   - `content`: Full text of the comment

### Document Classification

Documents are classified into six categories:

1. **law_draft**: Draft legislation documents containing both "ΣΧΕΔΙΟ" and "ΝΟΜΟΥ" (31.0%)
2. **analysis**: Regulatory impact analysis documents containing both "ΑΝΑΛΥΣΗ" and "ΣΥΝΕΠΕΙΩΝ" (10.8%)
3. **deliberation_report**: Public consultation reports containing both "ΕΚΘΕΣΗ" and "ΔΙΑΒΟΥΛΕΥΣΗ" (5.2%)
4. **other_draft**: Other draft documents containing "ΣΧΕΔΙΟ" but not "ΝΟΜΟΥ" (8.5%)
5. **other_report**: Other report documents containing "ΕΚΘΕΣΗ" but not "ΔΙΑΒΟΥΛΕΥΣΗ" (12.7%)
6. **other**: Documents not falling into any of the above categories (31.8%)


## Development Status

This project is in the initial development phase. Contributions and feedback are welcome.
