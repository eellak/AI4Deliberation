# Tests

Test suite for the AI4Deliberation project components.

## Overview
This directory contains unit tests, integration tests, and test fixtures for various modules of the AI4Deliberation system.

## Test Modules

### Core Tests
- `test_dry_run.py` - Tests for dry-run functionality
- `test_law_utils.py` - Tests for law utility functions
- `test_consultation4.py` - Specific tests for consultation processing
- `run_consultation4.py` - Runner for consultation 4 test suite
- `test_schema_enforcement_sagemaker.py` - Tests for schema enforcement with SageMaker integration

### Test Outputs
- `gemma_4b_output/` - Test outputs from 4B parameter Gemma model
- `gemma_12b_outputs/` - Test outputs from 12B parameter Gemma model

## Running Tests

### Run All Tests
```bash
python -m pytest tests/
```

### Run Specific Test Module
```bash
python -m pytest tests/test_law_utils.py
```

### Run Consultation Tests
```bash
python tests/run_consultation4.py
```

## Test Coverage
Tests cover:
- Document parsing and structure extraction
- Law modification detection
- Schema validation
- LLM integration
- Database operations
- Pipeline orchestration

## Test Data
Test fixtures and sample data are included for:
- Greek legal documents
- Consultation metadata
- Expected outputs for validation

## Adding New Tests
When adding tests:
1. Follow existing naming conventions (test_*.py)
2. Include docstrings explaining test purpose
3. Use appropriate fixtures
4. Ensure tests are independent and repeatable