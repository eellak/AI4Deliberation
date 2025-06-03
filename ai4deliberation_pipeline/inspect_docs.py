import sqlite3
import os

def inspect_documents(db_path):
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    consultation_id_to_check = 1
    query = f"""
    SELECT id, consultation_id, url, status, processed_text, content_type, extraction_method, updated_at
    FROM documents 
    WHERE consultation_id = {consultation_id_to_check};
    """
    
    print(f"Executing query on {db_path} for consultation_id = {consultation_id_to_check}...")
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print(f"No documents found for consultation_id = {consultation_id_to_check}.")
            return

        print(f"\nDocuments for consultation_id = {consultation_id_to_check}:")
        for row in rows:
            doc_id, cons_id, url, status, processed_text_val, content_type_val, extraction_method_val, updated_at_val = row
            processed_text_summary = (processed_text_val[:100] + "..." if processed_text_val and len(processed_text_val) > 100 
                                      else ("<EMPTY>" if processed_text_val == "" else ("<NULL>" if processed_text_val is None else processed_text_val)))
            print(f"  ID: {doc_id}, URL: {url}")
            print(f"    Status: {status}, Content-Type: {content_type_val}, Extraction Method: {extraction_method_val}, Updated At: {updated_at_val}")
            print(f"    Processed Text (summary): {processed_text_summary}\n")
            
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    # The default database path used by the orchestrator without --db-path
    db_to_inspect = "/mnt/data/AI4Deliberation/ai4deliberation_pipeline/deliberation_data_gr_MIGRATED_FRESH_20250602135430.db"
    print(f"Inspecting documents in database: {os.path.abspath(db_to_inspect)}")
    inspect_documents(db_to_inspect) 