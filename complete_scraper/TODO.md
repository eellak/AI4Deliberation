# AI4Deliberation Project TODO List

## Scraper Improvements

### Enhanced Incremental Scraping Logic

The current implementation of `scrape_all_consultations.py` should be improved to make better use of incremental scraping. Currently, we only have two options:

1. Skip consultations that already exist in the database (default behavior)
2. Re-scrape everything with `--force-scrape` (inefficient)

What we actually need to implement is a smarter incremental scraping approach:

1. **New Consultation Detection**:
   - Look for consultations that do not already exist in the database by title
   - This would allow us to find consultations even if the URL structure has changed

2. **Update In-Progress Consultations**:
   - For consultations that already exist but have `is_finished = False`:
     - Re-scrape them to get any new comments
     - Update minister messages (especially end_minister_message when consultations conclude)
     - Update any new documents that may have been added
     - Update the consultation status if it has completed

3. **Optimization**:
   - Add flags to control which aspects to update (comments, documents, status)
   - Add timestamp tracking to only fetch comments newer than the last scrape
   - Consider adding a `--update-unfinished` flag to specifically target in-progress consultations

### Implementation Tasks

- [ ] Modify the consultation matching logic to check by title as well as URL/post_id
- [ ] Add logic to detect and update in-progress consultations
- [ ] Implement selective updating of consultation components
- [ ] Add better progress tracking and reporting
- [ ] Update documentation to reflect new functionality

## PDF Processing Pipeline

Now that we've added the `content` and `extraction_quality` fields to the Document model, we need to implement a PDF processing pipeline that will:

1. Download PDF documents from the URLs stored in the database
2. Extract text content from the PDFs
3. Assess the quality of the extraction
4. Update the database with the extracted content and quality metrics

This should be implemented as a separate script/module to keep concerns separated.
