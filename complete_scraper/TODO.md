# AI4Deliberation Project TODO List

## Scraper Improvements

### Enhanced Incremental Scraping Logic ✅

The implementation of `scrape_all_consultations.py` has been improved to make better use of incremental scraping. Now, we have the following capabilities:

1. Skip consultations that already exist in the database and are marked as finished (default behavior)
2. Selectively update consultations that are unfinished to capture new comments and documents
3. Re-scrape everything with `--force-scrape` when needed (for complete refreshes)

The implemented incremental scraping approach includes:

1. **New Consultation Detection**:
   - Find and fully scrape consultations that do not exist in the database

2. **Update In-Progress Consultations** ✅:
   - For consultations that already exist but have `is_finished = False`:
     - Re-scrape them to get any new comments ✅
     - Update minister messages (especially end_minister_message when consultations conclude) ✅
     - Update any new documents that may have been added ✅
     - Update the consultation status if it has completed ✅

3. **Optimization**:
   - Added comprehensive change tracking and reporting ✅
   - The scraper generates a detailed report of all changes made to unfinished consultations ✅

### Implementation Tasks

- [ ] Modify the consultation matching logic to check by title as well as URL/post_id
- [x] Add logic to detect and update in-progress consultations
- [x] Implement selective updating of consultation components
- [x] Add better progress tracking and reporting
- [ ] Update documentation to reflect new functionality

### Future Enhancements

- [ ] Add timestamp tracking to only fetch comments newer than the last scrape
- [ ] Add flags to control which specific aspects to update (comments, documents, status)
- [ ] Consider adding a `--update-unfinished-only` flag to specifically target in-progress consultations

## PDF Processing Pipeline

Now that we've added the `content` and `extraction_quality` fields to the Document model, we need to implement a PDF processing pipeline that will:

1. Download PDF documents from the URLs stored in the database
2. Extract text content from the PDFs
3. Assess the quality of the extraction
4. Update the database with the extracted content and quality metrics

This should be implemented as a separate script/module to keep concerns separated.
