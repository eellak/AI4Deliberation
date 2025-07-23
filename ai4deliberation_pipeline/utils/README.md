# Utils

Shared utilities for the AI4Deliberation pipeline.

## Overview
This module provides common utilities used across different components of the pipeline, including database management, logging, data flow control, and migration tools.

## Components

### Core Utilities
- `database.py` - Database connection management and statistics
- `logging_utils.py` - Centralized logging configuration and setup
- `data_flow.py` - Content processing flow management
- `anonymizer.py` - Data anonymization for privacy compliance

### Migration Tools
- `db_migration.py` - Database schema migration utilities
- `verify_migration.py` - Migration verification and validation

## Features

### Database Management
- Connection pooling and management
- Database statistics and monitoring
- Transaction handling
- Query optimization helpers

### Logging System
- Centralized log configuration
- Multiple log handlers (file, console)
- Log rotation and archival
- Structured logging support

### Data Flow Control
- Content processing pipelines
- State management for processing
- Batch operation support
- Progress tracking

### Privacy Tools
- PII detection and removal
- Comment anonymization
- User data protection
- GDPR compliance helpers

## Usage

### Database Operations
```python
from utils.database import get_db_connection, get_db_stats

with get_db_connection() as conn:
    # Perform database operations
    stats = get_db_stats(conn)
```

### Logging Setup
```python
from utils.logging_utils import setup_logging

logger = setup_logging(config, "module_name")
logger.info("Processing started")
```

### Data Anonymization
```python
from utils.anonymizer import anonymize_comments

anonymized_data = anonymize_comments(comment_data)
```

### Migration Verification
```python
from utils.verify_migration import verify_migration_integrity

is_valid = verify_migration_integrity(old_db, new_db)
```

## Best Practices
- Use connection context managers
- Configure logging early in application
- Anonymize data before external sharing
- Verify migrations before deployment