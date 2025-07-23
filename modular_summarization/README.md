# Modular Summarization

Sophisticated modular system for summarizing Greek legislative consultation documents using Large Language Models (LLMs).

## Overview
This module implements a multi-stage hierarchical summarization pipeline specifically designed for Greek legislative documents, with Gemma model integration and advanced document structure parsing.

## Architecture

### Core Components
- `workflow.py` - Main workflow orchestration for multi-stage summarization
- `llm.py` - LLM integration layer (supports Gemma models)
- `db_io.py` - Database input/output operations
- `config.py` - Configuration management
- `logger_setup.py` - Logging configuration

### Document Processing
- `hierarchy_parser.py` - Parses document hierarchical structure
- `advanced_parser.py` - Advanced parsing for complex document structures
- `law_utils.py` - Utilities for detecting and handling law modifications
- `schema_enforcement.py` - Ensures output compliance with defined schemas
- `compression.py` - Text compression utilities

### Supporting Utilities
- `prompts.py` - Prompt templates and management
- `retry.py` - Retry logic for API calls
- `utils.py` - General utility functions

## Multi-Stage Summarization Process

### Stage 1: Article-Level Summarization
- Processes individual articles
- Extracts key provisions and requirements
- Identifies law modifications

### Stage 2: Chapter-Level Summarization
- Aggregates article summaries by chapter
- Identifies chapter themes and objectives

### Stage 3: Part-Level Summarization
- Synthesizes chapter summaries into part-level overviews
- Provides high-level document structure understanding

## Key Features
- **Hierarchical Processing**: Respects document structure (articles → chapters → parts)
- **Law Modification Detection**: Identifies changes to existing legislation
- **Schema Enforcement**: Ensures consistent output format
- **Greek Language Optimization**: Specialized handling for Greek legal terminology
- **Retry Mechanisms**: Robust error handling for API interactions
- **Configurable Prompts**: Customizable prompt templates

## Configuration
Configure via `config.yaml` or environment variables:
- LLM model selection
- API endpoints
- Retry parameters
- Output schemas

## Usage
```python
from workflow import SummarizationWorkflow
workflow = SummarizationWorkflow(config)
workflow.process_consultation(consultation_id)
```