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