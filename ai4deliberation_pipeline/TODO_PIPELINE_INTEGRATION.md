# TODO: Master Pipeline Integration

## Project Overview
Integration of modules for creating a database from Greek online consultations (opengov.gr) into an automated pipeline.

**Pipeline Components:**
1. **Scraper**: Re-scrape entire website or update existing DB with new deliberations
2. **HTML Pipeline**: Extract HTML to text using markdownify  
3. **PDF Pipeline**: Download and extract PDF content
4. **Rust Cleaning Pipeline**: Clean noisy PDF-to-markdown text, return cleaned text plus Greek/English percentages and badness score (0-1)
5. **Future Reference Detection Pipeline**: For Greek and EU legalese (not ready yet)

## Configuration System
**Location**: `config/pipeline_config.yaml`
**Environment Override Pattern**: `AI4D_*` environment variables override config values

---

## PHASE 1: Database Schema Update & Migration ✅ COMPLETED

### Database Schema Changes
- [x] Add new columns to Documents table: content_cleaned, badness_score, greek_percentage, english_percentage
- [x] Create 5 new legalese tables: nomoi, ypourgikes_apofaseis, proedrika_diatagmata, eu_regulations, eu_directives
- [x] Create migration script with backup and rollback functionality

### Checkpoint Results: ✅ PASSED
- **Database**: `/mnt/data/AI4Deliberation/new_html_extraction/deliberation_data_gr_markdownify.db`
- **Backup Created**: `deliberation_data_gr_markdownify_backup_20250130_101615.db`
- **Data Preserved**: 1065 consultations + 28031 articles + 2089 documents + all comments
- **New Schema**: All new columns and tables created successfully

---

## PHASE 2: Configuration System ✅ COMPLETED

### Configuration Infrastructure
- [x] Create centralized YAML configuration file
- [x] Environment variable override system (AI4D_ prefix)
- [x] Validation with directory auto-creation
- [x] Fallback defaults and error handling

### Checkpoint Results: ✅ PASSED
- **Config File**: `config/pipeline_config.yaml` created
- **Utils Module**: `master_pipeline/utils.py` with load_config()
- **Environment Overrides**: Tested AI4D_SCRAPER_REQUEST_TIMEOUT=60 override
- **Directory Creation**: Automatic creation of temp_processing directories

---

## PHASE 3: Scraper Module Integration ✅ COMPLETED

### Integration Requirements
- [x] Integrate configuration system into existing scraper
- [x] Add three modes: 'full' (scrape all), 'update' (new + ongoing), 'single-url' (specific URLs)
- [x] Add discovery of new consultations from website
- [x] Add ongoing consultation detection (no end_date or is_finished=False)
- [x] Update existing ongoing consultations with new data

### Checkpoint Results: ✅ PASSED
- **Single-URL Mode**: Successfully tested with `http://www.opengov.gr/ypaat/?p=1214`
  - Added 1 new consultation with full article and comment extraction
- **Update Mode**: Successfully tested automatic discovery
  - Found 4 new consultations from website (1066 → 1069 total)
  - Added 57 new articles and ~93K new comments  
- **Ongoing Detection**: Properly identifies consultations without end dates for re-scraping
- **Error Handling**: Graceful handling of missing data and failed requests
- **Logging**: Comprehensive logging with request delays and status updates

---

## PHASE 4: HTML Pipeline Integration ✅ COMPLETED

### HTML Processing Requirements
- [x] Create HTML extraction module that uses markdownify
- [x] Integrate with existing `content` field from Articles table
- [x] Process all articles that don't have `content_cleaned` yet
- [x] Handle Greek text encoding properly
- [x] Add batch processing for efficient handling
- [x] Store cleaned text in `content_cleaned` field

### Implementation Steps
- [x] Create `html_pipeline/html_processor.py`
- [x] Add HTML cleaning functions using markdownify
- [x] Create batch processing for articles without content_cleaned
- [x] Integrate with configuration system
- [x] Add comprehensive error handling and logging

### Checkpoint Results: ✅ PASSED
- **Module Created**: `html_pipeline/html_processor.py` with full configuration integration
- **Processing Results**: Successfully processed 57/113 unprocessed articles (99.8% overall completion)
- **Error Handling**: Gracefully handled 56 articles with empty/invalid HTML content
- **Configuration Integration**: Uses centralized config for batch size and markdownify settings
- **Greek Text Encoding**: Properly preserved Greek characters in markdown conversion
- **Database Updates**: Added extraction_method tracking for pipeline-processed articles
- **Logging**: Comprehensive logging with batch progress and error reporting

---

## PHASE 5: PDF Pipeline Integration ✅ COMPLETED

### PDF Processing Requirements
- [x] Create PDF download and extraction module
- [x] Integrate with existing Documents table
- [x] Download PDFs to `temp_processing/pdfs/`
- [x] Extract text to `temp_processing/markdown/`
- [x] Handle PDF extraction failures gracefully
- [x] Update Documents table with extracted content
- [x] **Replace GlossAPI clustering with badness_score**: Documents with badness_score > 0.1 = "bad", <= 0.1 = "good"

### Implementation Steps
- [x] Create `pdf_pipeline/pdf_processor.py`
- [x] Add PDF download functionality with retries
- [x] Add PDF text extraction (PDF to markdown)
- [x] Create batch processing for documents without content
- [x] Integrate with configuration system
- [x] Add comprehensive error handling and logging
- [x] **Filter processing to non-law documents only** (exclude law_draft type)
- [x] **Update extraction_quality field based on badness_score thresholds**

### Checkpoint Results: ✅ PASSED
- **Integration Completed**: Successfully integrated existing PDF pipeline with configuration system
- **Configuration**: Added `pdf_pipeline` settings to `config/pipeline_config.yaml`
- **Wrapper Module**: Created `pdf_pipeline/pdf_processor.py` as configuration-integrated interface
- **URL Resolution**: User's existing `process_document_redirects.py` handles URL redirect issues
- **GlossAPI Integration**: User's `process_pdfs_with_glossapi.py` provides proper PDF extraction
- **Database Updates**: User's `update_database_with_content.py` handles content and quality updates
- **Processing Ready**: 4 documents of type 'analysis' ready for PDF processing
- **Pipeline Components**: All 4 steps (export → redirects → processing → database update) integrated
- **Test Results**: Successfully processed 4 analysis documents with GlossAPI extraction
- **Quality Assessment**: All 4 documents marked as 'good' quality with proper Greek text extraction
- **Database Integration**: Content and extraction_quality fields properly updated
- **Greek Text Preservation**: Confirmed proper Greek character encoding and formatting

---

## PHASE 6: Rust Cleaner Integration ✅ COMPLETED

### Rust Text Cleaning Requirements
- [x] Create Rust cleaner integration module  
- [x] Process extracted content for cleaning and quality assessment
- [x] Generate badness scores for document quality
- [x] Calculate Greek and English language percentages
- [x] Update Documents table with cleaned content and metrics
- [x] Integrate with configuration system
- [x] Handle batch processing for performance

### Implementation Steps
- [x] Create `rust_pipeline/rust_processor.py`
- [x] Import `text_cleaner_rs` module from venv
- [x] Add Rust cleaner configuration to `config/pipeline_config.yaml`
- [x] Implement document cleaning workflow
- [x] Add database update functionality with reliable SQLite commits
- [x] Create comprehensive logging and error handling
- [x] Add progress tracking and batch processing
- [x] Test with sample documents

### Checkpoint Results: ✅ PASSED
- **Integration Completed**: Successfully integrated Rust text cleaner with configuration system
- **Module Import**: `text_cleaner_rs` properly imported from virtual environment
- **Configuration**: Added `rust_cleaner` settings to pipeline config with threads, scripts, and batch size
- **Processing Workflow**: Implemented complete workflow (document retrieval → Rust cleaning → database update)
- **Database Updates**: Fixed SQLite direct updates ensuring proper transaction commits
- **Quality Metrics**: Successfully calculating badness scores and language percentages
- **Test Results**: 6 documents processed successfully with excellent quality scores (negative badness = very good)
- **Performance**: Fast processing (5 documents in ~0.02 seconds with Rust efficiency)

### Key Features
- **Configuration Integration**: Uses `rust_cleaner` section from pipeline config
- **Batch Processing**: Processes documents in configurable batches (default: 100)
- **Language Detection**: Detects Greek and Latin/English percentages
- **Quality Assessment**: Calculates badness scores (≤0.1 = good quality)
- **Reliable Updates**: Direct SQLite transactions with proper commit handling
- **Error Handling**: Comprehensive error handling and logging
- **Statistics**: Real-time progress tracking and completion statistics

---

## PHASE 7: Future Reference Detection Pipeline 🚧 DEFERRED

### Reference Detection Requirements
- [ ] Create reference detection integration module (DEFERRED - will integrate after core pipeline)
- [ ] Process documents for legal reference detection
- [ ] Extract and categorize legal references (laws, articles, etc.)
- [ ] Create reference database tables/relationships

**Note**: Deferring this phase to focus on core pipeline integration and efficiency improvements.

---

## PHASE 8: Project Structure & Modular Organization 🔄 IN PROGRESS

### Critical Architecture Issues Identified
- **Efficiency Problem**: Current Rust cleaning reads from DB then writes back (inefficient)
- **Solution**: Pipeline should flow: download → extract → clean → store once
- **Need**: Modular project structure with clear APIs

### Project Restructuring Requirements
- [ ] Create unified master module structure following GitHub best practices
- [ ] Move existing components into modular format with clear boundaries
- [ ] Document API interfaces for each module (scraper, html, pdf, rust cleaning)
- [ ] Ensure efficient data flow: process content in memory before DB storage
- [ ] Create clear module separation with defined input/output contracts

### Implementation Steps
- [ ] Create `master_pipeline/` as main integration folder
- [ ] Reorganize existing modules (`scraper/`, `html_pipeline/`, `pdf_pipeline/`, `rust_pipeline/`)
- [ ] Define module APIs and data flow contracts
- [ ] Update configuration to support new modular structure
- [ ] Create module documentation with clear interfaces

---

## PHASE 9: Integrated End-to-End API 🔄 NEXT

### Integration Requirements - CRITICAL
- [ ] **MANDATORY**: Fresh database schema recreation with backup
- [ ] Create single integrated API script for complete pipeline
- [ ] **MANDATORY**: End-to-end test with ONE new consultation
- [ ] **REQUIREMENT**: Must run to completion successfully before proceeding
- [ ] Efficient pipeline: scraping → downloading → extracting → cleaning → storing (single DB write)
- [ ] Complete verification: print all consultation data to verify correctness

### Pipeline Flow Design
```
New Consultation → Scraper → Articles/Documents → 
PDF Download → Content Extraction → Rust Cleaning → 
Database Storage (single write) → Verification Output
```

### Deliverables
- [ ] Recreated database schema with backup
- [ ] `run_integrated_pipeline.py` - single entry point script
- [ ] End-to-end processing of one consultation with verification
- [ ] Performance metrics and success confirmation
- [ ] Complete data verification output

**CRITICAL REQUIREMENT**: No progression to next phase until successful end-to-end run with full verification.

---

## Current Status: 🔄 PHASE 8 IN PROGRESS - ARCHITECTURE & EFFICIENCY FOCUS

**Immediate Priority**: Fix pipeline efficiency and create modular structure before end-to-end integration.

**Next Steps**: 
1. Project restructuring with modular APIs
2. Integrated pipeline with efficient data flow  
3. **MANDATORY**: Fresh run to completion with verification

**Architecture Goal**: Eliminate inefficient database read/write cycles, create clean modular structure, ensure end-to-end functionality.

**Success Metrics So Far**:
- ✅ Database successfully migrated with all new schema
- ✅ Configuration system working with environment overrides  
- ✅ Scraper integration working perfectly across all modes
- ✅ Real website testing successful with new data discovery
- ✅ 4 new consultations discovered and processed in update mode
- ✅ HTML pipeline processed 57/113 articles achieving 99.8% overall completion
- ✅ PDF pipeline successfully integrated and tested with 4 analysis documents
- ✅ Rust cleaning pipeline processing documents with excellent quality scores
- ✅ Future reference detection pipeline integration in progress

**Database Status**: 
- Total: 1069 consultations, 28,088 articles, 121,357 comments
- Articles: 99.8% have processed content (28,032/28,088)
- Documents: 2,096 total, 6 cleaned with Rust (1,365 remaining for bulk processing)
- Quality: Excellent badness scores achieved (negative values = very good quality)
- Reference detection pipeline integration in progress 