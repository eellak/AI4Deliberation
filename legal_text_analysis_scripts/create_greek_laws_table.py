import pandas as pd
import sqlite3
import os
from datetime import datetime
import re

def extract_year_from_date(date_val):
    """Extract year from date string or datetime"""
    if pd.isna(date_val) or not date_val:
        return None
    
    # Handle datetime objects
    if isinstance(date_val, pd.Timestamp):
        return date_val.year
    
    # Try to parse as datetime first
    try:
        return pd.to_datetime(date_val, errors='coerce').year
    except:
        pass
    
    # Try to extract 4-digit year using regex
    try:
        match = re.search(r'\b(\d{4})\b', str(date_val))
        if match:
            return int(match.group(1))
    except:
        pass
    
    return None

def safe_convert_to_string(value):
    """Safely convert any value to string, handling NaN and None"""
    if pd.isna(value) or value is None:
        return None
    return str(value)

def safe_convert_to_int(value):
    """Safely convert value to int, handling NaN and None"""
    if pd.isna(value) or value is None:
        return None
    try:
        return int(value)
    except:
        return None

def safe_convert_to_bool(value):
    """Safely convert value to bool, handling NaN and None"""
    if pd.isna(value) or value is None:
        return None
    return bool(value)

def read_markdown_content(md_file_path):
    """Read markdown file content safely"""
    try:
        with open(md_file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading {md_file_path}: {e}")
        return None

def create_greek_laws_table():
    """Create and populate the Greek_laws table"""
    
    # Paths
    parquet_path = '/mnt/data/gazette_processing/download_results/download_results.parquet'
    markdown_dir = '/mnt/data/gazette_processing/markdown'
    db_path = '/mnt/data/AI4Deliberation/new_html_extraction/deliberation_data_gr_markdownify.db'
    
    print("Loading parquet file...")
    try:
        df = pd.read_parquet(parquet_path)
        print(f"Loaded {len(df)} records from parquet file")
    except Exception as e:
        print(f"Error loading parquet file: {e}")
        return
    
    print("Connecting to database...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return
    
    # Drop table if exists and create the Greek_laws table
    print("Creating Greek_laws table...")
    cursor.execute("DROP TABLE IF EXISTS Greek_laws")
    
    create_table_sql = """
    CREATE TABLE Greek_laws (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        law_type TEXT,
        law_number TEXT,
        description TEXT,
        fek_title TEXT,
        fek_url TEXT,
        date TEXT,
        entry_year INTEGER,
        pages TEXT,
        preferred_url TEXT,
        download_success BOOLEAN,
        filename TEXT,
        download_error TEXT,
        download_retry_count INTEGER,
        extraction TEXT,
        processing_stage TEXT,
        markdown_content TEXT,
        content_size INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    
    cursor.execute(create_table_sql)
    conn.commit()
    
    print("Processing records and inserting data...")
    successful_inserts = 0
    failed_inserts = 0
    
    for index, row in df.iterrows():
        try:
            # Get the corresponding markdown filename
            pdf_filename = safe_convert_to_string(row['filename'])
            if not pdf_filename or not pdf_filename.endswith('.pdf'):
                print(f"Invalid filename format: {pdf_filename}")
                failed_inserts += 1
                continue
                
            md_filename = pdf_filename.replace('.pdf', '.md')
            md_file_path = os.path.join(markdown_dir, md_filename)
            
            # Read markdown content
            markdown_content = read_markdown_content(md_file_path)
            if markdown_content is None:
                print(f"Could not read markdown file: {md_filename}")
                failed_inserts += 1
                continue
            
            # Extract year from date
            entry_year = extract_year_from_date(row['date'])
            
            # Calculate content size
            content_size = len(markdown_content) if markdown_content else 0
            
            # Safely convert all data
            insert_data = (
                safe_convert_to_string(row['law_type']),
                safe_convert_to_string(row['law_number']), 
                safe_convert_to_string(row['description']),
                safe_convert_to_string(row['fek_title']),
                safe_convert_to_string(row['fek_url']),
                safe_convert_to_string(row['date']),
                entry_year,
                safe_convert_to_string(row['pages']),
                safe_convert_to_string(row['preferred_url']),
                safe_convert_to_bool(row['download_success']),
                safe_convert_to_string(row['filename']),
                safe_convert_to_string(row['download_error']),
                safe_convert_to_int(row['download_retry_count']),
                safe_convert_to_string(row['extraction']),
                safe_convert_to_string(row['processing_stage']),
                markdown_content,
                content_size
            )
            
            # Insert into database
            insert_sql = """
            INSERT INTO Greek_laws (
                law_type, law_number, description, fek_title, fek_url, date, entry_year,
                pages, preferred_url, download_success, filename, download_error,
                download_retry_count, extraction, processing_stage, markdown_content, content_size
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            cursor.execute(insert_sql, insert_data)
            successful_inserts += 1
            
            # Progress indicator
            if (index + 1) % 100 == 0:
                print(f"Processed {index + 1}/{len(df)} records...")
                conn.commit()  # Commit every 100 records
                
        except Exception as e:
            print(f"Error processing record {index}: {e}")
            failed_inserts += 1
            continue
    
    # Final commit
    conn.commit()
    
    print(f"\nProcessing complete!")
    print(f"Successfully inserted: {successful_inserts} records")
    print(f"Failed insertions: {failed_inserts} records")
    
    # Verify the table
    cursor.execute("SELECT COUNT(*) FROM Greek_laws")
    count = cursor.fetchone()[0]
    print(f"Total records in Greek_laws table: {count}")
    
    # Show sample data
    cursor.execute("SELECT id, law_type, law_number, entry_year, filename, content_size FROM Greek_laws LIMIT 5")
    sample_rows = cursor.fetchall()
    print("\nSample data from Greek_laws table:")
    for row in sample_rows:
        print(f"  ID: {row[0]}, Type: {row[1]}, Number: {row[2]}, Year: {row[3]}, File: {row[4]}, Size: {row[5]} chars")
    
    conn.close()
    print("Database connection closed.")

if __name__ == '__main__':
    create_greek_laws_table() 