#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug script to test database updates and figure out why they're not persisting.
"""

import os
import sys
import sqlite3

# Add parent directory for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from master_pipeline.utils import load_config

def debug_database_updates():
    """Debug database update issues."""
    
    config = load_config()
    database_path = config['database']['default_path']
    
    print(f"Database path: {database_path}")
    print(f"Database exists: {os.path.exists(database_path)}")
    
    # Test direct SQLite update
    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        
        # Check if columns exist
        cursor.execute("PRAGMA table_info(documents)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"Available columns: {columns}")
        
        # Check for columns we need
        required_cols = ['content_cleaned', 'badness_score', 'greek_percentage', 'english_percentage']
        missing_cols = [col for col in required_cols if col not in columns]
        if missing_cols:
            print(f"Missing columns: {missing_cols}")
            return False
        
        # Get one document to test with
        cursor.execute("SELECT id, content FROM documents WHERE content IS NOT NULL LIMIT 1")
        row = cursor.fetchone()
        if not row:
            print("No documents with content found")
            return False
        
        doc_id, content = row
        print(f"Testing with document ID {doc_id}")
        
        # Check current values
        cursor.execute("SELECT content_cleaned, badness_score FROM documents WHERE id = ?", (doc_id,))
        before = cursor.fetchone()
        print(f"Before update: content_cleaned={before[0] is not None}, badness_score={before[1]}")
        
        # Try to update
        test_cleaned = "TEST CLEANED CONTENT"
        test_badness = 0.123
        
        cursor.execute("""
            UPDATE documents 
            SET content_cleaned = ?, badness_score = ?, greek_percentage = ?, english_percentage = ?
            WHERE id = ?
        """, (test_cleaned, test_badness, 95.5, 4.5, doc_id))
        
        print(f"Updated {cursor.rowcount} rows")
        
        # Check values before commit
        cursor.execute("SELECT content_cleaned, badness_score, greek_percentage FROM documents WHERE id = ?", (doc_id,))
        after_no_commit = cursor.fetchone()
        print(f"After update (no commit): cleaned={after_no_commit[0] is not None}, badness={after_no_commit[1]}, greek={after_no_commit[2]}")
        
        # Commit
        conn.commit()
        print("Committed transaction")
        
        # Check values after commit
        cursor.execute("SELECT content_cleaned, badness_score, greek_percentage FROM documents WHERE id = ?", (doc_id,))
        after_commit = cursor.fetchone()
        print(f"After commit: cleaned={after_commit[0] is not None}, badness={after_commit[1]}, greek={after_commit[2]}")
        
        conn.close()
        
        # Reopen database and check persistence
        conn2 = sqlite3.connect(database_path)
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT content_cleaned, badness_score, greek_percentage FROM documents WHERE id = ?", (doc_id,))
        persistent = cursor2.fetchone()
        print(f"After reopening DB: cleaned={persistent[0] is not None}, badness={persistent[1]}, greek={persistent[2]}")
        conn2.close()
        
        # Check overall stats
        conn3 = sqlite3.connect(database_path)
        cursor3 = conn3.cursor()
        cursor3.execute("SELECT COUNT(*) FROM documents WHERE content_cleaned IS NOT NULL")
        count = cursor3.fetchone()[0]
        print(f"Total documents with cleaned content: {count}")
        conn3.close()
        
        return True
        
    except Exception as e:
        print(f"Error during debug: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    debug_database_updates() 