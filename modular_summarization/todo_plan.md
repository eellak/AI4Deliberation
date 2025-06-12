# Modular Summarization Refactor – TODO & Plan

## Goals
1. **Neat workflow script (<100 LOC)** that orchestrates the pipeline by importing well-scoped modules.
2. **Remove Stage 2.4–2.6** heavy re-join logic; we will adopt a new adaptive chunking/compression strategy.
3. **Separate modules**:
   - `config.py` – global constants (token limits, compression ratio, etc.).
   - `prompts.py` – prompt templates + small retry helper.
   - `advanced_parser.py` – streamlined article/section parsing utilities.
4. **Integrate `section_parser` assets** into a future `hierarchy_parser` module supporting the Greek legal hierarchy:
   - **Μέρος (Part) → Κατηγορία (Category) → Άρθρο (Article)**.
   - Each level will generate summaries, rolling up (Article → Category → Part → Whole).
5. **Consistent compression**: maintain ≈30 % ratio; no summarization if original text <80 words.

---

## Task Breakdown

### 1 – Extract & clean modules (DONE)
- [x] `config.py` with defaults.
- [x] `prompts.py` minimal Greek templates + retry helper.
- [x] `advanced_parser.py` simple header-based splitter.
- [x] `__init__.py` placeholder.
- [x] This `todo_plan.md`.

### 2 – Write the lightweight orchestrator (NEXT)
- Create `workflow.py` (target <100 LOC). **Important**: keep core logic slim by delegating heavy lifting to helper modules.
  1. Load articles from DB (via `db_io.py`).
  2. Use `advanced_parser.get_article_chunks()` for each DB entry **(full gap-filling & quote-aware detection must be preserved – see Task 8)**.
  3. For each Article chunk (>80 words) generate a **Stage 1** summary; if ≤80 words, reuse original text.
  4. Group Stage 1 summaries **per Κατηγορία** and run **Stage 2** summarizer with a prompt that explains: «Το νομοσχέδιο δομείται σε Μέρη → Κατηγορίες → Άρθρα· τα ακόλουθα είναι περιλήψεις άρθρων της Κατηγορίας {X}».
  5. Aggregate Category summaries **per Μέρος** and run **Stage 3** summarizer to produce a cohesive Part-level overview.
  6. (Future) Optionally combine Part summaries into an overall bill summary.
  7. Return structured result dict / write JSON.
  8. Expose `run_workflow()` that receives `consultation_id` and optional `article_id`.

### 3 – Build `hierarchy_parser` (COMPLETED)
- [x] `hierarchy_parser.py` created wrapping `section_parser` and exposing Part/Category/Article dataclasses.
- Cooperates with `advanced_parser` for gap-filled articles.

### 4 – Dynamic prompt length injection (NEXT)
- Extend `compression.py` (or new `metrics.py`) with `length_metrics(text)` returning `(tokens, words, sentences)`.
- Add placeholders `{input_tokens}`, `{input_words}`, `{target_sentences}` in prompt templates.
- Runner computes metrics per stage and `str.format` fills the prompt before generation.
- Update adaptive compression logic to compute `target_sentences` from `desired_tokens()`.

### 5 – Hierarchical dry-run presentation (NEXT)
- When `--dry-run` flag is set:
  - Parse DB articles → build `BillHierarchy`.
  - For each Part → Category → Article show:
    * title, word count, token estimate.
    * **planned prompt excerpt** (first 40 chars) indicating stage and target tokens.
  - Output in Markdown or CSV for human review.
- Ensure runner skips LLM calls but exercises full parsing/metric pipeline.

### 5b – Dry-run regression tests (NEXT)
- PyTest module `test_dry_run.py` that iterates over sample consultation IDs (fixture list).
- Calls `run_workflow(consultation_id, dry_run=True)` and:
  1. Asserts that **article sequences** per Part/Category are continuous (via `hierarchy_parser.verify_continuity`).
  2. Asserts no missing Part/Category numbers across the hierarchy.
  3. Saves generated `dry_run_markdown` into `tests/output/{cid}_hierarchy.txt` for human diff review.
  4. Verifies that each Article block includes word/token counts.
- Add CLI `scripts/generate_dry_runs.py` for regenerating all hierarchy files in bulk.

### 6 – Adaptive compression & token budgeting (FUTURE)
- New helper `compression.py`:
  - `desired_tokens(input_tokens, stage) -> int` with **dynamic ratio** (e.g., 25 % for large inputs, 40 % for small) so that a 3 000-word Category summary compresses more than a 1 000-word one.
  - Logic to **skip** summarization if `< MIN_WORDS_FOR_SUMMARY`.
  - Helper `should_split(input_tokens, stage)` comparing against model window.
- Update prompts to accept `{TARGET_TOKENS}` placeholder and formula-driven budget.

### 7 – Prompt library refactor (FUTURE)
- `prompts.py` must include **all** templates:
  * Stage 1 (article), Stage 2 (category), Stage 3 (part), continuation, shortening, etc.
  * Each Stage prompt must interpolate dynamic values (e.g., Category name, token budget).
- Provide factory `get_prompt(stage_id, **kwargs)` for formatted insertion.

### 8 – Port advanced gap-filling parser logic (FUTURE)
- Extend `advanced_parser.py` with:
  - Quote-aware header detection.
  - Title-range parsing (`parse_db_article_title_range`).
  - `find_and_prioritize_mentions_for_gaps()` from legacy code.
  - Same prioritisation heuristics (start-of-line / quoted / inline etc.).
  - **Hierarchy gap fix**: For any Μέρος that has *null* Κεφάλαια in its DB titles, *before* article parsing scan the article **contents** for `ΚΕΦΑΛΑΙΟ` headers (e.g. `### ΚΕΦΑΛΑΙΟ Β΄`).  Detect these and inject synthetic Chapter nodes into the hierarchy, then proceed with normal article header parsing.
  - Add regression tests with complex fixtures to guarantee identical chunk outputs.

### 9 – Tests & CI (FUTURE)
- PyTest suite covering parser, hierarchy aggregation, compression maths, prompt integrity & orchestrator E2E dry-run.
- Github Actions (or similar) for lint & unit tests.

### 10 – Documentation (FUTURE)
- Auto-generated API docs via `mkdocs`.
- Detailed examples / notebooks.

---

## Notes
• Hierarchy parser finished ✓. Dynamic prompt metrics & dry-run hierarchy view are upcoming priorities.
• The current modules are **scaffolds**; full logic will be ported as per Tasks 5-8.
• Be meticulous: **feature parity with `orchestrate_summarization_v3.py` is mandatory** before decommissioning the monolith.
• Hierarchical summarization & adaptive compression will likely change token estimates → prompts must accept variable target lengths.
