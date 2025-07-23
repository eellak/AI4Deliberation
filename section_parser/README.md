# Section Parser

Utilities for parsing hierarchical structure from Greek legal documents.

## Overview
This module specializes in extracting and understanding the hierarchical organization of Greek legal documents, including parts (ΜΕΡΟΣ) and chapters (ΚΕΦΑΛΑΙΟ).

## Main Components

### Scripts
- `section_parser.py` - Main parser for extracting document sections and hierarchy
- `investigate_continuity.py` - Analyzes continuity and consistency of document structure

### Key Features
- **Greek Numeral Conversion**: Converts Greek numerals (Α', Β', Γ', etc.) to integers
- **Hierarchy Extraction**: Identifies and extracts:
  - ΜΕΡΟΣ (Parts)
  - ΚΕΦΑΛΑΙΟ (Chapters)
  - Article sequences
- **Structure Validation**: Ensures logical continuity in document structure
- **Pattern Matching**: Robust regex patterns for various formatting styles

## Functionality
The parser can:
1. Extract part and chapter numbers from article titles
2. Convert Greek ordinals to numeric values
3. Build hierarchical document maps
4. Validate structural integrity

## Usage
```python
from section_parser import parse_document_structure

structure = parse_document_structure(document_text)
# Returns hierarchical mapping of parts, chapters, and articles
```

## Greek Numeral Support
Handles conversion of:
- Α' → 1
- Β' → 2
- Γ' → 3
- And so on...

## Dependencies
- Python standard library
- regex module for advanced pattern matching