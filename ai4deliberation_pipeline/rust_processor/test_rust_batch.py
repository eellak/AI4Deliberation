#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for Rust cleaning pipeline - processes a small batch for verification.
"""

import os
import sys
import sqlite3

# Add parent directory for imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from rust_pipeline.rust_processor import RustProcessor
from master_pipeline.utils import load_config

def test_rust_cleaning_small_batch(batch_size=5):
    """Test Rust cleaning with a small batch of documents."""
    
    print(f"Testing Rust cleaning with {batch_size} documents")
    print("=" * 60)
    
    # Initialize processor
    processor = RustProcessor()
    
    # Get a small batch of documents
    config = load_config()
    database_path = config['database']['default_path']
    
    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        
        # Get a few documents with content but no cleaned content
        query = """
        SELECT id, type, LENGTH(content) as content_length
        FROM documents
        WHERE content IS NOT NULL 
        AND content != ''
        AND content_cleaned IS NULL
        ORDER BY id
        LIMIT ?
        """
        
        cursor.execute(query, (batch_size,))
        docs_info = cursor.fetchall()
        conn.close()
        
        if not docs_info:
            print("No documents found for testing")
            return False
        
        print(f"Found {len(docs_info)} documents for testing:")
        for doc_id, doc_type, content_length in docs_info:
            print(f"  Document {doc_id}: type={doc_type}, content_length={content_length}")
        
        print("\nGetting documents for processing...")
        documents = processor.get_documents_needing_cleaning()[:batch_size]
        
        print(f"Processing {len(documents)} documents with Rust cleaner...")
        results = processor.process_documents_with_rust(documents)
        
        if results:
            print(f"\nRust processing completed successfully!")
            print(f"Processed {len(results)} documents")
            
            # Show sample results
            for doc_id, result in list(results.items())[:3]:  # Show first 3
                print(f"\nDocument {doc_id}:")
                print(f"  Badness score: {result['badness_score']:.3f}")
                print(f"  Greek percentage: {result['greek_percentage']:.1f}%")
                print(f"  English percentage: {result['english_percentage']:.1f}%")
                print(f"  Original content length: {result['total_chars']}")
                if result['cleaned_content']:
                    print(f"  Cleaned content length: {len(result['cleaned_content'])}")
                    print(f"  Cleaned content preview: {result['cleaned_content'][:100]}...")
                else:
                    print(f"  No cleaned content produced")
            
            # Update database
            print(f"\nUpdating database with results...")
            success = processor.update_database_with_results(results)
            
            if success:
                print("Database update successful!")
                
                # Verify the updates
                print("\nVerifying database updates...")
                stats = processor.get_cleaning_stats()
                print(f"Total documents with content: {stats.get('total_with_content', 0)}")
                print(f"Total cleaned documents: {stats.get('total_cleaned', 0)}")
                print(f"Documents still needing cleaning: {stats.get('need_cleaning', 0)}")
                
                return True
            else:
                print("Database update failed!")
                return False
        else:
            print("Rust processing failed!")
            return False
            
    except Exception as e:
        print(f"Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_rust_cleaning_small_batch()
    if success:
        print("\n✅ Test completed successfully!")
    else:
        print("\n❌ Test failed!")
        sys.exit(1) 