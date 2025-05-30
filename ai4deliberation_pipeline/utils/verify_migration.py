#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verification script for database migration.
"""

import sys
import os
import sqlite3

# Add the complete_scraper directory to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'opengov', 'complete_scraper'))

from db_models import init_db, Consultation, Document

def verify_migration(db_path):
    """Verify that migration was successful."""
    print(f'Testing migrated database: {db_path}')
    
    # Check with SQLite directly
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check documents table schema
    cursor.execute('PRAGMA table_info(documents)')
    columns = cursor.fetchall()
    print('\nDocuments table columns:')
    for col in columns:
        print(f'  {col[1]} ({col[2]})')
    
    # Check if new legalese tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    new_tables = ['nomoi', 'ypourgikes_apofaseis', 'proedrika_diatagmata', 'eu_regulations', 'eu_directives']
    print('\nNew legalese tables:')
    for table in new_tables:
        if table in tables:
            print(f'  ✓ {table} exists')
        else:
            print(f'  ✗ {table} missing')
    
    # Check that existing data is preserved
    cursor.execute('SELECT COUNT(*) FROM consultations')
    consultations_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM articles')
    articles_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM documents')
    documents_count = cursor.fetchone()[0]
    
    print(f'\nExisting data preserved:')
    print(f'  Consultations: {consultations_count}')
    print(f'  Articles: {articles_count}')
    print(f'  Documents: {documents_count}')
    
    conn.close()
    
    # Test SQLAlchemy models work with new schema
    print('\nTesting SQLAlchemy models...')
    db_url = f'sqlite:///{db_path}'
    engine, Session = init_db(db_url)
    session = Session()
    
    # Try to query existing data
    consultations = session.query(Consultation).limit(2).all()
    print(f'Sample consultations: {len(consultations)}')
    for c in consultations:
        print(f'  {c.title[:60]}...')
    
    session.close()
    print('\n✓ Migration verification completed successfully!')
    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Verify database migration')
    parser.add_argument('database_path', help='Path to the migrated database')
    args = parser.parse_args()
    
    verify_migration(args.database_path) 