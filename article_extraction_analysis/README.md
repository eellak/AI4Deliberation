# Article Extraction Analysis

Tools and utilities for parsing and analyzing article structures in Greek legal and consultation documents.

## Overview
This module provides sophisticated parsing capabilities for Greek legal documents, with special handling for Greek numerals and article sequence validation.

## Main Components

### Core Utilities
- `article_parser_utils.py` - Core parsing utilities for Greek article headers and numerals
- `detect_multiple_articles_in_db.py` - Detects when multiple articles are incorrectly stored in single database entries
- `experimental_sequence_detector.py` - Experimental methods for detecting article sequences

### Key Features
- **Greek Numeral Support**: Converts Greek ordinal numbers (ΠΡΩΤΟ, ΔΕΥΤΕΡΟ, etc.) to integers
- **Article Sequence Validation**: Ensures proper article numbering sequence
- **Header Parsing**: Extracts and normalizes article headers from various formats
- **Multi-Article Detection**: Identifies when database entries contain multiple concatenated articles

### Subdirectories
- `range_sequence_analysis/` - Advanced sequence analysis tools
- `unit_tests/` - Test suite for parsing functionality

## Usage
```python
from article_parser_utils import parse_article_header, check_article_sequence_integrity
```

## Dependencies
- Standard Python libraries
- Database connectivity for article detection scripts