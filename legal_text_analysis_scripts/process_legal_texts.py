import re
import pandas as pd
import importlib.util
import warnings
import json
import os

# Suppress specific warnings from openpyxl if they occur during pandas operations
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

def load_regex_patterns(script_path):
    """Loads regex patterns from a given Python script path."""
    try:
        spec = importlib.util.spec_from_file_location("regex_module", script_path)
        regex_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(regex_module)
        
        patterns = {}
        if hasattr(regex_module, 'LAW_REGEX_PATTERN'):
            patterns['law'] = regex_module.LAW_REGEX_PATTERN
        if hasattr(regex_module, 'PRESIDENTIAL_DECREE_REGEX_PATTERN'):
            patterns['presidential_decree'] = regex_module.PRESIDENTIAL_DECREE_REGEX_PATTERN
        if hasattr(regex_module, 'MINISTERIAL_DECISION_REGEX_PATTERN'):
            patterns['ministerial_decision'] = regex_module.MINISTERIAL_DECISION_REGEX_PATTERN
        
        if not patterns:
            raise AttributeError("No regex patterns found in the specified script.")
        return patterns
    except Exception as e:
        print(f"Error loading regex patterns from {script_path}: {e}")
        raise

def preprocess_presidential_decrees(df):
    """Preprocesses the Presidential Decrees DataFrame."""
    df_processed = df.copy()
    if 'law_number' in df_processed.columns:
        df_processed['law_number'] = df_processed['law_number'].astype(str).str.strip()
    else:
        print("Warning: 'law_number' column not found in Presidential Decrees DataFrame.")
        df_processed['law_number'] = pd.Series(dtype='str')

    if 'date' in df_processed.columns:
        def extract_year(date_str):
            if pd.isna(date_str):
                return None
            try:
                return pd.to_datetime(date_str, errors='coerce').year
            except Exception:
                match = re.search(r'\b(\d{4})\b', str(date_str)) # Corrected: \b for word boundary
                if match:
                    return int(match.group(1))
                return None
        
        df_processed['DocumentYear'] = df_processed['date'].apply(extract_year)
        df_processed['DocumentYear'] = df_processed['DocumentYear'].fillna(0).astype(int)
    else:
        print("Warning: 'date' column not found in Presidential Decrees DataFrame.")
        df_processed['DocumentYear'] = pd.Series(dtype='int')

    return df_processed

def preprocess_ministerial_decisions(df):
    """Preprocesses the Ministerial Decisions (YA) DataFrame."""
    df_processed = df.copy()

    if 'fek_title' not in df_processed.columns:
        print("Warning: 'fek_title' column not found in Ministerial Decisions DataFrame.")
        df_processed['MD_Series'] = pd.Series(dtype='str')
        df_processed['MD_Number'] = pd.Series(dtype='str')
        df_processed['MD_Year'] = pd.Series(dtype='int')
        return df_processed

    pattern = re.compile(
        r""" # raw string for regex
        (?:(?P<series>[Α-ΩA-ZΆ-Ώά-ώ.\s]+?)\s+)? # Optional series
        (?P<number>[\w.\-/]+?)                  # Number part
        \s*/\s*
        (?P<year>\d{4})                           # Year (4 digits)
        (?:\s*\(.*\))?                            # Optional text in parentheses
        $                                          # End of string
        """, re.VERBOSE
    )
    
    general_pattern = re.compile(
        r""" # raw string for regex
        (?P<number_like>[A-ZΑ-Ω0-9\s.\-/()]+?) # Capture a broad "number-like" part
        (?:\s*/\s*(?P<year>\d{4}))?          # Optionally capture a year if separated by /
        """, re.VERBOSE | re.IGNORECASE
    )

    def parse_fek_title(title_str):
        if pd.isna(title_str):
            return None, None, None
        
        title_str = str(title_str).strip()
        
        match_specific = pattern.match(title_str)
        if match_specific:
            series = match_specific.group('series')
            number = match_specific.group('number')
            year = match_specific.group('year')
            return series.strip() if series else None, number.strip() if number else None, int(year) if year else None

        # General extraction if specific fails
        # Corrected regex: \d for digits, \s for space, ensure proper escaping for special chars if any were missed.
        num_match = re.search(r'([A-ZΑ-Ω0-9.\-/]+(?:\s*/\s*[A-ZΑ-Ω0-9.\-/]+)*)', title_str)
        year_match = re.search(r'(\d{4})(?!.*\d{4})', title_str) # last 4-digit year

        gen_number = num_match.group(1).strip() if num_match else None
        gen_year = int(year_match.group(1)) if year_match else None
        
        series_match = re.match(r'^([Α-ΩA-ZΆ-Ώά-ώ.]+)', title_str)
        gen_series = None
        if series_match and gen_number:
             # Check if series is genuinely a prefix and not the whole number itself
            if gen_number.startswith(series_match.group(1).strip()) and len(gen_number) > len(series_match.group(1).strip()):
                gen_series = series_match.group(1).strip()

        if gen_number and gen_year:
            if gen_series and gen_number.startswith(gen_series):
                potential_num = gen_number[len(gen_series):].strip()
                if potential_num:
                    gen_number = potential_num
            return gen_series, gen_number, gen_year
            
        return None, None, None

    parsed_titles = df_processed['fek_title'].apply(lambda x: pd.Series(parse_fek_title(x)))
    df_processed[['MD_Series', 'MD_Number', 'MD_Year']] = parsed_titles

    df_processed['MD_Series'] = df_processed['MD_Series'].astype(str).fillna('').str.upper()
    df_processed['MD_Number'] = df_processed['MD_Number'].astype(str).fillna('').str.strip()
    df_processed['MD_Year'] = pd.to_numeric(df_processed['MD_Year'], errors='coerce').fillna(0).astype(int)
    
    return df_processed


def find_and_match_documents(text_to_search, df_presidential, df_ministerial, patterns_dict):
    """
    Finds legal references in text and matches them against provided DataFrames.
    """
    found_references = []

    try:
        pd_regex_str = patterns_dict.get('presidential_decree')
        md_regex_str = patterns_dict.get('ministerial_decision')

        if not pd_regex_str:
            print("Presidential Decree regex pattern not found.")
            return found_references
        if not md_regex_str:
            print("Ministerial Decision regex pattern not found.")
            return found_references
            
        pd_pattern = re.compile(pd_regex_str, re.IGNORECASE | re.VERBOSE)
        md_pattern = re.compile(md_regex_str, re.IGNORECASE | re.VERBOSE)
    except Exception as e:
        print(f"Error compiling regex patterns: {e}")
        return found_references

    print("\nStarting search for Presidential Decrees...")
    for match in pd_pattern.finditer(text_to_search):
        match_details = match.groupdict()
        
        regex_pd_number = match_details.get('number')
        # Check for either year_num or year_date from the modified regex
        regex_pd_year_str = match_details.get('year_num') or match_details.get('year_date')

        if not regex_pd_number or not regex_pd_year_str:
            # print(f"Skipping PD match due to missing number or year: {match.group(0)}")
            continue
        
        try:
            regex_pd_year = int(regex_pd_year_str)
        except ValueError:
            # print(f"Skipping PD match due to invalid year format: {regex_pd_year_str} in {match.group(0)}")
            continue

        # Filter DataFrame
        if 'law_number' in df_presidential.columns and 'DocumentYear' in df_presidential.columns:
            condition = (df_presidential['law_number'].str.strip().str.lower() == str(regex_pd_number).strip().lower()) & \
                        (df_presidential['DocumentYear'] == regex_pd_year)
            matched_data_df = df_presidential[condition]

            if not matched_data_df.empty:
                found_references.append({
                    'source_text': match.group(0),
                    'regex_match_details': match_details,
                    'document_type': 'Presidential Decree',
                    'matched_data': matched_data_df.to_dict(orient='records')
                })
        else:
            print("Presidential Decree DataFrame missing 'law_number' or 'DocumentYear' for matching.")
            break
    print("Finished search for Presidential Decrees.")

    print("\nStarting search for Ministerial Decisions...")
    for match in md_pattern.finditer(text_to_search):
        match_details = match.groupdict()

        # If the 'undesired_prefix' group is matched, this is not the reference we want.
        if match_details.get('undesired_prefix'):
            continue
        
        # Ministerial decision regex has alternative capture groups (id1/id2, etc.)
        regex_md_id = match_details.get('id1') or match_details.get('id2')
        regex_md_fek_series = match_details.get('fek_series1') or match_details.get('fek_series2')
        # regex_md_fek_number = match_details.get('fek_number1') or match_details.get('fek_number2') # Not directly used for now, id1/id2 is primary number
        regex_md_fek_year_str = match_details.get('fek_year1') or match_details.get('fek_year2')

        if not regex_md_id:
            continue
            
        regex_md_id = str(regex_md_id).strip()
        conditions = (df_ministerial['MD_Number'].str.strip().str.lower() == regex_md_id.lower())

        if regex_md_fek_year_str:
            try:
                regex_md_fek_year_int = int(regex_md_fek_year_str)
                conditions &= (df_ministerial['MD_Year'] == regex_md_fek_year_int)
            except ValueError:
                pass 

        if regex_md_fek_series:
            regex_md_fek_series = str(regex_md_fek_series).strip().upper()
            # Ensure MD_Series exists and is not empty for comparison
            if 'MD_Series' in df_ministerial.columns:
                 conditions &= (df_ministerial['MD_Series'].fillna('').str.strip().str.upper() == regex_md_fek_series)

        if 'MD_Number' in df_ministerial.columns and 'MD_Year' in df_ministerial.columns:
            matched_data_df = df_ministerial[conditions]
            if not matched_data_df.empty:
                found_references.append({
                    'source_text': match.group(0),
                    'regex_match_details': match_details,
                    'document_type': 'Ministerial Decision',
                    'matched_data': matched_data_df.to_dict(orient='records')
                })
        else:
            print("Ministerial Decision DataFrame missing 'MD_Number' or 'MD_Year' for matching.")
            break
    print("Finished search for Ministerial Decisions.")
    return found_references


def main():
    REGEX_SCRIPT_PATH = '/mnt/data/Myrsini/ai4deliberation/regex_capture_groups.py'
    TEST_TEXT_PATH = '/mnt/data/Myrsini/ai4deliberation/exported_consultations_data.txt'
    PRESIDENTIAL_DECREES_PARQUET_PATH = '/mnt/data/Myrsini/ai4deliberation/FEK/metadata/download_results_Presidantial_2005-2025.parquet'
    MINISTERIAL_DECISIONS_PARQUET_PATH = '/mnt/data/Myrsini/ai4deliberation/FEK/metadata/download_results_YA05-25.parquet'
    OUTPUT_JSON_FILE_NAME = 'matched_legal_references.json'

    print("Loading regex patterns...")
    try:
        patterns = load_regex_patterns(REGEX_SCRIPT_PATH)
    except Exception:
        return

    print("Loading Parquet files...")
    try:
        df_presidential = pd.read_parquet(PRESIDENTIAL_DECREES_PARQUET_PATH)
        df_ministerial_ya = pd.read_parquet(MINISTERIAL_DECISIONS_PARQUET_PATH)
    except FileNotFoundError as e:
        print(f"Error: Parquet file not found. {e}")
        return
    except Exception as e:
        print(f"Error loading Parquet files: {e}")
        return
        
    print("Preprocessing DataFrames...")
    df_presidential_processed = preprocess_presidential_decrees(df_presidential)
    df_ministerial_ya_processed = preprocess_ministerial_decisions(df_ministerial_ya)

    print(f"Presidential Decrees DataFrame - Processed sample: {df_presidential_processed[['law_number', 'DocumentYear']].head()}")
    print(f"Ministerial Decisions (YA) DataFrame - Processed sample: {df_ministerial_ya_processed[['fek_title', 'MD_Series', 'MD_Number', 'MD_Year']].head()}")

    print(f"Loading test text from {TEST_TEXT_PATH}...")
    try:
        with open(TEST_TEXT_PATH, 'r', encoding='utf-8') as f:
            test_text = f.read()
    except FileNotFoundError:
        print(f"Error: Test text file not found at {TEST_TEXT_PATH}")
        return
    except Exception as e:
        print(f"Error reading test text file: {e}")
        return

    print("\n--- Starting Document Matching ---\n")
    matched_references = find_and_match_documents(
        test_text,
        df_presidential_processed,
        df_ministerial_ya_processed,
        patterns
    )

    if not matched_references:
        print("No matching documents found in the text.")
    else:
        print(f"Found {len(matched_references)} potential document references:\n")
        for ref in matched_references:
            print(f"Source Text: \"{ref['source_text']}\"")
            print(f"  Document Type: {ref['document_type']}")
            print(f"  Regex Details: {ref['regex_match_details']}")
            print(f"  Matched Data ({len(ref['matched_data'])} record(s)):")
            for record in ref['matched_data']:
                print(f"    - PD_LawNo: {record.get('law_number')}, PD_Year: {record.get('DocumentYear')}, PD_Date: {record.get('date')}, Filename: {record.get('filename')}" if ref['document_type'] == 'Presidential Decree' 
                      else f"    - MD_FekTitle: {record.get('fek_title')}, MD_Series: {record.get('MD_Series')}, MD_Num: {record.get('MD_Number')}, MD_Year: {record.get('MD_Year')}, Filename: {record.get('filename')}")
            print("-" * 30)

        # --- Exporting matched references to JSON ---
        # Get the directory of the current script to save the JSON in the same location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_json_path = os.path.join(script_dir, OUTPUT_JSON_FILE_NAME)
        
        print(f"\nExporting {len(matched_references)} found references to {output_json_path}...")
        try:
            with open(output_json_path, 'w', encoding='utf-8') as f_json:
                json.dump(matched_references, f_json, ensure_ascii=False, indent=4)
            print(f"Successfully exported matched references to {output_json_path}")
        except IOError as e:
            print(f"Error writing JSON to file: {e}")
        except Exception as e:
            print(f"An unexpected error occurred during JSON export: {e}")

if __name__ == '__main__':
    main() 