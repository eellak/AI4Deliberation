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
└── README.md                 # This file
```

## Features (Planned)

- Scrape complete lists of consultations from ministries
- Extract consultation metadata (title, dates, ministry)
- Download consultation documents
- Extract public comments and their metadata
- Search and filter consultations by various criteria
- Export data in multiple formats (JSON, CSV, etc.)

## CSS/XPath Selectors

Based on analysis of the OpenGov.gr platform, we've identified the following key elements:

- Main consultations list: Accessible at `/home/category/consultations`
- Individual consultation pages: Structured as e.g. `/ypex/?p=1045`
- Comments: Associated with specific articles and accessible via article pages
- Document links: PDF and other documents embedded within consultation pages

## Development Status

This project is in the initial development phase. Contributions and feedback are welcome.
