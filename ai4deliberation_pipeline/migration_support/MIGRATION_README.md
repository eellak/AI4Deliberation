# Database Migration Guide

This guide covers migrating your valuable processed data from the old database (`deliberation_data_gr_markdownify.db`) to the new pipeline schema with correct extraction methods and external document tables.

## Overview

### Migration Scope
- **Old Database**: `/mnt/data/AI4Deliberation/deliberation_data_gr_markdownify.db`
- **New Schema**: `scraper/db_models.py` with enhanced fields and external document tables
- **Data Volume**: 152,015+ records (36 ministries, 1,065 consultations, 28,031 articles, 2,089 documents, 120,775 comments)
- **Processing**: Days of compute work preserved through Rust cleaning and quality analysis

### Schema Differences

#### Core Tables Enhanced
- **Articles**: Added `content_cleaned`, `extraction_method` 
- **Documents**: Added `content_cleaned`, `extraction_method`, `badness_score`, `greek_percentage`, `english_percentage`
- **Comments**: Added `extraction_method`

#### New External Document Tables
The new schema includes 5 additional tables for legal references:
1. **nomoi** - Greek laws (νόμοι)
2. **ypourgikes_apofaseis** - Ministerial decisions (υπουργικές αποφάσεις)
3. **proedrika_diatagmata** - Presidential decrees (προεδρικά διατάγματα)
4. **eu_regulations** - EU regulations
5. **eu_directives** - EU directives

Each external table includes fields for content, quality metrics, and metadata.

#### Extraction Method Standards
- **Documents**: All use `docling` extraction method
- **Articles**: All use `markdownify` extraction method  
- **Comments**: All use `markdownify` extraction method
- **Note**: Comments in old DB may have been extracted with docling and might need re-extraction

## Migration Process

### Phase 1: Data Transfer Migration
```bash
python migration_support/data_transfer_migration.py
```

**What it does:**
- Creates automatic backup of old database
- Initializes new database with complete schema (including 5 external tables)
- Transfers all 152,015+ records with schema adaptations
- Sets correct extraction methods:
  - Documents → `docling`
  - Articles → `markdownify` 
  - Comments → `markdownify`
- Sets new fields to NULL initially (populated in Phase 2)
- Verifies transfer completeness with detailed reporting

### Phase 2: Post-Migration Processing
```bash
python migration_support/post_migration_processing.py
```

**What it does:**
- Runs Rust cleaning on 1,384+ documents with content
- Populates `badness_score`, `greek_percentage`, `english_percentage`
- Verifies extraction method consistency
- Identifies comments that may need re-extraction
- Generates comprehensive processing reports

### Phase 3: Scraper Verification
After migration, run the scraper to:
- Verify migration efficacy
- Fetch any new data from opengov.gr
- Test pipeline with migrated data

```bash
python scraper/main_scraper.py --update
```

## Complete Workflow

### One-Command Migration
```bash
python migration_support/complete_migration_workflow.py
```

This orchestrates all three phases automatically with comprehensive reporting.

### Workflow Options
```bash
# Dry run (preview without changes)
python migration_support/complete_migration_workflow.py --dry-run

# Skip processing (data transfer only)
python migration_support/complete_migration_workflow.py --skip-processing

# Skip scraper (migration + processing only)
python migration_support/complete_migration_workflow.py --skip-scraper
```

## Key Features

### Automatic Backup & Recovery
- Creates timestamped backups before any changes
- Graceful fallback if SQLAlchemy unavailable
- Error recovery and partial processing options

### Extraction Method Compliance
- **Documents**: Correctly marked as `docling` extracted
- **Articles**: Correctly marked as `markdownify` extracted  
- **Comments**: Correctly marked as `markdownify` extracted
- Automatic detection of comments that may need re-extraction

### Quality Metrics
- Rust cleaning provides badness scores (lower = better quality)
- Language analysis (Greek/English percentages)
- Content quality verification and reporting

### External Document Support
- 5 new empty tables ready for legal reference data
- Complete schema with content, quality, and metadata fields
- Structured for nomoi, ministerial decisions, decrees, EU regulations/directives

### Comprehensive Verification
- Record count validation across all tables
- Extraction method compliance checking
- Quality score analysis and reporting
- Processing completeness verification

## Usage Examples

### Basic Migration
```bash
# Complete migration with all phases
python migration_support/complete_migration_workflow.py

# Preview what would happen
python migration_support/complete_migration_workflow.py --dry-run
```

### Phase-by-Phase Migration
```bash
# Phase 1: Data transfer only
python migration_support/data_transfer_migration.py

# Phase 2: Process transferred data
python migration_support/post_migration_processing.py

# Phase 3: Verify with scraper
python scraper/main_scraper.py --update
```

### Partial Processing
```bash
# Process only specific number of documents
python migration_support/post_migration_processing.py --limit 100

# Get help on all options
python migration_support/post_migration_processing.py --help
```

## Expected Results

### Data Transfer (Phase 1)
- ✅ 36 ministries transferred
- ✅ 1,065 consultations transferred  
- ✅ 28,031 articles transferred (marked as `markdownify`)
- ✅ 2,089 documents transferred (marked as `docling`)
- ✅ 120,775 comments transferred (marked as `markdownify`)
- ✅ 5 external document tables created (empty)

### Processing (Phase 2)
- ✅ 1,384+ documents with content cleaned
- ✅ Quality scores populated (badness_score, greek_percentage, english_percentage)
- ✅ Processing reports generated
- ⚠️ Comments flagged if they may need re-extraction

### Verification (Phase 3)
- ✅ Scraper runs successfully on migrated data
- ✅ New data fetched from opengov.gr
- ✅ Pipeline functionality verified

## Migration Notes

### Extraction Method Decisions
Based on your requirements:
- **All documents**: Extracted with docling (PDF processing)
- **All articles + comments**: Extracted with markdownify (HTML processing)
- **Legacy comments**: May need re-extraction if originally from docling

### Quality Considerations
- Documents with `badness_score < 0.1` are high quality
- Documents with `greek_percentage > 80%` are primarily Greek
- Comments with PDF-like characteristics may need re-extraction

### External Document Tables
The 5 new tables are created empty and ready for:
- Legal reference scraping
- Cross-referencing with consultations
- Enhanced document linking capabilities

## Troubleshooting

### Common Issues

**ImportError for SQLAlchemy:**
- Migration automatically falls back to manual schema creation
- No action needed, migration continues normally

**Processing Errors:**
- Check Rust processor availability
- Use `--limit` flag to process documents in smaller batches
- Review `migration_workflow.log` for detailed error information

**Scraper Issues:**
- Verify scraper script location (`scraper/main_scraper.py`)
- Check network connectivity to opengov.gr
- Use `--skip-scraper` flag to complete migration without scraper verification

### Recovery Options

**Restore from Backup:**
```bash
# Backups are created automatically as:
# deliberation_data_gr_markdownify.db.backup.YYYYMMDD_HHMMSS
cp /path/to/backup.db deliberation_data_gr.db
```

**Partial Re-processing:**
```bash
# Re-run processing with limits
python migration_support/post_migration_processing.py --limit 50

# Skip migration, just process
python migration_support/complete_migration_workflow.py --skip-migration
```

## Verification Commands

### Check Migration Success
```bash
# Quick verification
sqlite3 deliberation_data_gr.db "SELECT COUNT(*) FROM documents;"

# Detailed verification  
python migration_support/complete_migration_workflow.py --dry-run
```

### Check Extraction Methods
```bash
sqlite3 deliberation_data_gr.db "
SELECT extraction_method, COUNT(*) 
FROM documents 
GROUP BY extraction_method;
"
```