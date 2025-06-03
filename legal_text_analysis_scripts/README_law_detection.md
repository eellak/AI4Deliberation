# Greek Law Detection System

## Overview

This project implements a simplified system for detecting references to Greek laws within consultation articles and matching them with our Greek laws database.

## Components

### 1. Database Extension
- **File**: `create_greek_laws_table.py`
- **Purpose**: Extends the existing consultation database with a new `Greek_laws` table
- **Data Source**: Combines metadata from gazette processing parquet files with markdown content
- **Records**: 1,761 Greek laws with full text content

### 2. Simplified Law Detection
- **Files**: `simplified_law_detection.py`, `law_detection_summary.py`
- **Purpose**: Detect law references in consultation articles using a simplified regex pattern

### Simplified Regex Pattern
```regex
(?ix)  # Case-insensitive, verbose
(?P<type>ν\.|Ν\.|νόμου|νόμο)  # Only these three patterns
\s*
(?P<number>\d+)               # Law number (required)
\s*/\s*
(?P<year>\d{4})               # Year (required)
```

**Key Features:**
- Matches only: `ν.`, `Ν.`, `νόμου`, `νόμο`
- Excludes: `ν.δ.` (νομοθετικά διατάγματα)
- Requires both law number and year
- Case-insensitive matching

## Test Results

### Regex Pattern Testing
✅ **Successful matches:**
- `ν. 4412/2016` → Law 4412/2016
- `Ν. 4624/2019` → Law 4624/2019  
- `νόμο 4808/2021` → Law 4808/2021
- `νόμου 4727/2020` → Law 4727/2020

❌ **Correctly excluded:**
- `ν.δ. 123/2020` (presidential decree)
- `νόμος 4727/2020` (without number/year format)

### Consultation Analysis Results
**Dataset:** 100 consultation articles

**Detection Results:**
- Articles with law references: **81/100 (81%)**
- Total law references found: **347**
- Unique laws referenced: **51**

**Database Matching:**
- Laws found in Greek_laws table: **37/51 (72.5%)**

### Most Frequently Referenced Laws
1. Law 4887/2022: 182 references
2. Law 4871/2021: 35 references  
3. Law 4399/2016: 17 references
4. Law 4449/2017: 10 references
5. Law 4938/2022: 8 references

### Sample Matched Laws in Database
- **Ν. 4622/2019**: ΕΠΙΤΕΛΙΚΟ ΚΡΑΤΟΣ: ΟΡΓΑΝΩΣΗ, ΛΕΙΤΟΥΡΓΙΑ ΚΑΙ ΔΙΑΦΑΝΕΙΑ ΤΗΣ ΚΥΒ...
- **Ν. 4798/2021**: ΚΩΔΙΚΑΣ ΔΙΚΑΣΤΙΚΩΝ ΥΠΑΛΛΗΛΩΝ ΚΑΙ ΛΟΙΠΕΣ ΕΠΕΙΓΟΥΣΕΣ ΔΙΑΤΑΞΕΙΣ...
- **Ν. 4871/2021**: ΜΕΤΑΡΡΥΘΜΙΣΕΙΣ ΣΤΟ ΝΟΜΟΘΕΤΙΚΟ ΠΛΑΙΣΙΟ ΤΗΣ ΕΘΝΙΚΗΣ ΣΧΟΛΗΣ ΔΙΚ...

### Unmatched Laws
Laws referenced in consultations but not in our Greek_laws table (older laws):
- Law 2072/1992
- Law 1406/1983
- Law 3299/2004
- Law 2601/1998

## Database Schema

### Greek_laws Table
```sql
CREATE TABLE Greek_laws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    law_type TEXT,                    -- Type of law (Ν., etc.)
    law_number TEXT,                  -- Law number
    description TEXT,                 -- Law description
    fek_title TEXT,                   -- Government Gazette title
    fek_url TEXT,                     -- URL to gazette
    date TEXT,                        -- Publication date
    entry_year INTEGER,               -- Extracted year
    pages TEXT,                       -- Number of pages
    preferred_url TEXT,               -- Preferred access URL
    download_success BOOLEAN,         -- Download status
    filename TEXT,                    -- PDF filename
    download_error TEXT,              -- Any download errors
    download_retry_count INTEGER,     -- Retry attempts
    extraction TEXT,                  -- Extraction quality
    processing_stage TEXT,            -- Processing pipeline stage
    markdown_content TEXT,            -- Full law text in markdown
    content_size INTEGER,             -- Size of content in characters
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Usage Examples

### Basic Law Detection
```python
from simplified_law_detection import find_law_references_in_text

text = "Σύμφωνα με το ν. 4412/2016 και τον Ν. 4624/2019"
references = find_law_references_in_text(text)
# Returns: [{'number': '4412', 'year': 2016, ...}, {'number': '4624', 'year': 2019, ...}]
```

### Database Querying
```python
# Find a specific law
SELECT * FROM Greek_laws WHERE law_number = '4887' AND entry_year = 2022;

# Search by content
SELECT law_number, entry_year, description 
FROM Greek_laws 
WHERE markdown_content LIKE '%ψηφιακός%'
ORDER BY entry_year DESC;
```

## Files Structure
```
legal_text_analysis_scripts/
├── create_greek_laws_table.py      # Database creation script
├── simplified_law_detection.py     # Main detection script  
├── law_detection_summary.py        # Summary analysis script
├── regex_capture_groups.py         # Original complex regex patterns
└── README_law_detection.md         # This documentation
```

## Key Insights

1. **High Detection Rate**: 81% of consultation articles contain law references
2. **Frequent References**: Some laws (like 4887/2022) are referenced very frequently across consultations
3. **Good Database Coverage**: 72.5% of referenced laws are available in our database
4. **Temporal Pattern**: Unmatched laws are typically older (1980s-2000s) predating our dataset

## Future Improvements

1. **Expand Database**: Include older laws (pre-2005) to improve coverage
2. **Enhanced Patterns**: Add support for law amendments and modifications
3. **Context Analysis**: Analyze the context around law references
4. **Cross-References**: Link consultation articles with related laws automatically 