#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Complete end-to-end test of the AI4Deliberation pipeline.
"""

import os
import sys
import logging
import sqlite3
import shutil # Added for deleting the test DB

# Set up paths for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Define a test database path
TEST_DB_PATH = os.path.join(current_dir, "test_pipeline_from_scratch.db")

def test_complete_pipeline():
    """Test the complete AI4Deliberation pipeline end-to-end."""
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Test URL from how_to_test.md
    test_url = "https://www.opengov.gr/ypoian/?p=14356"
    expected_articles = 7
    expected_comments = 14 # Approximate, as per how_to_test.md
    expected_documents = 2
    expected_processed_documents = 1
    
    print("="*80)
    print("🚀 COMPLETE AI4DELIBERATION PIPELINE TEST")
    print(f"URL: {test_url}")
    print("="*80)
    
    try:
        # Import pipeline components
        from config.config_manager import load_config
        from utils.logging_utils import setup_logging
        from master.pipeline_orchestrator import PipelineOrchestrator
        
        print("✅ Imports successful")
        
        # Load configuration but override database path for this test
        base_config = load_config()
        test_config = base_config.copy() # Create a mutable copy
        test_config['database']['default_path'] = TEST_DB_PATH
        
        # Ensure the database file is removed before starting if it exists
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
            print(f"🗑️ Removed existing test database: {TEST_DB_PATH}")

        database_path = TEST_DB_PATH # Use the test DB path
        
        # STEP 1: (Skipped for scratch test as DB is new or removed)
        print(f"\nℹ️ STEP 1: Skipped - Running test from scratch with a new database.")
        # The original cleanup logic is removed as we start with a fresh DB.
        # If the DB existed, it was removed above.
        # If it didn't exist, it will be created by the pipeline.

        # Verify database is clean (or non-existent)
        if os.path.exists(database_path):
            conn_check = sqlite3.connect(database_path)
            cursor_check = conn_check.cursor()
            try:
                cursor_check.execute("SELECT COUNT(*) FROM consultations WHERE url = ?", (test_url,))
                remaining_consultations = cursor_check.fetchone()[0]
                if remaining_consultations > 0:
                    print(f"❌ ERROR: {remaining_consultations} consultations for the test URL already exist in the new DB! This should not happen.")
                    conn_check.close()
                    return False
            except sqlite3.OperationalError: # Tables might not exist yet
                print("✅ Database is new, tables not yet created (as expected).")
            conn_check.close()
        else:
            print(f"✅ Database {database_path} does not exist (as expected for a scratch run).")
        
        # STEP 2: Initialize pipeline orchestrator
        print(f"\n🔧 STEP 2: Initializing pipeline orchestrator with test config...")
        # Pass the modified config to the orchestrator
        orchestrator = PipelineOrchestrator(test_config)
        print("✅ Pipeline orchestrator initialized")
        
        # STEP 3: Run the complete pipeline
        print(f"\n🎯 STEP 3: Running complete pipeline for consultation...")
        result = orchestrator.process_consultation(test_url, force_reprocess=False)
        
        print(f"\n📈 PIPELINE RESULTS:")
        print(f"  Success: {result.success}")
        print(f"  Consultation ID: {result.consultation_id}")
        print(f"  Articles processed: {result.articles_processed}")
        print(f"  Documents processed: {result.documents_processed}")
        print(f"  Processing time: {result.processing_time:.2f} seconds")
        
        if result.errors:
            print(f"  ❌ Errors: {result.errors}")
        
        # STEP 4: Verify results in database
        if result.consultation_id:
            print(f"\n🔍 STEP 4: VERIFICATION - Checking database results in {database_path}...")
            if not os.path.exists(database_path):
                print(f"❌ ERROR: Database {database_path} was not created by the pipeline.")
                return False

            conn = sqlite3.connect(database_path)
            cursor = conn.cursor()
            
            # Count articles
            cursor.execute("SELECT COUNT(*) FROM articles WHERE consultation_id = ?", (result.consultation_id,))
            article_count = cursor.fetchone()[0]
            
            # Count comments
            cursor.execute("SELECT COUNT(*) FROM comments WHERE article_id IN (SELECT id FROM articles WHERE consultation_id = ?)", (result.consultation_id,))
            comment_count = cursor.fetchone()[0]
            
            # Count documents
            cursor.execute("SELECT COUNT(*) FROM documents WHERE consultation_id = ?", (result.consultation_id,))
            document_count = cursor.fetchone()[0]
            
            # Check document processing details
            cursor.execute("""
                SELECT id, type, url, 
                       content IS NOT NULL as has_content,
                       content_cleaned IS NOT NULL as has_cleaned,
                       badness_score, greek_percentage, english_percentage, extraction_method
                FROM documents WHERE consultation_id = ?
            """, (result.consultation_id,))
            documents = cursor.fetchall()
            
            # Get consultation details
            cursor.execute("SELECT title FROM consultations WHERE id = ?", (result.consultation_id,))
            consultation_title = cursor.fetchone()[0]
            
            conn.close()
            
            print(f"  📄 Consultation: {consultation_title[:100]}...")
            print(f"  📑 Articles: {article_count} (expected: {expected_articles})")
            print(f"  💬 Comments: {comment_count} (expected: >= {expected_comments})") # Using >= for comments
            print(f"  📋 Documents: {document_count} (expected: {expected_documents})")
            
            print(f"\n📋 DOCUMENT PROCESSING DETAILS:")
            for doc_id, doc_type, doc_url, has_content, has_cleaned, badness, greek_pct, english_pct, method in documents:
                print(f"  Document {doc_id}:")
                print(f"    Type: {doc_type}")
                print(f"    Has content: {has_content}")
                print(f"    Has cleaned: {has_cleaned}")
                print(f"    Badness score: {badness}")
                print(f"    Greek %: {greek_pct}")
                print(f"    English %: {english_pct}")
                print(f"    Method: {method}")
                if doc_url:
                    print(f"    URL: {doc_url[:80]}...")
                print()
            
            # Count how many documents have content_cleaned
            processed_docs_count = sum(1 for doc in documents if doc[4]) # doc[4] is has_cleaned

            # Success criteria based on how_to_test.md
            success_criteria = {
                "Articles scraped": article_count == expected_articles,
                "Comments scraped": comment_count >= expected_comments, # allow more comments
                "Documents found": document_count == expected_documents,
                "Documents processed (cleaned)": processed_docs_count == expected_processed_documents,
                "Pipeline success": result.success
            }
            
            print(f"✅ SUCCESS CRITERIA:")
            all_passed = True
            for criterion, passed in success_criteria.items():
                status = "✅ PASS" if passed else "❌ FAIL"
                print(f"  {criterion}: {status}")
                if not passed:
                    all_passed = False
            
            print("\n" + "="*80)
            if all_passed:
                print("🎉 COMPLETE PIPELINE TEST: SUCCESS!")
                print("✅ All components working: scraper → PDF processor → text cleaner → database")
            else:
                print("💥 COMPLETE PIPELINE TEST: FAILED!")
                print("❌ Some components not working properly")
            print("="*80)
            
            # Clean up the test database
            # if all_passed and os.path.exists(TEST_DB_PATH):
            # print(f"\n🧹 Cleaning up test database: {TEST_DB_PATH}")
            # os.remove(TEST_DB_PATH)
            # print("✅ Test database removed.")
            # Decided against auto-deletion for now, to allow inspection post-run.

            return all_passed
        else:
            print("❌ No consultation ID returned - pipeline failed completely")
            return False
            
    except Exception as e:
        print(f"💥 Error running complete pipeline: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_complete_pipeline()
    sys.exit(0 if success else 1) 