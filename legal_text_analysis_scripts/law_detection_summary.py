import re
import sqlite3
from collections import Counter

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

def summarize_law_detection():
    """Summarize law detection results"""
    db_path = '/mnt/data/AI4Deliberation/new_html_extraction/deliberation_data_gr_markdownify.db'
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get articles with content
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
    LIMIT 100
    """
    
    cursor.execute(query)
    consultations = cursor.fetchall()
    
    print(f"Analyzing {len(consultations)} consultation articles...")
    
    all_law_references = []
    articles_with_refs = 0
    unique_laws = set()
    
    for cons_id, cons_title, art_id, art_title, art_content in consultations:
        law_refs = find_law_references_in_text(art_content)
        
        if law_refs:
            articles_with_refs += 1
            for ref in law_refs:
                all_law_references.append(ref)
                unique_laws.add((ref['number'], ref['year']))
    
    print(f"\nSUMMARY:")
    print(f"- Articles analyzed: {len(consultations)}")
    print(f"- Articles with law references: {articles_with_refs}")
    print(f"- Total law references found: {len(all_law_references)}")
    print(f"- Unique laws referenced: {len(unique_laws)}")
    
    # Count most frequently referenced laws
    law_counter = Counter((ref['number'], ref['year']) for ref in all_law_references)
    print(f"\nMOST FREQUENTLY REFERENCED LAWS:")
    for (number, year), count in law_counter.most_common(10):
        print(f"  - Law {number}/{year}: {count} references")
    
    # Check how many are in our Greek_laws table
    matched_count = 0
    matched_laws = []
    
    for number, year in unique_laws:
        cursor.execute("""
        SELECT law_type, law_number, entry_year, fek_title, description 
        FROM Greek_laws 
        WHERE law_number = ? AND entry_year = ?
        """, (number, year))
        
        result = cursor.fetchone()
        if result:
            matched_count += 1
            matched_laws.append((number, year, result))
    
    print(f"\nMATCHING WITH GREEK_LAWS TABLE:")
    print(f"- Referenced laws found in Greek_laws table: {matched_count}/{len(unique_laws)} ({matched_count/len(unique_laws)*100:.1f}%)")
    
    if matched_laws:
        print(f"\nSAMPLE MATCHED LAWS:")
        for number, year, (law_type, law_number, entry_year, fek_title, description) in matched_laws[:10]:
            print(f"  - {law_type} {law_number}/{entry_year}")
            print(f"    FEK: {(fek_title or 'N/A')[:60]}...")
            print(f"    Description: {(description or 'N/A')[:60]}...")
            print()
    
    # Show some unmatched laws (laws referenced but not in our table)
    unmatched_laws = [law for law in unique_laws if not any(law[0] == m[0] and law[1] == m[1] for m in matched_laws)]
    if unmatched_laws:
        print(f"SAMPLE UNMATCHED LAWS (not in Greek_laws table):")
        for number, year in unmatched_laws[:10]:
            ref_count = law_counter[(number, year)]
            print(f"  - Law {number}/{year} ({ref_count} references)")
    
    conn.close()

def test_regex_only():
    """Test just the regex patterns"""
    print("TESTING SIMPLIFIED REGEX PATTERNS:")
    print("=" * 50)
    
    test_texts = [
        "Σύμφωνα με το ν. 4412/2016 για τις δημόσιες συμβάσεις",
        "Με βάση τον Ν. 4624/2019 περί ψηφιακής διακυβέρνησης", 
        "Ο νόμος 4727/2020 προβλέπει νέες διατάξεις",
        "Σύμφωνα με τον νόμο 4808/2021 και τις τροποποιήσεις του",
        "Βάσει των διατάξεων του ν.δ. 123/2020",  # Should NOT match
        "Εφαρμόζεται το ν. 1234/2023 από την ημερομηνία",
        "Text without any law references",
        "Multiple references: ν. 4412/2016 και Ν. 4624/2019 επίσης νόμου 4727/2020"
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"Test {i}: {text}")
        matches = find_law_references_in_text(text)
        if matches:
            print(f"  ✓ Found {len(matches)} matches:")
            for match in matches:
                print(f"    → {match['full_match']} (Law {match['number']}/{match['year']})")
        else:
            print("  ✗ No matches found")
        print()

if __name__ == '__main__':
    test_regex_only()
    print("\n" + "=" * 60)
    print("CONSULTATION ANALYSIS")
    print("=" * 60)
    summarize_law_detection() 