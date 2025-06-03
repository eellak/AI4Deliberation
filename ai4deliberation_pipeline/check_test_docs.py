#!/usr/bin/env python3

import sqlite3

conn = sqlite3.connect('deliberation_data_gr_fixed.db')
cursor = conn.cursor()

cursor.execute('SELECT id, content_cleaned IS NULL, LENGTH(content_cleaned), greek_percentage, english_percentage FROM documents WHERE id IN (3, 5, 6)')

print('Status of test documents:')
print('ID | Cleaned is NULL | Cleaned Length | Greek%  | English%')
print('-' * 55)

for row in cursor.fetchall():
    doc_id, is_null, cleaned_len, greek, english = row
    print(f'{doc_id:2d} | {str(is_null):15s} | {cleaned_len or 0:13d} | {greek or 0:6.1f}% | {english or 0:7.1f}%')

# Also check why the processor doesn't find these documents
print('\nChecking processor query...')
cursor.execute('''
SELECT id, content IS NOT NULL, content != '', content_cleaned IS NULL
FROM documents 
WHERE id IN (3, 5, 6)
''')

print('ID | Has Content | Non-Empty | Cleaned NULL | Should Process')
print('-' * 60)
for row in cursor.fetchall():
    doc_id, has_content, non_empty, cleaned_null = row
    should_process = has_content and non_empty and cleaned_null
    print(f'{doc_id:2d} | {str(has_content):11s} | {str(non_empty):9s} | {str(cleaned_null):12s} | {str(should_process):14s}')

conn.close() 