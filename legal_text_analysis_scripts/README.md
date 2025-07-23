# Legal Text Analysis Scripts

Specialized tools for analyzing Greek legal texts and detecting references to laws, presidential decrees, and ministerial decisions.

## Overview
This module provides regex-based pattern matching and analysis tools specifically designed for Greek legal documents.

## Main Scripts

### Core Functionality
- `export_consultations.py` - Exports consultation data from SQLite database to text files
- `process_legal_texts.py` - Main processing script with comprehensive regex patterns for legal references
- `law_detection_summary.py` - Simplified law detection with summary generation
- `simplified_law_detection.py` - Streamlined version of law detection
- `regex_capture_groups.py` - Contains regex patterns for legal text matching
- `create_greek_laws_table.py` - Creates database tables for Greek laws

### Key Features
- **Legal Reference Detection**: Identifies references to:
  - Laws (Νόμος/Ν.)
  - Presidential Decrees (Προεδρικό Διάταγμα/Π.Δ.)
  - Ministerial Decisions (Υπουργική Απόφαση/Υ.Α.)
- **Greek Language Support**: Regex patterns designed for Greek legal terminology
- **Database Integration**: Exports and processes data from SQLite databases
- **Pattern Library**: Comprehensive regex patterns for various legal citation formats

## Usage
```bash
# Export consultations to text files
python export_consultations.py

# Process legal texts and detect references
python process_legal_texts.py

# Generate law detection summary
python law_detection_summary.py
```

## Regular Expression Patterns
The scripts use sophisticated regex patterns to match various Greek legal citation formats, including:
- Abbreviated and full forms
- Different date formats
- Article and paragraph references