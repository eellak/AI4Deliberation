import re
import sqlite3
import pandas as pd

# Simplified regex pattern to detect only ν., Ν., or νόμου followed by number/year
SIMPLIFIED_LAW_REGEX = r"""
(?ix)  # Case-insensitive, verbose
(?P<type>ν\.|Ν\.|νόμου|νόμο)  # Only these three patterns
\s*
(?P<number>\d+)               # Law number (required)
\s*/\s*
(?P<year>\d{4})               # Year (required)
"""

def find_law_references_in_text(text):
    """Find law references in a given text using the simplified regex"""
    if not text:
        return []
    
    pattern = re.compile(SIMPLIFIED_LAW_REGEX, re.IGNORECASE | re.VERBOSE)
    matches = []
    
    for match in pattern.finditer(text):
        match_details = match.groupdict()
        matches.append({
            'full_match': match.group(0),
            'type': match_details.get('type'),
            'number': match_details.get('number'),
            'year': int(match_details.get('year')),
            'start_pos': match.start(),
            'end_pos': match.end()
        })
    
    return matches

def get_sample_consultations(db_path, limit=5):
    """Get sample consultations and their articles from the database"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get consultations with their articles
    query = """
    SELECT 
        c.id as consultation_id,
        c.title as consultation_title,
        a.id as article_id,
        a.title as article_title,
        a.content as article_content
    FROM consultations c
    JOIN articles a ON c.id = a.consultation_id
    WHERE a.content IS NOT NULL 
    AND LENGTH(a.content) > 100
    ORDER BY c.id ASC
    LIMIT ?
    """
    
    cursor.execute(query, (limit * 10,))  # Get more articles to have options
    results = cursor.fetchall()
    conn.close()
    
    return results

def find_matching_laws_in_db(law_references, db_path):
    """Find matching laws in the Greek_laws table based on number and year"""
    if not law_references:
        return []
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    matched_laws = []
    
    for ref in law_references:
        # Query the Greek_laws table for matching law
        query = """
        SELECT id, law_type, law_number, entry_year, fek_title, description, content_size
        FROM Greek_laws 
        WHERE law_number = ? AND entry_year = ?
        """
        
        cursor.execute(query, (ref['number'], ref['year']))
        matches = cursor.fetchall()
        
        if matches:
            for match in matches:
                matched_laws.append({
                    'reference': ref,
                    'law_id': match[0],
                    'law_type': match[1], 
                    'law_number': match[2],
                    'law_year': match[3],
                    'fek_title': match[4],
                    'description': match[5],
                    'content_size': match[6]
                })
    
    conn.close()
    return matched_laws

def test_law_detection():
    """Test the law detection on sample consultations"""
    db_path = '/mnt/data/AI4Deliberation/new_html_extraction/deliberation_data_gr_markdownify.db'
    
    print("Loading sample consultations...")
    consultations = get_sample_consultations(db_path, limit=10)
    
    print(f"Found {len(consultations)} consultation articles to analyze.\n")
    
    all_law_references = []
    articles_with_references = []
    
    for i, (cons_id, cons_title, art_id, art_title, art_content) in enumerate(consultations):
        # Find law references in article content
        law_refs = find_law_references_in_text(art_content)
        
        if law_refs:
            articles_with_references.append({
                'consultation_id': cons_id,
                'consultation_title': cons_title,
                'article_id': art_id,
                'article_title': art_title,
                'law_references': law_refs
            })
            all_law_references.extend(law_refs)
            
            print(f"Article {art_id} (Consultation {cons_id}):")
            print(f"  Title: {(art_title or 'No title')[:80]}...")
            print(f"  Found {len(law_refs)} law references:")
            for ref in law_refs:
                print(f"    - {ref['full_match']} (Law {ref['number']}/{ref['year']})")
            print()
    
    print(f"\nSummary:")
    print(f"- Analyzed {len(consultations)} articles")
    print(f"- Found law references in {len(articles_with_references)} articles")
    print(f"- Total law references found: {len(all_law_references)}")
    
    if all_law_references:
        print(f"\nLooking for matches in Greek_laws table...")
        matched_laws = find_matching_laws_in_db(all_law_references, db_path)
        
        print(f"Found {len(matched_laws)} matches in Greek_laws table:")
        for match in matched_laws:
            ref = match['reference']
            print(f"\n  Reference: {ref['full_match']} (Law {ref['number']}/{ref['year']})")
            print(f"  Matched Law: {match['law_type']} {match['law_number']}/{match['law_year']}")
            print(f"  FEK Title: {(match['fek_title'] or 'N/A')[:80]}...")
            print(f"  Content Size: {match['content_size']} chars")
    
    return articles_with_references, all_law_references, matched_laws if all_law_references else []

def test_regex_patterns():
    """Test the simplified regex on some sample texts"""
    print("Testing simplified regex patterns...\n")
    
    test_texts = [
        "Σύμφωνα με το ν. 4412/2016 για τις δημόσιες συμβάσεις",
        "Με βάση τον Ν. 4624/2019 περί ψηφιακής διακυβέρνησης",
        "Ο νόμος 4727/2020 προβλέπει νέες διατάξεις",
        "Σύμφωνα με τον νόμο 4808/2021 και τις τροποποιήσεις του",
        "Βάσει των διατάξεων του ν.δ. 123/2020", # This should NOT match (ν.δ.)
        "Εφαρμόζεται το ν. 1234/2023 από την ημερομηνία",
        "Text without any law references",
        "Multiple references: ν. 4412/2016 και Ν. 4624/2019 επίσης νόμου 4727/2020"
    ]
    
    pattern = re.compile(SIMPLIFIED_LAW_REGEX, re.IGNORECASE | re.VERBOSE)
    
    for i, text in enumerate(test_texts, 1):
        print(f"Test {i}: {text}")
        matches = find_law_references_in_text(text)
        if matches:
            print(f"  Found {len(matches)} matches:")
            for match in matches:
                print(f"    - {match['full_match']} → Law {match['number']}/{match['year']}")
        else:
            print("  No matches found")
        print()

if __name__ == '__main__':
    print("=" * 60)
    print("SIMPLIFIED LAW DETECTION TEST")
    print("=" * 60)
    
    # First test the regex patterns
    test_regex_patterns()
    
    print("=" * 60)
    print("TESTING ON CONSULTATION ARTICLES")
    print("=" * 60)
    
    # Then test on actual consultation data
    test_law_detection() 