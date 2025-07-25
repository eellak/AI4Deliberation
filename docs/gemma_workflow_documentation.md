# Gemma 3 27B IT Workflow Documentation

## Overview

The AI4Deliberation pipeline uses Google's Gemma 3 27B IT (Instruction-Tuned) model to progressively summarize Greek legislative consultations from individual articles up to complete, citizen-friendly summaries. The workflow consists of four main stages plus an evaluation phase.

## Model Configuration

### Base Model: `google/gemma-3-27b-it`
- **Parameters**: 27 billion
- **Precision**: bfloat16
- **Context Window**: 8,192 tokens
- **Architecture**: Transformer with Flash Attention 2 support
- **Temperature Settings**:
  - Initial: 0.01 (near-deterministic)
  - Retry: 0.2 (for failed validation)
- **Top-p Sampling**:
  - Initial: 0.95 (near-greedy)
  - Retry: 0.9 (slightly wider)

## Stage 1: Article-Level Summarization

### Purpose
Process individual legislative articles to extract key information and classify their intent.

### Input
- Raw article text from SQLite database
- Article metadata (ID, number, title)

### Processing Logic

1. **Article Classification**:
   - **Introductory Articles** (Σκοπός/Αντικείμενο):
     - Article 1 → Σκοπός (Purpose)
     - Article 2 → Αντικείμενο (Subject)
     - Preserved verbatim, no LLM processing
   
   - **Law Modification Articles**:
     - Detected via pattern matching for law references
     - Extracts quoted segments (minimum 10 words)
     - Processes each modification separately
   
   - **New Provision Articles**:
     - All articles not classified as above
     - Summarized as establishing new rules/procedures

2. **Summarization Approach**:
   - **Short articles** (<80 words): Preserved verbatim
   - **Long articles**: Compressed using LLM with JSON-constrained generation

3. **JSON Schema Enforcement**:
   - Uses LM-Format-Enforcer for guaranteed valid JSON
   - Schema: `{"summary": "string"}`
   - Maximum 2 retries on validation failure

### Prompts Used

**Law Modification** (`law_mod_json`):
```
Δίνεται απόσπασμα από νομοσχέδιο που τροποποιεί τον νόμο {law_name}.
Γράψε μια σύντομη περίληψη (~20 λέξεις) της αλλαγής που περιγράφεται στο παρακάτω απόσπασμα:
{quoted_change}
Απάντησε σε JSON: {"summary": "..."}
```

**New Provision** (`law_new_json`):
```
Δίνεται άρθρο νομοσχεδίου που εισάγει νέα διάταξη.
Γράψε μια σύντομη περίληψη (~20 λέξεις) εξηγώντας τι θεσπίζει το άρθρο:
{article}
Απάντησε σε JSON: {"summary": "..."}
```

### Output
- CSV file: `cons{N}_stage1.csv`
- Columns: article_id, article_number, part, chapter, classifier_decision, summary_text, raw_content, law_reference
- Trace log: `cons{N}_trace.log` (if enabled)

### Token Limits
- Maximum per summary: 1,200 tokens
- Typical output: 20-50 words per article

## Stage 2: Chapter-Level Aggregation

### Purpose
Combine article summaries within each chapter into cohesive chapter summaries.

### Input
- Article summaries from Stage 1 CSV
- Grouped by (part, chapter) tuples

### Processing Logic

1. **Bullet Point Aggregation**:
   - Articles sorted by article number
   - Each summary formatted as bullet point
   - Introductory articles excluded

2. **Compression Strategy**:
   - Target: ~50% compression ratio
   - Minimum 200 words, maximum 300 words per chapter
   - Focus on citizen impact and practical implications

### Prompt Template (`stage2_chapter`):
```
Δίνονται οι περιλήψεις των άρθρων ενός κεφαλαίου νομοσχεδίου:
{bullets}

Γράψε μια ενιαία περίληψη (200-300 λέξεις) που:
1. Συνοψίζει το περιεχόμενο του κεφαλαίου
2. Εστιάζει στις πρακτικές επιπτώσεις για τους πολίτες
3. Χρησιμοποιεί απλή γλώσσα
```

### Output
- CSV file: `cons{N}_stage2.csv`
- Columns: consultation_id, part, chapter, summary_text, raw_prompt, raw_output, retries

## Stage 3: Part-Level Synthesis

### Purpose
Create narrative summaries for each part (ΜΕΡΟΣ) of the legislation.

### Input
- Chapter summaries from Stage 2 CSV
- Introductory articles (Σκοπός/Αντικείμενο) if present

### Processing Logic

The stage uses a sophisticated two-phase narrative approach:

1. **Phase 1: Narrative Planning**
   - Analyzes chapter summaries to identify 2-6 thematic "beats"
   - Creates structured narrative plan with key points
   - Output: JSON with beats array

2. **Phase 2: Paragraph Generation**
   - Generates one paragraph per beat
   - Each paragraph flows naturally into the next
   - Maintains factual accuracy while improving readability

3. **Fallback Mechanism**:
   - If narrative approach fails, reverts to single-stage summarization
   - Uses simpler prompt for direct synthesis

### Prompts Used

**Narrative Planning** (`stage3_narrative_plan`):
```
Αναλύστε τις περιλήψεις κεφαλαίων και δημιουργήστε σχέδιο αφήγησης με 2-6 θεματικές ενότητες.
Κάθε ενότητα πρέπει να έχει:
- beat_title: Σύντομος τίτλος
- key_points: 2-4 βασικά σημεία
```

**Paragraph Synthesis** (`stage3_paragraph_beat`):
```
Γράψτε μια παράγραφο για την ενότητα "{beat_title}" με βάση:
{key_points}
Η παράγραφος πρέπει να είναι 50-80 λέξεις και να ρέει φυσικά.
```

### Output
- CSV file: `cons{N}_stage3.csv`
- Columns: consultation_id, part, summary_text, citizen_summary_text, narrative_plan_json
- Target length: 300-400 words per part

## Polish Stage: Citizen-Friendly Refinement

### Purpose
Transform technical summaries into accessible language for general citizens.

### Input
- Raw part summaries from Stage 3

### Processing Logic

1. **Grammar and Style Correction**:
   - Fixes spelling and grammatical errors
   - Improves sentence structure and flow

2. **Simplification**:
   - Replaces legal jargon with plain language
   - Breaks down complex sentences
   - Adds explanatory context where needed

3. **Redundancy Removal**:
   - Eliminates repetitive content
   - Maintains all factual information

### Prompt (`CITIZEN_POLISH_PROMPT`):
```
Βελτιώστε το κείμενο για πολίτες:
1. Διορθώστε γραμματικά/ορθογραφικά λάθη
2. Απλοποιήστε πολύπλοκους όρους
3. Αφαιρέστε επαναλήψεις
4. Διατηρήστε όλα τα γεγονότα

Επιστρέψτε JSON: {"summary_text": "..."}
```

### Output
- Updates Stage 3 CSV with `citizen_summary_text` column
- Separate trace log: `cons{N}_polish_trace.log`

## Final Assembly

### Purpose
Combine all part summaries into a single consultation summary.

### Processing Steps

1. **Part Ordering**:
   - Parts sorted by Greek numeral value
   - Maintains legislative structure

2. **Law Modifications Summary**:
   - Extracts all law references from Stage 1
   - Groups by part
   - Generates sentence: "Τροποποιούνται οι νόμοι..."

3. **Content Assembly**:
   - Header: `ΜΕΡΟΣ {name}:`
   - Optional: Law modifications section
   - Summary text (raw or polished based on configuration)

### Output
- Text file: `cons{N}_final_summary.txt`
- Format:
  ```
  ΜΕΡΟΣ Α:
  
  Αλλαγές:
  Τροποποιούνται οι νόμοι ν. 4174/2013 και ν. 4308/2014.
  
  Περίληψη:
  [Part summary text...]
  
  ΜΕΡΟΣ Β:
  [...]
  ```

## Key Technical Features

### 1. JSON Generation with Schema Enforcement
- Uses `lm-format-enforcer` library
- Guarantees valid JSON output
- Prevents common LLM formatting errors

### 2. Retry Logic
- Temperature escalation (0.01 → 0.2)
- Maximum 2 retries per generation
- Graceful degradation on persistent failures

### 3. Token Management
- Dynamic token budgets based on input length
- Compression ratio targets
- Context window awareness

### 4. Reasoning Traces
- Complete prompt/output logging
- Enabled via `ENABLE_REASONING_TRACE` config
- Outputs to `traces/` directory

### 5. Greek Language Handling
- Greek numeral parsing (Α, Β, Γ, etc.)
- Accent normalization
- Proper sorting and ordering

## Error Handling

1. **Missing Data**:
   - Skips empty chapters/parts
   - Logs warnings for missing content

2. **LLM Failures**:
   - Falls back to simpler prompts
   - Preserves original text if summarization fails

3. **Validation Errors**:
   - Captures last valid output
   - Reports retry count in output

## Performance Considerations

- **GPU Memory**: ~40GB for full model loading
- **Inference Speed**: ~30-60 seconds per part
- **Batch Processing**: Supports multiple consultations
- **Caching**: No built-in caching (stateless processing)

## Configuration Points

All settings in `modular_summarization/config.py`:
- Model ID and precision
- Token limits per stage
- Temperature settings
- Compression ratios
- Database paths
- Trace settings