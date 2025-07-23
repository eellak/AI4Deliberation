# Rust Processor

High-performance text processing module using Rust integration.

## Overview
This module provides Rust-based text cleaning and analysis capabilities, offering significant performance improvements for computationally intensive text processing operations.

## Components

### Python Scripts
- `rust_processor.py` - Python interface to Rust processing functions
- `test_rust_batch.py` - Batch testing utilities for Rust processor
- `debug_database.py` - Database debugging tools for Rust processing results

## Key Features

### Text Processing
- **High-Performance Cleaning**: Rust-based algorithms for fast text cleaning
- **Badness Score Calculation**: Quantifies document quality issues
- **Language Detection**: Determines Greek/English language percentages
- **Batch Processing**: Efficient processing of multiple documents

### Quality Metrics
The processor calculates various quality metrics:
- Badness scores (lower is better)
- Language distribution percentages
- Character encoding issues
- Structural problems

## Integration
The Rust processor integrates with:
- PDF extraction pipeline (processes markdown files)
- Database storage (updates quality metrics)
- Cleaning pipeline (provides cleaned text)

## Performance Benefits
- 10-100x faster than pure Python implementations
- Memory efficient for large documents
- Parallel processing capabilities
- Minimal GIL impact

## Usage
```python
from rust_processor import RustProcessor

processor = RustProcessor()
result = processor.process_document(markdown_content)
# Returns: {
#     'cleaned_text': str,
#     'badness_score': float,
#     'greek_percentage': float,
#     'english_percentage': float
# }
```

## Building
Requires Rust toolchain for compilation:
```bash
cargo build --release
```

## Dependencies
- Rust toolchain
- PyO3 for Python bindings
- Database connectivity libraries