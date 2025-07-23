# Migration Support

Database migration utilities for the AI4Deliberation pipeline.

## Overview
This module provides comprehensive tools for migrating data between database schemas, with support for data transformation, validation, and post-migration processing.

## Components

### Migration Scripts
- `complete_migration_workflow.py` - Orchestrates the complete migration process
- `data_transfer_migration.py` - Handles data transfer between old and new schemas
- `post_migration_processing.py` - Post-migration cleanup and optimization
- `comment_reextraction.py` - Re-extracts comments with improved parsing

### Documentation
- `MIGRATION_README.md` - Detailed migration instructions and procedures

## Migration Workflow

1. **Pre-Migration**
   - Backup existing database
   - Validate source data
   - Prepare target schema

2. **Data Transfer**
   - Map old schema to new schema
   - Transfer core data
   - Maintain referential integrity

3. **Post-Migration Processing**
   - Apply Rust-based text cleaning
   - Re-extract comments with improved algorithms
   - Update metadata and indices

4. **Verification**
   - Validate data completeness
   - Check data integrity
   - Generate migration report

## Key Features
- **Safe Migration**: Automatic backups before migration
- **Data Validation**: Ensures data integrity throughout
- **Incremental Processing**: Can resume interrupted migrations
- **Detailed Logging**: Complete audit trail of migration steps
- **Rollback Support**: Can revert to pre-migration state

## Usage
```bash
# Run complete migration
python complete_migration_workflow.py --source old.db --target new.db

# Run specific migration step
python data_transfer_migration.py --source old.db --target new.db
```

## Safety Measures
- Always creates backups before migration
- Validates data at each step
- Provides dry-run option
- Generates detailed reports