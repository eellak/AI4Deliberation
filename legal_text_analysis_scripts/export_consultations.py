import sqlite3
import os

# --- Configuration ---
# Number of consultations to export
NUM_CONSULTATIONS_TO_EXPORT = 80 
# Path to the SQLite database
DB_PATH = '/mnt/data/Myrsini/ai4deliberation/deliberation_data_BACKUP.db'
# Output text file name
OUTPUT_FILE_NAME = 'exported_consultations_data.txt'
# ---------------------

def export_consultations_to_text(db_path, output_file, num_consultations):
    """
    Connects to the SQLite database, fetches data for the specified number of consultations
    and their related articles, and writes the data to a text file.
    """
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return

    conn = None
    output_lines = []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Fetch consultations
        # Querying specific columns as identified: id, title, start_minister_message, end_minister_message
        cursor.execute("""
            SELECT id, title, start_minister_message, end_minister_message 
            FROM consultations 
            ORDER BY id ASC 
            LIMIT ?
        """, (num_consultations,))
        consultations = cursor.fetchall()

        if not consultations:
            print(f"No consultations found in the database {db_path}.")
            return

        output_lines.append(f"Exporting data for {len(consultations)} consultations:\n")
        output_lines.append("=" * 50 + "\n")

        for i, consultation in enumerate(consultations):
            consultation_id, cons_title, start_message, end_message = consultation
            
            output_lines.append(f"--- Consultation {i+1} ---")
            output_lines.append(f"Consultation ID: {consultation_id}")
            output_lines.append(f"Consultation Title: {cons_title if cons_title else 'N/A'}")
            output_lines.append("Start Minister Message:")
            output_lines.append(f"{start_message if start_message else 'N/A'}")
            output_lines.append("End Minister Message:")
            output_lines.append(f"{end_message if end_message else 'N/A'}\n")
            
            # Fetch related articles for the current consultation
            # Querying specific columns: title, content
            cursor.execute("""
                SELECT title, content 
                FROM articles 
                WHERE consultation_id = ? 
                ORDER BY id ASC
            """, (consultation_id,))
            articles = cursor.fetchall()

            if articles:
                output_lines.append("  Related Articles:")
                for j, article in enumerate(articles):
                    article_title, article_content = article
                    output_lines.append(f"    Article {j+1}:")
                    output_lines.append(f"      Article Title: {article_title if article_title else 'N/A'}")
                    output_lines.append( "      Article Content:")
                    output_lines.append(f"      {article_content if article_content else 'N/A'}\n")
            else:
                output_lines.append("  No related articles found for this consultation.\n")
            
            output_lines.append("=" * 50 + "\n")

        # Write to output file
        with open(output_file, 'w', encoding='utf-8') as f:
            for line in output_lines:
                f.write(line + "\n")
        print(f"Successfully exported data to {output_file}")

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    except IOError as e:
        print(f"File I/O error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Construct the full path for the output file relative to the script directory
    output_file_path = os.path.join(script_dir, OUTPUT_FILE_NAME)
    
    export_consultations_to_text(DB_PATH, output_file_path, NUM_CONSULTATIONS_TO_EXPORT) 