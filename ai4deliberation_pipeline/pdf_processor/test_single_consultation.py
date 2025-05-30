#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test PDF processing for a single consultation

This script tests the PDF processing pipeline with a single consultation
to verify everything works before processing the full dataset.
Excludes law_draft documents as they contain the same content as HTML.
"""

import os
import sys
import time
import logging
import sqlite3
import pandas as pd

# Add the master_pipeline to path for configuration utilities
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'master_pipeline'))
from utils import load_config

# Import GlossAPI
from glossapi.corpus import Corpus

def test_single_consultation_pdf_processing(consultation_id: int = 798):
    """
    Test PDF processing for a single consultation.
    
    Args:
        consultation_id: ID of consultation to test (default: 798 has 14 non-law docs)
    """
    print(f"🧪 Testing PDF processing for consultation {consultation_id}")
    
    # Load configuration
    config = load_config()
    database_path = config['database']['default_path']
    workspace_dir = os.path.join(config['directories']['temp_processing'], 'pdf_test_workspace')
    
    # Create workspace
    os.makedirs(workspace_dir, exist_ok=True)
    print(f"📁 Workspace: {workspace_dir}")
    
    # Step 1: Export documents for this consultation (excluding law_draft)
    print("\n📋 Step 1: Exporting documents for testing...")
    
    conn = sqlite3.connect(database_path)
    
    # Query for non-law documents without content
    query = """
    SELECT d.id as document_id, d.title, d.url, d.type
    FROM documents d
    JOIN consultations c ON d.consultation_id = c.id  
    WHERE d.consultation_id = ? 
    AND d.url IS NOT NULL 
    AND d.url != ''
    AND (d.content IS NULL OR d.content = '')
    AND d.type != 'law_draft'
    ORDER BY d.id
    """
    
    df = pd.read_sql_query(query, conn, params=(consultation_id,))
    
    if len(df) == 0:
        print(f"❌ No non-law documents needing processing found for consultation {consultation_id}")
        conn.close()
        return False
    
    print(f"✅ Found {len(df)} documents to process:")
    for _, row in df.iterrows():
        print(f"   - {row['document_id']}: {row['type']} - {row['title'][:50]}...")
    
    # Save to parquet
    parquet_path = os.path.join(workspace_dir, 'documents.parquet')
    df.to_parquet(parquet_path, index=False)
    print(f"💾 Exported to: {parquet_path}")
    
    # Also get consultation info for context
    cursor = conn.cursor()
    cursor.execute("SELECT url, title FROM consultations WHERE id = ?", (consultation_id,))
    consultation_info = cursor.fetchone()
    conn.close()
    
    print(f"🏛️  Consultation: {consultation_info[1]}")
    print(f"🔗 URL: {consultation_info[0]}")
    
    # Step 2: Process with GlossAPI
    print(f"\n⚙️  Step 2: Processing {len(df)} documents with GlossAPI...")
    
    try:
        # Create GlossAPI Corpus object
        corpus = Corpus(
            input_dir=workspace_dir,
            output_dir=workspace_dir,
            verbose=True
        )
        
        # Download PDFs
        print("📥 Downloading PDFs...")
        start_time = time.time()
        corpus.download(url_column='url', verbose=True)
        download_time = time.time() - start_time
        print(f"✅ Download completed in {download_time:.1f} seconds")
        
        # Extract text
        print("📄 Extracting text...")
        extract_start = time.time()
        corpus.extract(num_threads=2)  # Use fewer threads for testing
        extract_time = time.time() - extract_start
        print(f"✅ Extraction completed in {extract_time:.1f} seconds")
        
        # Skip sectioning for now (as user mentioned it's optional)
        print("⏭️  Skipping sectioning for test")
        
    except Exception as e:
        print(f"❌ Error in GlossAPI processing: {e}")
        return False
    
    # Step 3: Analyze results
    print(f"\n📊 Step 3: Analyzing results...")
    
    # Check download results
    download_results_file = os.path.join(workspace_dir, 'download_results', 'download_results.parquet')
    if os.path.exists(download_results_file):
        results_df = pd.read_parquet(download_results_file)
        print(f"📈 Processed {len(results_df)} documents")
        
        # Show extraction statistics
        extraction_counts = results_df['extraction'].value_counts()
        for status, count in extraction_counts.items():
            percentage = round(count / len(results_df) * 100, 1)
            print(f"   {status}: {count} ({percentage}%)")
        
        # Show some details
        print("\n🔍 Sample results:")
        for _, row in results_df.head(3).iterrows():
            print(f"   URL: {row['url'][:60]}...")
            print(f"   Extraction: {row['extraction']}")
            if 'length' in row:
                print(f"   Content length: {row.get('length', 'unknown')}")
            print()
            
    else:
        print("❌ Download results file not found")
        return False
    
    # Check markdown files
    markdown_dir = os.path.join(workspace_dir, 'markdown')
    if os.path.exists(markdown_dir):
        markdown_files = [f for f in os.listdir(markdown_dir) if f.endswith('.md')]
        print(f"📝 Found {len(markdown_files)} markdown files")
        
        # Show a sample
        if markdown_files:
            sample_file = os.path.join(markdown_dir, markdown_files[0])
            with open(sample_file, 'r', encoding='utf-8') as f:
                content = f.read()
                print(f"📄 Sample content ({len(content)} chars):")
                print(f"   {content[:200]}...")
                if len(content) > 200:
                    print("   ...")
    else:
        print("❌ Markdown directory not found")
    
    print(f"\n✅ Test completed! Check results in: {workspace_dir}")
    return True

if __name__ == "__main__":
    # Test with consultation 798 (has 14 non-law documents)
    success = test_single_consultation_pdf_processing(consultation_id=798)
    
    if success:
        print("\n🎉 PDF processing test completed successfully!")
        print("   You can now proceed with larger batches.")
    else:
        print("\n💥 PDF processing test failed!")
        print("   Please check the errors above and fix issues before proceeding.") 