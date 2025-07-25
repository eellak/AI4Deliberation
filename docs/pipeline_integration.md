# AI4Deliberation Pipeline Integration Overview

## System Architecture

The AI4Deliberation pipeline is a modular system that transforms Greek legislative consultations into citizen-friendly summaries and evaluates their quality. The pipeline consists of two main phases:

1. **Summarization Phase**: Uses Gemma 3 27B IT to progressively summarize legislation
2. **Evaluation Phase**: Uses Gemini 2.5 Pro to assess summary quality

## Directory Structure

```
/mnt/data/AI4Deliberation/
├── modular_summarization/      # Core summarization modules
│   ├── config.py              # Central configuration
│   ├── workflow.py            # Stage 1 orchestration
│   ├── stage23_helpers_v2.py  # Stage 2 helpers
│   ├── stage3_expanded.py     # Stage 3 narrative logic
│   ├── prompts.py             # All prompt templates
│   ├── llm.py                 # LLM interface (Gemma)
│   └── validator.py           # JSON validation
├── scripts/                    # Entry points
│   ├── generate_stage1_csvs.py
│   ├── generate_stage2_3_summaries.py
│   └── run_multiple_consultations.sh
├── summary_evaluation/         # Evaluation module
│   ├── evaluate.py            # Main evaluation script
│   ├── prompts.py             # Evaluation prompts
│   └── utils.py               # Helper functions
├── outputs/                    # Generated summaries
│   ├── cons{N}_stage1.csv
│   ├── cons{N}_stage2.csv
│   ├── cons{N}_stage3.csv
│   └── cons{N}_final_summary.txt
└── outputs_evaluation/         # Evaluation results
    └── evaluation_results.csv
```

## Execution Flow

### 1. Data Preparation
```bash
# Export legislation from database to dry_run files
python export_dry_run.py --consultation-ids 1 2 3
```

### 2. Stage 1: Article Summarization
```bash
python scripts/generate_stage1_csvs.py \
    --consultation-ids 1 2 3 \
    --output-dir outputs \
    --real  # Use actual Gemma model
```

### 3. Stages 2-3 + Polish: Aggregation
```bash
python scripts/generate_stage2_3_summaries.py \
    --ids 1 2 3 \
    --csv-dir outputs \
    --output-dir outputs \
    --polish \
    --real
```

### 4. Evaluation
```bash
python -m summary_evaluation.evaluate \
    --summaries-dir outputs \
    --legislation-dir . \
    --out outputs_evaluation/results.csv
```

## Configuration Management

### Model Settings (`modular_summarization/config.py`)

```python
# Model configuration
DEFAULT_MODEL_ID = "google/gemma-3-27b-it"
TORCH_DTYPE = "bfloat16"
MAX_CONTEXT_TOKENS = 8192

# Generation parameters
INITIAL_TEMPERATURE = 0.01
RETRY_TEMPERATURE = 0.2

# Token budgets
MAX_TOKENS_STAGE1 = 1200
MAX_TOKENS_STAGE2 = 1200
MAX_TOKENS_STAGE3 = 1600

# Database settings
DB_PATH = "/path/to/database.db"
TABLE_NAME = "articles"
```

### Environment Variables

```bash
# For evaluation with Gemini
export GOOGLE_API_KEY="your-api-key"

# For evaluation with OpenAI
export OPENAI_API_KEY="your-api-key"

# GPU settings for Gemma
export CUDA_VISIBLE_DEVICES="0"
export TOKENIZERS_PARALLELISM="false"
```

## Key Integration Points

### 1. Database Interface
- **Input**: SQLite database with articles and consultations tables
- **Schema**: 
  - `articles`: id, consultation_id, title, content, content_cleaned
  - `consultations`: id, title, start_date, end_date

### 2. File Formats

**Stage 1 CSV**:
```csv
article_id,article_number,part,chapter,classifier_decision,summary_text,raw_content,law_reference
123,1,Α,Α,skopos,"","{full article text}",""
124,2,Α,Α,new_provision,"Θεσπίζει νέο πλαίσιο για...","{full article text}",""
```

**Final Summary Text**:
```
ΜΕΡΟΣ Α:

Αλλαγές:
Τροποποιούνται οι νόμοι ν. 4174/2013 και ν. 4308/2014.

Περίληψη:
[Part summary text...]
```

### 3. Model Loading

**Gemma (Local GPU)**:
```python
from modular_summarization.llm import get_generator
generator = get_generator(dry_run=False)  # Loads Gemma 3 27B IT
```

**Gemini (API)**:
```python
import google.generativeai as genai
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-pro")
```

## Batch Processing

### Shell Script Automation
```bash
#!/bin/bash
# scripts/run_pipeline.sh

CONSULTATIONS="1 2 3 4 5"
OUTPUT_DIR="outputs"

# Stage 1
python scripts/generate_stage1_csvs.py \
    --consultation-ids $CONSULTATIONS \
    --output-dir $OUTPUT_DIR \
    --real

# Stages 2-3 + Polish
python scripts/generate_stage2_3_summaries.py \
    --ids $CONSULTATIONS \
    --csv-dir $OUTPUT_DIR \
    --output-dir $OUTPUT_DIR \
    --polish \
    --real

# Evaluation
python -m summary_evaluation.evaluate \
    --summaries-dir $OUTPUT_DIR \
    --legislation-dir . \
    --out $OUTPUT_DIR/evaluation_results.csv
```

### Python Orchestration
```python
from modular_summarization.workflow import run_workflow

# Process consultation
result = run_workflow(
    consultation_id=123,
    dry_run=False,
    enable_trace=True
)

# Access results
law_mods = result["law_modifications"]
new_provisions = result["law_new_provisions"]
```

## Monitoring and Debugging

### 1. Trace Logs
- **Location**: `outputs/cons{N}_trace.log`
- **Contents**: All prompts and LLM outputs
- **Enable**: Set `ENABLE_REASONING_TRACE = True`

### 2. Progress Tracking
```python
# In scripts
import logging
logging.basicConfig(level=logging.INFO)
```

### 3. Dry Run Mode
```bash
# Test pipeline without GPU/API calls
python scripts/generate_stage1_csvs.py \
    --consultation-ids 1 \
    --dry-run
```

## Performance Optimization

### 1. GPU Memory Management
- **Model Loading**: ~40GB VRAM required for Gemma 3 27B
- **Batch Size**: Process one consultation at a time
- **Flash Attention**: Automatically enabled if available

### 2. API Rate Limiting
- **Gemini**: Built-in retry with exponential backoff
- **Token Limits**: Respect model context windows

### 3. Parallel Processing
```bash
# Run multiple consultations in parallel
parallel -j 4 python scripts/generate_stage1_csvs.py \
    --consultation-ids {} --real ::: 1 2 3 4
```

## Customization Points

### 1. Adding New Prompts
```python
# In modular_summarization/prompts.py
CUSTOM_PROMPT = """
Your custom prompt template here...
Input: {input_text}
"""
```

### 2. Modifying Evaluation Criteria
```python
# In summary_evaluation/prompts.py
# Add new criterion to EVALUATION_PROMPT_TEMPLATE
"new_criterion": {
    "reasoning": "...",
    "score": 0
}
```

### 3. Custom Post-Processing
```python
# After Stage 3
def custom_post_process(summary_text):
    # Your processing logic
    return processed_text
```

## Common Issues and Solutions

### 1. Out of Memory
- Reduce batch size
- Use model quantization
- Enable CPU offloading

### 2. JSON Parsing Errors
- Check LM-Format-Enforcer configuration
- Increase retry temperature
- Add fallback parsing logic

### 3. API Timeouts
- Implement chunking for long documents
- Increase timeout values
- Use retry decorators

## Future Enhancements

1. **Multi-GPU Support**: Distribute model across GPUs
2. **Streaming Generation**: Process chunks progressively
3. **Caching Layer**: Store intermediate results
4. **Web Interface**: Interactive summary generation
5. **Multi-Language Support**: Extend beyond Greek
6. **Fine-Tuning**: Adapt Gemma specifically for Greek legal text