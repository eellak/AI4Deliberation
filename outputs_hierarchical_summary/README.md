# Outputs Hierarchical Summary

Storage directory for outputs from the hierarchical summarization pipeline.

## Overview
This directory contains the results of multi-stage summarization processing for Greek legislative consultations.

## Directory Structure

### Output Files by Stage
- `stage1_*.csv` - Article-level summarization results
- `stage2_*.csv` - Chapter-level summarization results  
- `stage3_*.csv` - Part-level summarization results
- `final_summary_*.csv` - Complete hierarchical summaries

### Additional Outputs
- `trace_*.log` - Processing trace logs for debugging
- `polish_trace_*.log` - Logs from summary polishing phase
- Consultation-specific subdirectories

## File Format
CSV files typically contain:
- Document identifiers (consultation ID, article/chapter/part numbers)
- Original text excerpts
- Generated summaries
- Metadata (processing timestamps, model versions)

## Usage
These files are generated automatically by the modular summarization pipeline. They can be used for:
- Analysis of summarization quality
- Input to downstream processes
- Human review and validation
- Performance evaluation

## Data Schema
Each CSV follows a consistent schema defined by the summarization pipeline, ensuring compatibility across different processing runs.