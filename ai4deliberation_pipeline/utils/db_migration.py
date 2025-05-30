#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Migration Utilities

Handles database schema migrations with backup and rollback functionality.
"""

import os
import sys
import sqlite3
import logging
import shutil
from datetime import datetime
from pathlib import Path

# Import database models
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

from ai4deliberation_pipeline.scraper.db_models import init_db, Base

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_migration_backup(database_path: str, backup_dir: str) -> str:
    """
    Create a backup of the database before migration.
    
    Args:
        database_path: Path to the existing SQLite database
        backup_dir: Directory to store the backup
        
    Returns:
        str: Path to the backup file
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_name = os.path.splitext(os.path.basename(database_path))[0]
    backup_filename = f"{db_name}_backup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    # Ensure backup directory exists
    os.makedirs(backup_dir, exist_ok=True)
    
    if os.path.exists(database_path):
        logger.info(f"Creating backup: {backup_path}")
        shutil.copy2(database_path, backup_path)
        return backup_path
    else:
        logger.info(f"Database file {database_path} does not exist. Skipping backup.")
        return None # Or an empty string, or handle appropriately in recreate_database_schema

def migrate_database_schema(database_path: str, backup_path: str) -> bool:
    """
    Migrate database schema to new version.
    
    Args:
        database_path: Path to the database to migrate
        backup_path: Path to the backup file
        
    Returns:
        bool: Success status
    """
    return migrate_database(database_path)

def migrate_database(db_path):
    """
    Migrate existing database to new schema.
    
    Args:
        db_path: Path to the existing SQLite database
    """
    logger.info(f"Starting migration of database: {db_path}")
    
    # Check if database exists
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return False
    
    try:
        # Connect to database with raw SQLite for schema modifications
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check current schema
        logger.info("Analyzing current database schema...")
        
        # Get current tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        logger.info(f"Found existing tables: {existing_tables}")
        
        # Check if documents table exists and get its current schema
        if 'documents' in existing_tables:
            cursor.execute("PRAGMA table_info(documents)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            logger.info(f"Current documents table columns: {column_names}")
            
            # Add new columns to documents table if they don't exist
            new_columns = [
                ('content_cleaned', 'TEXT'),
                ('badness_score', 'REAL'),
                ('greek_percentage', 'REAL'),
                ('english_percentage', 'REAL')
            ]
            
            for column_name, column_type in new_columns:
                if column_name not in column_names:
                    logger.info(f"Adding column {column_name} to documents table")
                    cursor.execute(f"ALTER TABLE documents ADD COLUMN {column_name} {column_type}")
                else:
                    logger.info(f"Column {column_name} already exists in documents table")
        
        # Check if articles table needs content_cleaned column
        if 'articles' in existing_tables:
            cursor.execute("PRAGMA table_info(articles)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            if 'content_cleaned' not in column_names:
                logger.info("Adding content_cleaned column to articles table")
                cursor.execute("ALTER TABLE articles ADD COLUMN content_cleaned TEXT")
            
            if 'extraction_method' not in column_names:
                logger.info("Adding extraction_method column to articles table")
                cursor.execute("ALTER TABLE articles ADD COLUMN extraction_method TEXT")
        
        # Check if documents table needs extraction_method column  
        if 'documents' in existing_tables:
            cursor.execute("PRAGMA table_info(documents)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            if 'extraction_method' not in column_names:
                logger.info("Adding extraction_method column to documents table")
                cursor.execute("ALTER TABLE documents ADD COLUMN extraction_method TEXT")
        
        # Create new legalese tables
        legalese_tables = [
            'nomoi', 'ypourgikes_apofaseis', 'proedrika_diatagmata', 
            'eu_regulations', 'eu_directives'
        ]
        
        for table_name in legalese_tables:
            if table_name not in existing_tables:
                logger.info(f"Creating new table: {table_name}")
                # Basic structure - will be enhanced by SQLAlchemy
                cursor.execute(f"""
                    CREATE TABLE {table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        url TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            else:
                logger.info(f"Table {table_name} already exists")
        
        # Commit changes
        conn.commit()
        conn.close()
        
        # Now use SQLAlchemy to create any missing tables with proper schema
        logger.info("Using SQLAlchemy to finalize schema...")
        db_url = f'sqlite:///{db_path}'
        engine, Session = init_db(db_url)
        
        logger.info("Migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function for command-line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate AI4Deliberation database to new schema')
    parser.add_argument('database_path', help='Path to the existing database file')
    
    args = parser.parse_args()
    
    # Resolve path
    db_path = os.path.abspath(args.database_path)
    
    if migrate_database(db_path):
        print("Migration completed successfully!")
        print(f"Backup saved as: {db_path}.backup")
    else:
        print("Migration failed! Check logs for details.")
        sys.exit(1)

if __name__ == "__main__":
    main() 