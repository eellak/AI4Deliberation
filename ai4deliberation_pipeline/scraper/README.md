# Scraper

Web scraping module for opengov.gr consultations.

## Overview
This module implements comprehensive web scraping functionality to discover, download, and store Greek government consultation data from opengov.gr.

## Core Components

### Main Scripts
- `scrape_to_db.py` - Main entry point for scraping to database
- `scrape_all_consultations.py` - Batch scraping of all consultations
- `scrape_single_consultation.py` - Scrape individual consultation
- `list_consultations.py` - Discover and list available consultations

### Scraping Modules
- `metadata_scraper.py` - Extracts consultation metadata
- `content_scraper.py` - Downloads consultation content and comments
- `utils.py` - Utility functions for scraping

### Database
- `db_models.py` - SQLAlchemy ORM models
- `db_population_report.py` - Generate reports on scraped data

## Features

### Consultation Discovery
- Automatically discovers new consultations
- Tracks consultation status and updates
- Handles pagination on listing pages

### Data Extraction
- **Metadata**: Title, dates, ministry, status
- **Content**: Full consultation text and documents
- **Comments**: Public comments with threading
- **Documents**: Links to associated PDFs

### Robust Scraping
- Retry logic for failed requests
- Rate limiting to respect server
- Session management for efficiency
- Error handling and logging

## Database Schema
Key tables:
- `consultations` - Main consultation metadata
- `articles` - Individual articles within consultations
- `comments` - Public comments
- `documents` - Associated document references

## Usage

### Scrape All Consultations
```bash
python scrape_all_consultations.py
```

### Scrape Specific Consultation
```bash
python scrape_single_consultation.py --url https://opengov.gr/consultation/123
```

### List Available Consultations
```bash
python list_consultations.py --status active
```

### Generate Report
```bash
python db_population_report.py
```

## Configuration
Configured through pipeline config:
- Request timeouts
- Retry parameters
- Rate limiting
- User agent strings

## Best Practices
- Respect robots.txt
- Use appropriate delays between requests
- Handle errors gracefully
- Log all scraping activities