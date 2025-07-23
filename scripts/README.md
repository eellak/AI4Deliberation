# Scripts

Batch processing and utility scripts for the AI4Deliberation summarization pipeline.

## Overview
This directory contains executable scripts for running various stages of the consultation summarization pipeline in batch mode.

## Main Scripts

### Pipeline Execution
- `generate_stage1_csvs.py` - Batch processes consultations through Stage 1 (article-level summarization)
- `generate_stage2_3_summaries.py` - Processes Stage 2 (chapter-level) and Stage 3 (part-level) summaries

### Analysis Tools
- `law_mod_classify.py` - Classifies and analyzes law modifications in consultations
- `print_first_two_articles_per_part.py` - Utility for extracting sample articles from each document part
- `read_stage1_csv.py` - Reads and processes Stage 1 CSV output files

## Usage

### Running Stage 1 Processing
```bash
python generate_stage1_csvs.py --consultation-id 123
```

### Running Stage 2 and 3 Processing
```bash
python generate_stage2_3_summaries.py --input stage1_output.csv
```

### Law Modification Analysis
```bash
python law_mod_classify.py --consultation-id 123
```

## Workflow
1. Run `generate_stage1_csvs.py` to create article-level summaries
2. Run `generate_stage2_3_summaries.py` to create hierarchical summaries
3. Use analysis scripts for specific insights

## Output
Scripts typically output to the `outputs_hierarchical_summary/` directory with timestamped filenames.

## Dependencies
These scripts depend on the modular_summarization module and require proper configuration of the AI4Deliberation pipeline.