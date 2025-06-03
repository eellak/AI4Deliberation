# AI4Deliberation Pipeline Workflow: TODO & Sanity Checklist

This document outlines the desired workflow for the AI4Deliberation pipeline, highlights observed discrepancies in the current implementation, and suggests action items for alignment.

## I. Desired Workflow Criteria

**A. Core Discovery & Initial Scrape (for ALL consultations found on the site):**

- [ ] **1. Comprehensive Discovery:**
    - Iterate through `https://www.opengov.gr/home/category/consultations` (and all its pages) to detect *all* consultation links.
    - Extract a unique identifier (e.g., `post_id` derived from the URL or metadata) for each.
    - *Sanity Check:* If a known new consultation (e.g., Ministry of Health `https://www.opengov.gr/yyka/?p=5399` which appears on the main listing) is missed, this indicates a bug in discovery/pagination logic.

- [ ] **2. New Consultation Identification & Initial DB Entry:**
    - Compare the full discovered list against our database (using the unique ID).
    - For consultations *not yet* in our database, create a basic entry for them, flagging them as "new" and needing full processing.

- [ ] **3. Initial Scrape - Essential Data Points (for NEW consultations):**
    - For each *newly identified* consultation (not in DB before this run), scrape:
        - Metadata: Start/end dates, Ministry, total comment count, title, `is_finished` status.
        - Article Content & Titles.
        - Document URLs (URLs only).
        - Comment Text & associated metadata.
    - Store this information in respective DB tables.

- [ ] **4. Initial Extraction (NEW consultations - NO Cleaning Yet for Articles/Comments):**
    - Process scraped raw HTML content for new consultations.
    - Articles & Comments: Extract text using `markdownify` **only**.
    - **Crucially: NO Rust cleaning for article/comment text at this stage.**
    - Update article and comment records with this `markdownify`-ed text.

- [ ] **5. Document Processing Pipeline (NEW consultations - Docling & Rust Cleaning):**
    - Process identified document URLs for new consultations.
    - Download actual document files.
    - Process PDFs/other docs using `docling` to get markdown.
    - Take the `docling`-extracted markdown and clean it using the **Rust cleaner**.
    - Store `docling` output, final Rust-cleaned output, badness scores, etc., for these documents.

**B. Targeted Re-Scraping & Updates (for EFFICIENCY and currency):**

- [ ] **6. Re-scraping "Unfinished" Consultations:**
    - **Identification:** At the beginning of a pipeline run, identify all consultations in our DB marked as `is_finished == False`.
    - **Targeted Scrape (for these unfinished ones):** Re-scrape *only*:
        - Metadata: To check for changes in end date, `is_finished` status, ministry, comment counts.
        - Comments: To fetch *only new* comments submitted since the last scrape.
    - **Extraction & Update (for these unfinished ones):**
        - Update metadata in the DB.
        - For *newly fetched* comments, `markdownify` their text and store it. (Existing comments for this consultation should *not* be re-processed).
    - **Efficiency:** Avoid re-scraping/re-processing articles or documents for these "unfinished" consultations unless fundamental metadata (e.g., a new version of an attached document) indicates a change.

- [ ] **7. Processing Genuinely "New" Consultations:**
    - These are consultations identified in step 2 as not being in the DB at all *before* the current run's discovery phase.
    - These go through the *full* initial scrape and processing pipeline as defined in steps 3, 4, and 5.

**C. Overall Sanity Checks:**

- [ ] **No Redundant Cleaning:** Article and comment text should only be `markdownify`-ed once when first ingested (or if a comment is newly found for an unfinished consultation). They should **not** be routinely passed to the Rust cleaner. Rust cleaning is *only* for the output of `docling` for official documents.
- [ ] **Clear Distinction:** The pipeline should clearly distinguish between:
    - Updating ongoing consultations (metadata, new comments).
    - Processing entirely new consultations (full scrape, `markdownify` for articles/comments, `docling`+Rust for documents).
- [ ] **Efficiency:** Minimize re-scraping and re-processing of data that hasn't changed, especially for finished consultations.

---

## II. Observed Discrepancies vs. Current Pipeline

1.  **Comprehensive Discovery (Criterion A.1):**
    *   **Discrepancy:** The pipeline (specifically `scraper.list_consultations.py` or its usage by the orchestrator) failed to identify the recent Ministry of Health consultation (`https://www.opengov.gr/yyka/?p=5399`) even though web search results indicate it *is* present on the main `https://www.opengov.gr/home/category/consultations` listing.
    *   **Impact:** Potentially missing new consultations.

2.  **Initial Scrape & New Consultation Identification (Criteria A.2, A.3 vs. B.7):**
    *   **Discrepancy:** The current orchestrator identifies "new" consultations as those whose *URL* isn't in the database from the start of the run. However, if `scrape_and_store` then finds an *existing `post_id`* for such a URL, it still proceeds to re-scrape and re-process many components (including articles) as if it were entirely new, rather than treating it as an already existing (possibly finished) consultation that just happened to be re-listed.
    *   **Impact:** Inefficient re-processing of already existing (and potentially closed) consultations. Lack of clear separation between "truly new" and "updating existing unfinished."

3.  **Initial Extraction - Rust Cleaning of Articles/Comments (Criterion A.4):**
    *   **Discrepancy:** `PipelineOrchestrator._process_articles` (and likely `_process_comments` if it handled content similarly) currently sends article/comment content to the Rust cleaner after `markdownify`.
    *   **Impact:** Incorrect workflow (Rust cleaner is for `docling` output only), potential for mangled article/comment text, inefficiency.

4.  **Re-scraping "Unfinished" Consultations (Criterion B.6):**
    *   **Discrepancy:** There is no dedicated, separate loop or logic at the beginning of an orchestrator run to specifically identify and perform a *targeted, minimal update* (metadata and new comments only) for consultations already in the DB marked as `is_finished == False`.
    *   **Impact:**
        *   Unfinished consultations might be missed entirely if they are no longer on the first few pages of the main listing that `get_all_consultations` scrapes.
        *   If they *are* found by `get_all_consultations`, they are treated like any other "newly seen URL" and might undergo more extensive re-scraping/re-processing than necessary.

5.  **Processing of "Genuinely New" vs. "Existing but Re-listed" (Criteria A.3-A.5 & B.7):**
    *   **Discrepancy:** The pipeline doesn't clearly distinguish between a URL for a consultation that has never been seen (no matching `post_id` in DB) versus a URL that, once scraped, resolves to a `post_id` that *is* already in the DB. Both are currently funneled through a similar "newly discovered by this run" pathway which involves re-processing articles and, incorrectly, Rust-cleaning them.
    *   **Impact:** Inefficiency, redundant processing, and incorrect cleaning of articles for existing consultations.

---

## III. Suggested Fixes / Action Items

*   **A1: Fix Discovery Logic:**
    *   **Action:** Investigate `scraper.list_consultations.py` and its interaction with `pipeline_orchestrator.py`. Ensure it correctly paginates and parses *all* consultations from `https://www.opengov.gr/home/category/consultations`. Verify it can find the Ministry of Health consultation (`https://www.opengov.gr/yyka/?p=5399`) and other recent items from the main listing.

*   **A2: Correct Article/Comment Processing - Remove Rust Cleaning:**
    *   **Action:** Modify `PipelineOrchestrator._process_articles`. Ensure that after `markdownify` (likely via `ContentProcessor.process_html_content`), the content is stored directly and **not** passed to `self.rust_cleaner.clean_content_batch`.
    *   **Action:** Review/implement `PipelineOrchestrator._process_comments` to follow the same `markdownify`-only logic for comment text.

*   **A3: Implement Dedicated "Update Unfinished Consultations" Loop:**
    *   **Action:** In `pipeline_orchestrator.py`, before the main discovery loop, add a new section/method:
        1.  Query the database for all consultations where `is_finished == False`.
        2.  For each, call a *modified or new mode* of `scrape_and_store`. This mode should:
            *   Re-scrape live metadata to update status (e.g., `is_finished`, `end_date`, `total_comments_count`).
            *   Fetch *only new comments* (comments not already in the DB for this consultation_id).
            *   `Markdownify` and store these new comments.
            *   Avoid re-touching articles or existing comments unless explicitly needed (which is outside current scope).

*   **A4: Refine Main "New/Discovered Consultation" Processing Loop:**
    *   **Action:** The existing main loop in the orchestrator (that iterates over results from `get_all_consultations()`) should be modified.
    *   When `_scrape_consultation` is called:
        *   If `scrape_and_store` indicates this is a **truly new consultation** (i.e., the `post_id` was *not* found in the database):
            *   Proceed with the full workflow: scrape all (metadata, articles, docs, comments), `markdownify` articles/comments (per A2), and process documents via `docling` then Rust cleaner (as per A.5).
        *   If `scrape_and_store` indicates the `post_id` **already exists**:
            *   **If it was already handled by the "Update Unfinished" loop (A3), ideally skip major re-processing here.** (This might require `scrape_and_store` to return more context or the orchestrator to keep track).
            *   If it's finished and already exists, log this and do minimal (if any) further processing for this item in *this* loop. The goal is to avoid re-processing already-handled or finished items.
    *   **Goal:** This loop should primarily focus on items confirmed to be entirely new to the database or those needing specific, controlled updates not covered by the "unfinished" loop.

*   **A5: Enhance `scrape_and_store` Context & Control:**
    *   **Action:** Modify `scrape_and_store` to better support these differentiated workflows.
        *   It should clearly return whether a consultation (based on `post_id`) was "newly created in DB this call", "existed in DB and was updated (e.g. unfinished becoming finished)", or "existed in DB and was already finished/unchanged".
        *   Allow more granular control over what it scrapes/updates, e.g., a mode for "metadata and new comments only" for the "Update Unfinished" loop.

*   **A6: Review `ContentProcessor`:**
    *   **Action:** Ensure `ContentProcessor.process_html_content` (or wherever `markdownify` is called for articles/comments) does not invoke any cleaning beyond `markdownify`.
    *   Ensure `ContentProcessor.process_document_url` correctly sequences download -> `docling` -> Rust cleaning for official documents.

By addressing these points, the pipeline should become more robust, efficient, and aligned with the intended processing logic. 