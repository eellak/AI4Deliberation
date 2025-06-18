# Modular Summarization Refactor – TODO & Plan

## Goals
1. **Neat workflow script (<100 LOC)** that orchestrates the pipeline by importing well-scoped modules.
2. **Compression budgeting helper**: a reusable `summarization_budget()` that converts original length → `{target_words}/{target_sentences}/{token_limit}` and feeds prompts & retry logic (10 % words, /20 sentences, 2.5 tokens × 1.1 overshoot).
3. **Remove Stage 2.4–2.6** heavy re-join logic; we will adopt a new adaptive chunking/compression strategy.
4. **Separate modules**:
   - `config.py` – global constants (token limits, compression ratio, etc.).
   - `prompts.py` – prompt templates + small retry helper.
   - `advanced_parser.py` – streamlined article/section parsing utilities.
5. **Integrate `section_parser` assets** into a future `hierarchy_parser` module supporting the Greek legal hierarchy:
   - **Μέρος (Part) → Κατηγορία (Category) → Άρθρο (Article)**.
   - Each level will generate summaries, rolling up (Article → Category → Part → Whole).
6. **Consistent compression**: maintain ≈30 % ratio; no summarization if original text <80 words.

---

## Task Breakdown

### 1 – Extract & clean modules (DONE)
- [x] `config.py` with defaults.
- [x] `prompts.py` minimal Greek templates + retry helper.
- [x] `advanced_parser.py` simple header-based splitter.
- [x] `__init__.py` placeholder.
- [x] This `todo_plan.md`.

### 2 – Write the lightweight orchestrator (IN PROGRESS)
- [ ] Refactor to keep main body <100 LOC by extracting helper functions.
- [x] Created initial `workflow.py` (currently ~140 LOC; refactor later for brevity). Core logic delegates parsing and summarisation to helper modules.
  1. Load articles from DB (via `db_io.py`).
  2. Use `advanced_parser.get_article_chunks()` for each DB entry **(full gap-filling & quote-aware detection must be preserved – see Task 8)**.
  3. For each Article chunk (>80 words) generate a **Stage 1** summary using `summarization_budget()` to set `{target_*}` variables; if ≤80 words, reuse original text.
  4. Group Stage 1 summaries **per Κατηγορία** and run **Stage 2** summarizer with a prompt that explains the hierarchy and uses **dynamic budgets** from aggregated length.
  5. Aggregate Category summaries **per Μέρος** and run **Stage 3** summarizer with budgets.
  6. (Future) Optionally combine Part summaries into an overall bill summary.
  7. Return structured result dict / write JSON.
  8. Expose `run_workflow()` that receives `consultation_id` and optional `article_id`.

### 3 – Build `hierarchy_parser` (COMPLETED)
- [x] `hierarchy_parser.py` created wrapping `section_parser` and exposing Part/Category/Article dataclasses.
- Cooperates with `advanced_parser` for gap-filled articles.

### 7 – Hierarchical Data Model & Storage (NEW)
- [ ] Extend `hierarchy_parser.py` dataclasses:
  * `ArticleNode`: add `stage1_summary: str | None`
  * `ChapterNode`: add `stage2_summary: str | None`
  * `PartNode`: add `stage3_summary: str | None`
- [ ] Provide `to_dict()` / `from_dict()` helpers for JSON-serialisation preserving the tree & summaries.
- [ ] Persist final tree as `<consultation_id>_summaries.json`.
- `prompts.py` must include **all** templates:
  * Stage 1 (article), Stage 2 (category), Stage 3 (part), continuation, shortening, etc.
  * Each Stage prompt must interpolate dynamic values (e.g., Category name, token budget).
- Provide factory `get_prompt(stage_id, **kwargs)` for formatted insertion.

### 8 – Stage 2 summarisation – Chapter level (ΚΕΦΑΛΑΙΟ)
- [ ] In `workflow.py` iterate over `ChapterNode`s:
  1. Collect child `ArticleNode.stage1_summary`.
  2. Compute dynamic budget via `summarization_budget()`.
  3. Format `stage2_cohesive` prompt.
  4. Store result in `chapter.stage2_summary`.
- Extend `advanced_parser.py` with:
  - Quote-aware header detection.
  - Title-range parsing (`parse_db_article_title_range`).
  - `find_and_prioritize_mentions_for_gaps()` from legacy code.
  - Same prioritisation heuristics (start-of-line / quoted / inline etc.).
  - **Hierarchy gap fix**: For any Μέρος that has *null* Κεφάλαια in its DB titles, *before* article parsing scan the article **contents** for `ΚΕΦΑΛΑΙΟ` headers (e.g. `### ΚΕΦΑΛΑΙΟ Β΄`).  Detect these and inject synthetic Chapter nodes into the hierarchy, then proceed with normal article header parsing.
  - Add regression tests with complex fixtures to guarantee identical chunk outputs.

### 9 – Stage 3 summarisation – Part level (ΜΕΡΟΣ)
- [ ] For each `PartNode` gather `chapter.stage2_summary`.
- [ ] Compute budget, format prompt `stage3_exposition`.
- [ ] Store in `part.stage3_summary`.
- [ ] Implement accent-insensitive exact-word detectors `is_skopos`, `is_antikeimeno` in `law_utils.py`.
- [ ] In `workflow.py` capture first two logical articles per Μέρος, classify, store in `context["intro_articles"]` and exclude from summarisation loops.
- [ ] Ensure these raw texts are returned in `workflow` output for later surface.
- [ ] Unit tests for detection accuracy and exclusion behaviour.

### 10 – Workflow refactor & API
- [ ] Keep main `workflow.run_workflow()` <100 LOC by delegating to helpers:
  * `summarize_chapter(chapter_node)`
  * `summarize_part(part_node)`
- [ ] Return nested dict with summaries at all levels.
- [ ] Generate article-level summaries (Stage 1), then aggregate to ΚΕΦΑΛΑΙΟ (Stage 2) and to Μέρος (Stage 3) using dynamic budgets.
- [ ] Return `chapter_summaries` and `part_summaries` in workflow output.

### 11 – Prompt library updates
- [ ] Ensure Stage 2 & 3 prompts accept dynamic placeholders (token budget, names).
- [ ] Add helper `format_prompt(stage_id, hierarchy_node, **budget)` in `prompts.py`.
- PyTest suite covering parser, hierarchy aggregation, compression maths, prompt integrity & orchestrator E2E dry-run.
- Github Actions (or similar) for lint & unit tests.

### 12 – Tests & CI
- PyTest suite covering parser, hierarchy aggregation, compression maths, prompt integrity & orchestrator E2E dry-run.
- Github Actions (or similar) for lint & unit tests.

### 13 – Documentation
- Auto-generated API docs via `mkdocs`.
- Detailed examples / notebooks.
- Auto-generated API docs via `mkdocs`.
- Detailed examples / notebooks.

---

## Notes
• Hierarchy parser finished ✓. Dynamic prompt metrics & dry-run hierarchy view are upcoming priorities.
• The current modules are **scaffolds**; full logic will be ported as per Tasks 5-8.
• Be meticulous: **feature parity with `orchestrate_summarization_v3.py` is mandatory** before decommissioning the monolith.
• Hierarchical summarization & adaptive compression will likely change token estimates → prompts must accept variable target lengths.
