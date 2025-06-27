# Topic-Modeling Sub-Project

This folder contains the three pipelines (`v1`, `v2`, `v3`) that build BERTopic models for Greek-language consultation comments plus the evaluator.

## Overview

Public-consultation platforms collect hundreds or thousands of free-text comments.  The goal of this sub-project is to turn that raw text into an **actionable thematic map**:

1. Clean the comments and drop boiler-plate.
2. Convert every comment into a dense semantic embedding.
3. Cluster the embeddings with BERTopic (UMAP → HDBSCAN).
4. Pick representative comments for each cluster.
5. Ask a local LLM (Gemma-3 4B) to propose a concise Greek title and a 1-2-sentence explanation.
6. (Optional) Ask a second LLM (local or Gemini API) to evaluate those titles.

### What each version does

| Pipeline | What is new compared to the previous one | High-level steps |
|----------|------------------------------------------|------------------|
| **v1**   | Baseline.  Classic BERTopic pipeline + Gemma titles. | 1️⃣ Clean ➜ 2️⃣ SBERT embeddings ➜ 3️⃣ BERTopic **(UMAP→HDBSCAN, CLI-tunable)** ➜ 4️⃣ Representative comments (quantile) ➜ 5️⃣ Gemma titles |
| **v2**   | Pluggable embeddings, disk cache, fp16 Gemma, spell-check, strict JSON prompt. | Same as v1 but you can pick `--embedding_backend {sbert,gte_large}`; clustering still UMAP→HDBSCAN with `--umap_*` / `--hdb_*` flags; outputs land in `outputs/v2/` |
| **v3**   | Adds key-phrase extraction, hallucination guard, cluster hierarchy visual. | 1️⃣ Clean ➜ 2️⃣ Gemma key-phrases ➜ 3️⃣ Similarity filter ➜ 4️⃣ BERTopic **(UMAP→HDBSCAN)** ➜ 5️⃣ Titles that cite key-phrases |

All three share the same folder layout:

```
outputs/<version>/<consultation_id>/
   raw/           # cleaned comments CSV
   clustering/    # BERTopic artefacts
   reps/          # representative_comments_<v>.csv
   titles/        # topics_llm_<v>.jsonl
   evaluation/    # evaluation_results_<timestamp>.csv
```

> 💡  The scripts never send comment text outside the server; Gemma runs locally and Gemini is optional.

## 1. Quick setup

```bash
python3 -m venv ~/venv_topic
source ~/venv_topic/bin/activate

# install Python deps
pip install -r topic_modeling/requirements.txt

# add the Greek SpaCy model (≈ 548 MB once)
python -m spacy download el_core_news_lg

# (optional) enable GPU
pip install --upgrade torch==2.3.0+cu121 \
  --extra-index-url https://download.pytorch.org/whl/cu121
```

## 2. Hugging-Face model

Gemma-3 4B-Instruct weights must exist **locally**. Either

```bash
huggingface-cli login                  # paste your token once
python - <<'PY'
from transformers import Gemma3ForConditionalGeneration
Gemma3ForConditionalGeneration.from_pretrained("google/gemma-3-4b-it")
PY
```

or copy an existing snapshot to e.g. `/mnt/models/gemma-3-4b-it/`.  Then set

```bash
export GEMMA_PATH=/mnt/models/gemma-3-4b-it
```

## 3. Environment variables

Copy `env.example` to `.env` (or source it in your shell):

```bash
cp topic_modeling/env.example topic_modeling/.env
```

Key entries:

* `CUDA_VISIBLE_DEVICES` — pin the job to one GPU
* `PYTORCH_CUDA_ALLOC_CONF` — mitigates fragmenting allocations
* `GEMMA_PATH` — absolute path to the snapshot dir
* `GEMINI_API_KEY` — only needed when you run `evaluate_topics.py --gemini`
* `DB_URL` — SQLAlchemy URL for your comments DB

The scripts automatically load `.env` via `python-dotenv`.

## 4. Running

```bash
# v2 example
python topic_modeling/src/consultation_topic_modeling_v2.py \
       --consultation_id 320 \
       --embedding_backend sbert \
       --umap_min_dist 0.05 --hdb_min_cluster_size 6 \
       --hdb_min_samples 5 --umap_n 15 --random_state 42

# evaluator (local Gemma)
python topic_modeling/src/evaluate_topics.py \
       --consultation_id 320 --version v2 --local
```

Outputs land in `topic_modeling/outputs/<version>/<consultation_id>/…`. 

### 4.1  Enhanced evaluator – larger context & offline mode

The new script **`evaluate_topics_enhanced.py`** feeds Gemini (or local Gemma) *hundreds* of comments per topic instead of the fixed 10-comment subset and also supports a full **offline/manual-export** workflow.

Typical use-cases:

```bash
# (A) Full automatic evaluation with Gemini API
python topic_modeling/src/evaluate_topics_enhanced.py \
       --consultation_id 320 \
       --version v2 \
       --gemini \
       --api_key $GEMINI_API_KEY   # or set GEMINI_API_KEY in .env

# (B) Run everything locally with Gemma (no API key)
python topic_modeling/src/evaluate_topics_enhanced.py \
       --consultation_id 320 --version v2 --local

# (C) **Offline** – just dump the prompts for manual copy-paste
python topic_modeling/src/evaluate_topics_enhanced.py \
       --consultation_id 320 --version v2 --export_manual
```

In offline mode the script creates:

```
outputs/<ver>/<cid>/evaluation/manual_prompts/
   topic_0/
      prompt.txt         # ready-to-paste block for Gemini Chat/AI-Studio
      comments.txt       # the comments fed to Gemini (one per line)
      metadata.json      # helper counts, token estimate, etc.
   …
   all_prompts_combined.txt   # optional one-file dump
   README_how_to_use.txt      # quick instructions
```

After you paste a `prompt.txt` into Gemini and get the reply, record the score/feedback manually (or parse later) – the script has already created a placeholder CSV under `evaluation_enhanced_<timestamp>.csv`.

> **Dependencies added**: `sentence-transformers>=2.6`, `scikit-learn>=1.4`. These were appended to `requirements.txt`.

### 4.2  Unified single-prompt evaluator

`evaluate_topics_unified.py` packs **all** topics of one consultation into a *single* Gemini/Gemma prompt.

Pipeline in brief
1. Reads `clustering/topics.csv` to obtain every comment and its BERTopic `Probability`.
2. Loads titles & explanations from `titles/topics_llm_<ver>.jsonl` (or `.csv`).
3. For each topic it ranks **all** comments by probability.
4. Fills the LLM context window *round-robin* across topics so ότι every topic contributes comments and the highest-probability ones enter earliest.
5. Asks the LLM to return JSON with `{topic, score, feedback}`.

Run examples
```bash
# Evaluate with Gemini (one API call)
python topic_modeling/src/evaluate_topics_unified.py \
       --consultation_id 320 --version v2 \
       --gemini --api_key $GEMINI_API_KEY

# Local Gemma (no key, slower, offline)
python topic_modeling/src/evaluate_topics_unified.py \
       --consultation_id 320 --version v2 --local

# Manual copy-paste prompt
python topic_modeling/src/evaluate_topics_unified.py \
       --consultation_id 320 --version v2 --export_manual
```
Outputs:
```
outputs/<ver>/<cid>/evaluation/
   unified_prompt/prompt.txt   # if --export_manual
   evaluation_unified_<ts>.csv # parsed scores when LLM is called
```

The old `evaluate_topics_enhanced.py` (per-topic prompts) is still available for fine-grained or incremental evaluations.

--- 