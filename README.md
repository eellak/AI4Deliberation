# AI4Deliberation

A Python library for scraping and analyzing public deliberation data from the OpenGov.gr platform, specifically targeting the Greek Ministries' public consultations at https://www.opengov.gr/home/category/consultations.

## Overview

This project provides tools to extract, analyze, and process data from Greece's public consultation platform. Since OpenGov.gr does not provide an official API, this library implements web scraping techniques to access:

- Consultation documents (Νομοσχέδια)
- Public comments (Σχόλια)
- Explanatory reports (Εκθέσεις)
- Consultation metadata (dates, status, ministry, etc.)

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

## CSS/XPath Selectors

Based on analysis of the OpenGov.gr platform, we've identified the following key elements:

- Main consultations list: Accessible at `/home/category/consultations`
- Individual consultation pages: Structured as e.g. `/ypex/?p=1045`
- Comments: Associated with specific articles and accessible via article pages
- Document links: PDF and other documents embedded within consultation pages

## Development Status

This project is in the initial development phase. Contributions and feedback are welcome.
