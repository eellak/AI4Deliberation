# Cleaning

Document cleaning and analysis pipeline for Greek legal documents.

## Overview
This module provides a comprehensive multi-stage cleaning pipeline for processing legal documents, with special support for Greek text and integration with Rust-based performance optimizations.

## Main Components

### Core Scripts
- `pipeline_orchestrator.py` - Master orchestrator for the cleaning pipeline
- `analyze_badness.py` - Analyzes document quality metrics ("badness" scores)
- `extraction_metrics_rs/` - Rust-Python integration for high-performance text processing

### Key Features
- **Multi-Stage Pipeline**: Sequential cleaning stages for optimal results
- **Quality Metrics**: Badness score calculation for document quality assessment
- **Table Detection**: Identifies and removes tables from documents
- **Bilingual Support**: Handles both Greek and Latin scripts
- **Performance Optimization**: Rust integration for computationally intensive operations

### Subdirectories
- `nomoi/` - Specialized processing for Greek legal documents (νόμοι = laws)
- `extraction_metrics_rs/` - Rust module for performance-critical operations

## Processing Stages
1. Initial text extraction
2. Table detection and removal
3. Quality analysis and scoring
4. Final cleanup and formatting

## Usage
```python
from pipeline_orchestrator import CleaningPipeline
pipeline = CleaningPipeline()
pipeline.process_document(document_path)
```

## Dependencies
- Rust toolchain (for extraction_metrics_rs)
- Python 3.8+
- Various text processing libraries