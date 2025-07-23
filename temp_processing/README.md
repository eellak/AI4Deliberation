# Temp Processing

Temporary storage directory for intermediate processing files.

## Overview
This directory serves as a workspace for temporary files during document processing operations.

## Directory Structure

### Subdirectories
- `cleaned/` - Stores cleaned text files after processing
- `markdown/` - Contains markdown conversions of documents
- `pdfs/` - Downloaded PDF documents awaiting processing

## Usage
This directory is used by various pipeline components for:
- Staging files between processing steps
- Temporary storage during format conversions
- Caching downloaded documents

## Important Notes
- Files in this directory are temporary and may be deleted after processing
- Not intended for long-term storage
- Automatically managed by the pipeline
- May contain large PDF files during processing

## Cleanup
The pipeline may periodically clean this directory. Do not store important files here.

## File Naming
Temporary files typically use patterns like:
- `document_*.pdf` for downloaded PDFs
- `cleaned_*.txt` for processed text
- `*.md` for markdown conversions