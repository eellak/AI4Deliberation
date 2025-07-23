# PDF Processor

PDF document processing pipeline for extracting and converting consultation documents.

## Overview
This module handles the complete PDF processing workflow, from downloading documents to extracting text and storing structured content in the database.

## Core Components

### Main Processing Scripts
- `pdf_processor.py` - Core PDF processing logic
- `run_pdf_pipeline.py` - Pipeline runner for batch processing
- `process_pdfs_with_glossapi.py` - Integration with GlossAPI/Docling for text extraction

### Support Scripts
- `process_document_redirects.py` - Handles URL redirects for document downloads
- `export_documents_to_parquet.py` - Exports processed documents to Parquet format
- `update_database_with_content.py` - Updates database with extracted content
- `test_single_consultation.py` - Testing utility for individual consultations

### Setup/Reset Scripts
- `setup_test_data.py` - Prepares test data for development
- `reset_test_data.py` - Cleans test data

## Processing Workflow

1. **Download Phase**
   - Downloads PDF documents from consultation URLs
   - Handles redirects and failed downloads
   - Stores in `workspace/downloads/`

2. **Extraction Phase**
   - Uses GlossAPI/Docling for text extraction
   - Converts PDFs to markdown format
   - Stores in `workspace/markdown/`

3. **Storage Phase**
   - Updates database with extracted content
   - Links documents to consultations
   - Maintains processing metadata

## Directory Structure
```
workspace/
├── downloads/          # Downloaded PDF files
├── markdown/           # Extracted markdown content
├── sections/          # Parsed document sections
└── download_results/  # Processing results and logs
```

## Key Features
- **Robust Downloading**: Retry logic and redirect handling
- **Quality Extraction**: Uses state-of-the-art PDF extraction
- **Format Preservation**: Maintains document structure in markdown
- **Batch Processing**: Efficient handling of multiple documents
- **Error Recovery**: Tracks and retries failed documents

## Usage
```bash
# Process all pending PDFs
python run_pdf_pipeline.py

# Process specific consultation
python test_single_consultation.py --consultation-id 123

# Export to Parquet
python export_documents_to_parquet.py
```

## Dependencies
- GlossAPI/Docling for PDF extraction
- requests for downloading
- pandas for data manipulation
- SQLAlchemy for database operations