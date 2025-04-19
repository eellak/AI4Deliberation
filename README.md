# AI4Deliberation

A Python library for scraping and analyzing public deliberation data from the OpenGov.gr platform, specifically targeting the Greek Ministries' public consultations at https://www.opengov.gr/home/category/consultations.

[![HuggingFace Dataset](https://img.shields.io/badge/🤗-HuggingFace%20Dataset-yellow)](https://huggingface.co/datasets/glossAPI/opengov.gr-diaboyleuseis/tree/main)

## Overview

This project provides tools to extract, analyze, and process data from Greece's public consultation platform. Since OpenGov.gr does not provide an official API, this library implements web scraping techniques to access:

- Consultation documents (Νομοσχέδια)
- Public comments (Σχόλια)
- Explanatory reports (Εκθέσεις)
- Consultation metadata (dates, status, ministry, etc.)

The project has been enhanced with an improved document classification system that accurately categorizes documents into six different types based on their content and purpose.

## Dataset

A full database of scraped consultations is available on HuggingFace:

**[Greek Public Consultations Dataset](https://huggingface.co/datasets/glossAPI/opengov.gr-diaboyleuseis/tree/main)**

This SQLite database contains all consultations from OpenGov.gr with the improved document classification system. You can download the `deliberation_data_gr.db` file directly from the repository.

## Project Structure

```
AI4Deliberation/
├── README.md                    # This documentation file
├── SPECIFICATIONS.md            # Technical specifications document
├── SELECTORS.md                 # CSS/XPath selectors for scraping
├── deliberation_data_gr.db      # SQLite database for storing scraped data
└── complete_scraper/            # Main scraper implementation
    ├── content_scraper.py       # Scraper for article content and comments
    ├── db_models.py             # SQLAlchemy database models
    ├── db_population_report.py  # Tool to analyze database population
    ├── list_consultations.py    # Tool to list all consultations to CSV
    ├── metadata_scraper.py      # Scraper for consultation metadata
    ├── scrape_all_consultations.py # Scrape multiple consultations
    ├── scrape_single_consultation.py # Scrape a single consultation
    └── utils.py                # Utility functions for all scrapers
```

## Features

- **Comprehensive scraping**: Extract data from all public consultations on OpenGov.gr
- **Metadata extraction**: Capture consultation titles, dates, ministry information, and status
- **Deep content retrieval**: Extract article text, comments, and structured discussion data
- **Document links**: Gather links to official PDF documents (draft laws, reports, etc.)
- **Incremental updates**: Skip already scraped consultations unless forced to re-scrape
- **Robust error handling**: Multiple fallback methods for data extraction
- **Database storage**: Store all data in a normalized SQLite database
- **Analytics**: Generate reports on database population and data quality
- **Advanced document classification**: Categorize documents into six distinct types using a data-driven approach

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

## CSS/XPath Selectors

Based on analysis of the OpenGov.gr platform, we've identified the following key elements:

- Main consultations list: Accessible at `/home/category/consultations`
- Individual consultation pages: Structured as e.g. `/ypex/?p=1045`
- Comments: Associated with specific articles and accessible via article pages
- Document links: PDF and other documents embedded within consultation pages

## Development Status

This project is in the initial development phase. Contributions and feedback are welcome.
