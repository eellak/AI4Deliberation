#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Transfer Migration Script

Transfers data from the old database schema (deliberation_data_gr_markdownify.db) 
to the new pipeline schema, handling schema differences and preparing data for 
processing by Rust cleaner and other pipeline components.
"""

import os
import sys
import sqlite3
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Add the project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

# Try to import database models
try:
    from scraper.db_models import init_db, Base
except ImportError as e:
    print(f"Warning: Could not import db_models: {e}")
    print("Attempting to create schema manually...")
    init_db = None
    Base = None

# Set up logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_new_schema_manually(db_path: str):
    """Create the new database schema manually if SQLAlchemy is not available.
    This schema MUST match scraper.db_models.py exactly.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create ministries table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ministries (
            id INTEGER PRIMARY KEY,
            code VARCHAR(100) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            url VARCHAR(255) NOT NULL
        )
    """)
    
    # Create consultations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultations (
            id INTEGER PRIMARY KEY,
            post_id VARCHAR(50) NOT NULL,
            title VARCHAR(500) NOT NULL,
            start_minister_message TEXT,
            end_minister_message TEXT,
            start_date DATETIME,
            end_date DATETIME,
            is_finished BOOLEAN,
            url VARCHAR(255) NOT NULL UNIQUE,
            total_comments INTEGER DEFAULT 0,
            accepted_comments INTEGER,
            ministry_id INTEGER,
            FOREIGN KEY(ministry_id) REFERENCES ministries (id)
        )
    """)
    
    # Create articles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY,
            title VARCHAR(500) NOT NULL,
            url VARCHAR(255) NOT NULL UNIQUE,
            content TEXT,
            raw_html TEXT,
            content_cleaned TEXT, 
            extraction_method VARCHAR(100),
            badness_score REAL, 
            greek_percentage REAL, 
            english_percentage REAL, 
            consultation_id INTEGER NOT NULL, 
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
            FOREIGN KEY (consultation_id) REFERENCES consultations (id)
        )
    """)
    
    # Create documents table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            url VARCHAR(255) NOT NULL UNIQUE,
            file_path VARCHAR(512),          -- Path to the downloaded file
            status VARCHAR(50) DEFAULT 'pending', -- e.g., pending, downloaded, processed, error
            type VARCHAR(100),               -- law_draft, analysis, etc. (from original schema)
            content_type VARCHAR(100),       -- MIME type e.g. application/pdf
            
            processed_text TEXT,             -- Raw text extracted by Docling or other methods
            content TEXT,                    -- Legacy: may hold extracted text. Pipeline prefers processed_text.
            content_cleaned TEXT,            -- Cleaned content by Rust
            
            extraction_method VARCHAR(100),  -- Method for processed_text (e.g., 'docling')
            badness_score REAL,              -- Rust cleaner score for content_cleaned
            greek_percentage REAL,           -- Rust cleaner score
            english_percentage REAL,         -- Rust cleaner score
            
            -- extraction_quality VARCHAR(50), -- Legacy, replaced by status and badness_score
            consultation_id INTEGER,
            
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            -- content_cleaned_at DATETIME,    -- When Rust cleaning was last run
            FOREIGN KEY(consultation_id) REFERENCES consultations (id)
        )
    """)
    # Add indexes for documents table
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON documents (status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents (updated_at)")

    # Create comments table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY,
            comment_id VARCHAR(50),
            username VARCHAR(255) NOT NULL,
            date DATETIME,
            content TEXT NOT NULL,         -- Raw comment text (usually markdown from site)
            -- content_cleaned TEXT,      -- If comments were to be cleaned by Rust
            -- badness_score REAL,
            extraction_method VARCHAR(100),
            article_id INTEGER,
            -- updated_at DATETIME,       -- If comments were to be updated
            FOREIGN KEY(article_id) REFERENCES articles (id)
        )
    """)
    
    # Create the 5 new external document tables (Nomos, YpourgikiApofasi, etc.)
    external_tables = [
        ('nomoi', 'law_number VARCHAR(100)'),
        ('ypourgikes_apofaseis', 'decision_number VARCHAR(100), ministry VARCHAR(255)'),
        ('proedrika_diatagmata', 'decree_number VARCHAR(100)'),
        ('eu_regulations', 'regulation_number VARCHAR(100), eu_year INTEGER'),
        ('eu_directives', 'directive_number VARCHAR(100), eu_year INTEGER')
    ]
    
    for table_name, specific_columns in external_tables:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                url VARCHAR(255) NOT NULL UNIQUE,
                type VARCHAR(100),              -- Type classification
                content TEXT,                   -- Extracted content
                content_cleaned TEXT,           -- Cleaned content by Rust
                extraction_method VARCHAR(100),
                badness_score REAL,
                greek_percentage REAL,
                english_percentage REAL,
                publication_date DATETIME,
                source VARCHAR(100),            -- e.g., 'ΦΕΚ', 'EUR-Lex'
                {specific_columns},             -- Table-specific columns
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    conn.commit()
    conn.close()
    logger.info("Database schema created manually, matching current scraper.db_models.py definition.")

class DataTransferMigration:
    """Handles data transfer from old to new database schema."""
    
    def __init__(self, old_db_path: str, new_db_path: str):
        """
        Initialize the migration.
        
        Args:
            old_db_path: Path to the old database
            new_db_path: Path to the new database (will be created)
        """
        self.old_db_path = old_db_path
        self.new_db_path = new_db_path
        self.backup_dir = os.path.join(os.path.dirname(new_db_path), 'migration_backups')
        
        # Statistics tracking
        self.stats = {
            'ministries': {'transferred': 0, 'total': 0},
            'consultations': {'transferred': 0, 'total': 0},
            'articles': {'transferred': 0, 'total': 0, 'with_content': 0},
            'documents': {'transferred': 0, 'total': 0, 'with_content': 0},
            'comments': {'transferred': 0, 'total': 0}
        }
    
    @staticmethod
    def safe_float_convert(value) -> Optional[float]:
        """Safely convert a value to float, returning None for invalid values."""
        if value is None or value == '':
            return None
        
        # If it's already a number
        if isinstance(value, (int, float)):
            return float(value)
        
        # If it's a string, try to convert
        if isinstance(value, str):
            try:
                # Remove % sign if present
                cleaned_value = value.replace('%', '').strip()
                if cleaned_value == '' or cleaned_value.lower() in ['null', 'none']:
                    return None
                return float(cleaned_value)
            except (ValueError, TypeError):
                return None
        
        return None
    
    def create_backup(self) -> str:
        """Create backup of old database."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"old_db_backup_{timestamp}.db"
        backup_path = os.path.join(self.backup_dir, backup_filename)
        
        os.makedirs(self.backup_dir, exist_ok=True)
        
        if os.path.exists(self.old_db_path):
            logger.info(f"Creating backup: {backup_path}")
            shutil.copy2(self.old_db_path, backup_path)
            return backup_path
        else:
            raise FileNotFoundError(f"Old database not found: {self.old_db_path}")
    
    def initialize_new_database(self):
        """Initialize the new database with proper schema."""
        logger.info(f"Initializing new database: {self.new_db_path}")
        
        # Remove existing database if it exists to ensure a fresh start for this run
        if os.path.exists(self.new_db_path):
            # Instead of backup and move, just delete if we expect this script to fully create it.
            # Or, ensure the backup name is truly unique if keeping backups from this specific script.
            # For this workflow, since the new_db_path is already timestamped by the caller,
            # a simple deletion is fine.
            try:
                os.remove(self.new_db_path)
                logger.info(f"Removed existing database file at {self.new_db_path} to ensure fresh creation.")
            except OSError as e:
                logger.error(f"Error removing existing database {self.new_db_path}: {e}. Proceeding with caution.")

        # Create new database with proper schema
        if init_db is not None and Base is not None: # Check for Base as well for SQLAlchemy
            try:
                logger.info(f"Attempting to initialize schema using SQLAlchemy from scraper.db_models for: {self.new_db_path}")
                db_url = f'sqlite:///{self.new_db_path}'
                # init_db function from scraper.db_models should handle engine creation and Base.metadata.create_all(engine)
                engine, Session = init_db(db_url) 
                logger.info("New database schema created successfully with SQLAlchemy via scraper.db_models.init_db.")
                return engine, Session
            except Exception as e:
                logger.warning(f"SQLAlchemy initialization via scraper.db_models.init_db failed: {e}", exc_info=True)
                logger.info("Falling back to manual schema creation as defined in data_transfer_migration.py.")
        else:
            logger.info("SQLAlchemy (init_db or Base from scraper.db_models) not available. Proceeding with manual schema creation.")
        
        # Fallback to manual schema creation
        create_new_schema_manually(self.new_db_path)
        # For manual creation, we don't have an engine/Session to return in the same way.
        # The rest of the script uses direct sqlite3 connections for transfer.
        return None, None # Indicate manual creation, no SQLAlchemy engine/session from this path.
    
    def get_table_counts(self, db_path: str) -> Dict[str, int]:
        """Get record counts for all tables in a database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        counts = {}
        tables = ['ministries', 'consultations', 'articles', 'documents', 'comments']
        
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                counts[table] = 0  # Table doesn't exist
        
        conn.close()
        return counts
    
    def transfer_ministries(self, old_conn: sqlite3.Connection, new_conn: sqlite3.Connection):
        """Transfer ministries data (identical schema)."""
        logger.info("Transferring ministries...")
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        # Get all ministries from old database
        old_cursor.execute("SELECT id, code, name, url FROM ministries")
        ministries = old_cursor.fetchall()
        
        self.stats['ministries']['total'] = len(ministries)
        
        # Insert into new database
        for ministry in ministries:
            new_cursor.execute(
                "INSERT INTO ministries (id, code, name, url) VALUES (?, ?, ?, ?)",
                ministry
            )
            self.stats['ministries']['transferred'] += 1
        
        new_conn.commit()
        logger.info(f"Transferred {self.stats['ministries']['transferred']} ministries")
    
    def transfer_consultations(self, old_conn: sqlite3.Connection, new_conn: sqlite3.Connection):
        """Transfer consultations data (identical schema)."""
        logger.info("Transferring consultations...")
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        # Get all consultations from old database
        old_cursor.execute("""
            SELECT id, post_id, title, start_minister_message, end_minister_message,
                   start_date, end_date, is_finished, url, total_comments, 
                   accepted_comments, ministry_id
            FROM consultations
        """)
        consultations = old_cursor.fetchall()
        
        self.stats['consultations']['total'] = len(consultations)
        
        # Insert into new database
        for consultation in consultations:
            new_cursor.execute("""
                INSERT INTO consultations 
                (id, post_id, title, start_minister_message, end_minister_message,
                 start_date, end_date, is_finished, url, total_comments, 
                 accepted_comments, ministry_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, consultation)
            self.stats['consultations']['transferred'] += 1
        
        new_conn.commit()
        logger.info(f"Transferred {self.stats['consultations']['transferred']} consultations")
    
    def transfer_articles(self, old_conn: sqlite3.Connection, new_conn: sqlite3.Connection):
        """Transfer articles data with new schema fields."""
        logger.info("Transferring articles...")
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        # Get all articles from old database
        old_cursor.execute("""
            SELECT id, title, url, content, raw_html, consultation_id
            FROM articles
        """)
        articles = old_cursor.fetchall()
        
        self.stats['articles']['total'] = len(articles)
        
        # Insert into new database with new fields
        for article in articles:
            # Ensure we have the correct number of elements from the SELECT
            if len(article) == 6:
                art_id, title, url, content, raw_html, consultation_id = article
            else:
                # Fallback or error if columns don't match (e.g. if post_id was expected from old DB)
                # For now, assume the 6 columns as selected above
                logger.warning(f"Unexpected number of columns for article data: {article}. Skipping.")
                continue
            
            # Count articles with content
            if content and content.strip():
                self.stats['articles']['with_content'] += 1
            
            # All articles are extracted with markdownify
            extraction_method_value = 'markdownify'
            
            new_cursor.execute("""
                INSERT INTO articles 
                (id, title, url, content, raw_html, consultation_id, 
                 extraction_method,
                 content_cleaned, badness_score, greek_percentage, english_percentage, 
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (art_id, title, url, content, raw_html, consultation_id, extraction_method_value))
            
            self.stats['articles']['transferred'] += 1
        
        new_conn.commit()
        logger.info(f"Transferred {self.stats['articles']['transferred']} articles")
        logger.info(f"Articles with content: {self.stats['articles']['with_content']}")
        logger.info("All articles marked as extracted with 'markdownify'")
    
    def transfer_documents(self, old_conn: sqlite3.Connection, new_conn: sqlite3.Connection):
        """Transfer documents data with new schema fields."""
        logger.info("Transferring documents...")
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        # Get all documents from old database
        old_cursor.execute("""
            SELECT id, title, url, type, content, extraction_quality, consultation_id
            FROM documents
        """)
        documents = old_cursor.fetchall()
        
        self.stats['documents']['total'] = len(documents)
        
        # Insert into new database with new fields
        for document in documents:
            doc_id, title, url, doc_type, content, extraction_quality_old_db, consultation_id = document
            
            # Count documents with content
            if content and content.strip():
                self.stats['documents']['with_content'] += 1
            
            # All documents are extracted with docling
            extraction_method = 'docling'
            
            # Ensure status is set, default to 'pending' if not derived from extraction_quality_old_db
            current_status = 'pending' # Default status
            if extraction_quality_old_db:
                if extraction_quality_old_db.lower() == 'success':
                    current_status = 'processed' # Assuming 'success' in old DB means text was extracted
                elif extraction_quality_old_db.lower() in ['error', 'failure', 'failed']:
                    current_status = 'processing_failed'
                # Add other mappings if necessary, otherwise it remains 'pending'

            new_cursor.execute("""
                INSERT INTO documents 
                (id, title, url, type, content, processed_text, content_cleaned, extraction_method,
                 badness_score, greek_percentage, english_percentage, 
                 consultation_id, status, created_at, updated_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (doc_id, title, url, doc_type, content, content, None, extraction_method,
                  None, None, None, consultation_id, current_status))
            
            self.stats['documents']['transferred'] += 1
        
        new_conn.commit()
        logger.info(f"Transferred {self.stats['documents']['transferred']} documents")
        logger.info(f"Documents with content: {self.stats['documents']['with_content']}")
        logger.info("All documents marked as extracted with 'docling'")
    
    def transfer_comments(self, old_conn: sqlite3.Connection, new_conn: sqlite3.Connection):
        """Transfer comments data (identical schema)."""
        logger.info("Transferring comments...")
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        # Get all comments from old database
        old_cursor.execute("""
            SELECT id, comment_id, username, date, content, article_id
            FROM comments
        """)
        comments = old_cursor.fetchall()
        
        self.stats['comments']['total'] = len(comments)
        
        # Insert into new database with extraction_method
        for comment in comments:
            comment_id, comment_external_id, username, date, content, article_id = comment
            
            # All comments are extracted with markdownify
            extraction_method = 'markdownify'
            
            new_cursor.execute("""
                INSERT INTO comments 
                (id, comment_id, username, date, content, extraction_method, article_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (comment_id, comment_external_id, username, date, content, extraction_method, article_id))
            self.stats['comments']['transferred'] += 1
        
        new_conn.commit()
        logger.info(f"Transferred {self.stats['comments']['transferred']} comments")
        logger.info("All comments marked as extracted with 'markdownify'")
    
    def verify_transfer(self):
        """Verify that the transfer was successful."""
        logger.info("Verifying transfer...")
        
        old_counts = self.get_table_counts(self.old_db_path)
        new_counts = self.get_table_counts(self.new_db_path)
        
        logger.info("\nTransfer Verification:")
        logger.info("=" * 50)
        
        all_good = True
        for table in ['ministries', 'consultations', 'articles', 'documents', 'comments']:
            old_count = old_counts.get(table, 0)
            new_count = new_counts.get(table, 0)
            status = "✓" if old_count == new_count else "✗"
            
            if old_count != new_count:
                all_good = False
            
            logger.info(f"{status} {table}: {old_count} → {new_count}")
        
        logger.info("=" * 50)
        
        if all_good:
            logger.info("✓ All data transferred successfully!")
        else:
            logger.error("✗ Some data was not transferred correctly!")
        
        return all_good
    
    def verify_external_tables(self):
        """Verify that all external document tables were created."""
        logger.info("Verifying external document tables...")
        
        conn = sqlite3.connect(self.new_db_path)
        cursor = conn.cursor()
        
        external_tables = ['nomoi', 'ypourgikes_apofaseis', 'proedrika_diatagmata', 'eu_regulations', 'eu_directives']
        
        for table_name in external_tables:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if cursor.fetchone():
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                logger.info(f"✓ Table '{table_name}' exists with {count} records")
            else:
                logger.error(f"✗ Table '{table_name}' missing!")
        
        conn.close()
    
    def print_processing_summary(self):
        """Print summary of what needs to be processed next."""
        logger.info("\nProcessing Requirements Summary:")
        logger.info("=" * 60)
        
        # Documents needing Rust cleaning
        docs_with_content = self.stats['documents']['with_content']
        logger.info(f"📄 Documents with content needing Rust cleaning: {docs_with_content}")
        logger.info("   → All documents marked as extracted with 'docling'")
        logger.info("   → Run: python utils/post_migration_processing.py")
        
        # Articles needing content cleaning
        articles_with_content = self.stats['articles']['with_content']
        logger.info(f"📝 Articles with content: {articles_with_content}")
        logger.info("   → All articles marked as extracted with 'markdownify'")
        
        # Comments info
        comments_total = self.stats['comments']['transferred']
        logger.info(f"💬 Comments transferred: {comments_total}")
        logger.info("   → All comments marked as extracted with 'markdownify'")
        logger.info("   → Comments from old DB may need re-extraction if originally from docling")
        
        # External tables
        logger.info(f"🏛️ External document tables created (empty): 5 tables")
        logger.info("   → nomoi, ypourgikes_apofaseis, proedrika_diatagmata, eu_regulations, eu_directives")
        
        logger.info("\nNext Steps:")
        logger.info("1. Run Rust cleaner on documents with content")
        logger.info("2. Run scraper to fetch new data and verify migration")
        logger.info("3. Consider re-extracting comments if they were originally from docling")
        logger.info("4. Populate external document tables as needed")
        logger.info("5. Test pipeline with migrated data")
        
        logger.info("=" * 60)
    
    def run_migration(self) -> bool:
        """Run the complete migration process."""
        try:
            logger.info("Starting data transfer migration...")
            logger.info(f"Old database: {self.old_db_path}")
            logger.info(f"New database: {self.new_db_path}")
            
            # Step 1: Create backup
            backup_path = self.create_backup()
            logger.info(f"Backup created: {backup_path}")
            
            # Step 2: Initialize new database
            engine, Session = self.initialize_new_database()
            
            # Step 3: Connect to both databases
            old_conn = sqlite3.connect(self.old_db_path)
            new_conn = sqlite3.connect(self.new_db_path)
            
            try:
                # Step 4: Transfer data table by table
                self.transfer_ministries(old_conn, new_conn)
                self.transfer_consultations(old_conn, new_conn)
                self.transfer_articles(old_conn, new_conn)
                self.transfer_documents(old_conn, new_conn)
                self.transfer_comments(old_conn, new_conn)
                
                # Step 5: Verify transfer
                success = self.verify_transfer()
                
                # Step 6: Verify external tables
                self.verify_external_tables()
                
                if success:
                    # Step 7: Print processing summary
                    self.print_processing_summary()
                    logger.info("✓ Migration completed successfully!")
                    logger.info("\nRecommended next step:")
                    logger.info("python scraper/main_scraper.py --update")
                    return True
                else:
                    logger.error("✗ Migration verification failed!")
                    return False
                    
            finally:
                old_conn.close()
                new_conn.close()
                
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            import traceback
            traceback.print_exc()
            return False

def main():
    """Main function for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Transfer data from old to new database schema')
    parser.add_argument('old_db_path', help='Path to the old database file')
    parser.add_argument('new_db_path', help='Path for the new database file')
    parser.add_argument('--verify-only', action='store_true',
                       help='Only verify an existing migration')
    
    args = parser.parse_args()
    
    # Resolve paths
    old_db_path = os.path.abspath(args.old_db_path)
    new_db_path = os.path.abspath(args.new_db_path)
    
    if not os.path.exists(old_db_path):
        logger.error(f"Old database not found: {old_db_path}")
        sys.exit(1)
    
    migration = DataTransferMigration(old_db_path, new_db_path)
    
    if args.verify_only:
        if os.path.exists(new_db_path):
            success = migration.verify_transfer()
            sys.exit(0 if success else 1)
        else:
            logger.error(f"New database not found for verification: {new_db_path}")
            sys.exit(1)
    else:
        success = migration.run_migration()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 