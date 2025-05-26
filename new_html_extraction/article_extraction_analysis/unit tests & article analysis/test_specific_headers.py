#!/usr/bin/env python3
"""
Test script for validating specific observed article header patterns
using the parser from article_parser_utils.py.
"""

import sys
import os
import logging

# Ensure the parent directory is in sys.path to allow direct import
# of article_parser_utils if this script is run directly and they are siblings.
# current_dir = os.path.dirname(os.path.abspath(__file__))
# parent_dir = os.path.dirname(current_dir) # This would be new_html_extraction
# if parent_dir not in sys.path:
#     sys.path.insert(0, parent_dir)
# If AI4Deliberation is the root for python new_html_extraction/..., then this might be needed:
# project_root = os.path.abspath(os.path.join(current_dir, "../../")) # Goes up to AI4Deliberation
# if project_root not in sys.path:
#      sys.path.insert(0, project_root)

# Assuming article_parser_utils.py is in the same directory or PYTHONPATH is set up
try:
    from article_parser_utils import parse_article_header, ARTICLE_HEADER_REGEX
except ImportError:
    print("ERROR: Could not import from article_parser_utils.")
    print("Ensure article_parser_utils.py is in the same directory or PYTHONPATH is correctly set.")
    sys.exit(1)

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(asctime)s: %(message)s')

# List of specific header strings to test, with expected match status
# and optional checks for matched data.
observed_headers_with_expectations = [
    {"line": "Άρθρο 1", "should_match": True, "desc": "Simple case"},
    {"line": "  Άρθρο 1  ", "should_match": True, "desc": "Leading/trailing spaces"},
    {"line": "* Άρθρο 1", "should_match": True, "desc": "List marker *"},
    {"line": "- Άρθρο 1", "should_match": True, "desc": "List marker -"},
    {"line": "### Άρθρο 3", "should_match": True, "desc": "Heading marker ###"},
    {"line": "# Άρθρο 3", "should_match": True, "desc": "Heading marker #"},
    {"line": "«Άρθρο 1»", "should_match": False, "desc": "Quoted (handled by higher logic)"},
    {"line": "Άρθρο 1.", "should_match": True, "desc": "Trailing dot"},
    {"line": "Άρθρο 1:", "should_match": True, "desc": "Trailing colon"},
    {"line": "Άρθρο πρώτο", "should_match": False, "desc": "Greek word numeral (not in digit regex)"},
    {"line": "Άρθρο 2 παρ. 1", "should_match": True, "desc": "Paragraph ID", "checks": {"main_number": 2, "paragraph_id": "1", "alpha_suffix": None}},
    {"line": "Άρθρο48 παρ. 1", "should_match": True, "desc": "No space before number, with paragraph", "checks": {"main_number": 48, "paragraph_id": "1", "alpha_suffix": None}},
    {"line": "   Άρθρο 123   ", "should_match": True, "desc": "Spaces around and number"},
    {"line": "Άρθρα 245 – 250", "should_match": True, "desc": "Plural, en-dash range"},
    {"line": "Άρθρα 245 – 250 (Καταργούνται)", "should_match": True, "desc": "Plural, en-dash range, trailing text"},
    {"line": "Άρθρα 266-267", "should_match": True, "desc": "Plural, hyphen range"},
    {"line": "Άρθρα 266-267 (καταργούνται)", "should_match": True, "desc": "Plural, hyphen range, trailing text"},
    {"line": "άρθρα 10 - 12", "should_match": True, "desc": "Lowercase plural, hyphen range"},
    {"line": "**Άρθρο** **1**", "should_match": True, "desc": "Emphasis around keyword and number"},
    {"line": "**Άρθρο** **1**.", "should_match": True, "desc": "Emphasis with trailing dot"},
    {"line": "* **Άρθρο 1**", "should_match": True, "desc": "List marker with emphasis"},
    {"line": "Άρ**θρ**ο 1", "should_match": False, "desc": "Malformed internal emphasis in keyword"},
    {"line": "### **Άρθρ****o** **71**", "should_match": True, "desc": "Complex emphasis internal (Latin o)", "checks": {"main_number": 71}},
    {"line": "### **Άρθρ****ο** **71**", "should_match": True, "desc": "Complex emphasis internal (Greek ο)", "checks": {"main_number": 71}},
    {"line": "Άρθρο 1****18", "should_match": True, "desc": "Starred number", "checks": {"main_number": 118, "raw_number": "1****18"}},
    {"line": "Άρθρο 1Α", "should_match": True, "desc": "Alpha suffix, no space", "checks": {"main_number": 1, "alpha_suffix": "Α"}},
    {"line": "Άρθρο 1Α.", "should_match": True, "desc": "Alpha suffix, no space, trailing dot", "checks": {"main_number": 1, "alpha_suffix": "Α"}},
    {"line": "Άρθρο 12 ΣΤ", "should_match": True, "desc": "Alpha suffix with space", "checks": {"main_number": 12, "alpha_suffix": "ΣΤ"}},
    {"line": "Άρθρο 12 παρ. 3", "should_match": True, "desc": "Paragraph ID", "checks": {"main_number": 12, "paragraph_id": "3", "alpha_suffix": None}},
    {"line": "Άρθρο 12 παρ. 3 εδ. α", "should_match": True, "desc": "Paragraph ID with trailing text", "checks": {"main_number": 12, "paragraph_id": "3"}},
    {"line": "Άρθρο 100-102", "should_match": True, "desc": "Digit range"},
    {"line": "Κεφάλαιο Α - Άρθρο 1", "should_match": False, "desc": "Not at start of line"},
    {"line": "ΚΕΦΑΛΑΙΟ Α Άρθρο 1", "should_match": False, "desc": "Not at start of line (all caps preamble)"},
    {"line": "ΚΕΦΑΛΑΙΟ Α.\\nΆρθρο 1", "should_match": True, "desc": "Multi-line, second line test", "part_to_test": 1, "checks": {"main_number": 1}}, # Index of part after split
    {"line": "Άρθρο Α", "should_match": False, "desc": "Greek Alpha as number (not supported by digit regex)"},
    {"line": "Άρθρο", "should_match": False, "desc": "Keyword, no number"},
    {"line": "ΑΡΘΡΟ 1", "should_match": False, "desc": "Uppercase ARTHRO (case-sensitive mismatch)"},
    {"line": "άρθρο 1", "should_match": False, "desc": "Lowercase arthro singular (case-sensitive mismatch, regex is [ΆΑ]ρθρ)"},
    {"line": " Άρθρο Χ", "should_match": False, "desc": "Latin X as number (not digit)"},
    {"line": " * **Άρθρο X**", "should_match": False, "desc": "List with Latin X (not digit)"},
]

def run_tests():
    print(f"Testing with ARTICLE_HEADER_REGEX: {ARTICLE_HEADER_REGEX.pattern}\n")
    total_tests = len(observed_headers_with_expectations)
    passed_count = 0
    
    for i, test_spec in enumerate(observed_headers_with_expectations):
        header_line = test_spec["line"]
        should_match = test_spec["should_match"]
        description = test_spec["desc"]
        custom_checks = test_spec.get("checks")
        part_to_test_idx = test_spec.get("part_to_test")

        print(f"--- Test {i+1}/{total_tests}: {description} ---")
        
        actual_test_line = header_line

        # +++ DEBUG FOR TEST 34 +++
        if "Multi-line, second line test" in description:
            print(f"    DEBUG_TEST_34: header_line = {repr(header_line)}")
            print(f"    DEBUG_TEST_34: part_to_test_idx = {part_to_test_idx}")
            condition_check_debug = "\\n" in header_line # Check for literal backslash-n
            print(f"    DEBUG_TEST_34: '\\\\n' in header_line = {condition_check_debug}")
        # +++ END DEBUG +++

        if part_to_test_idx is not None and "\\n" in header_line: # Check for literal \\n
            line_parts = header_line.split("\\n") # Split by literal \\n
            if part_to_test_idx < len(line_parts):
                actual_test_line = line_parts[part_to_test_idx]
            print(f"Original multi-line: {repr(header_line)}")
            print(f"Testing line part [{part_to_test_idx}]: '{actual_test_line}'")
        else:
            print(f"Testing full line: '{actual_test_line}'")

        stripped_line = actual_test_line.strip()
        logging.debug(f"DEBUG: Testing stripped_line: '{stripped_line}' (repr: {repr(stripped_line)})")
        parsed_result = parse_article_header(stripped_line)
        
        case_passed = False
        if parsed_result and should_match:
            logging.info(f"  MATCHED (as expected): '{stripped_line}'")
            parsed_result.pop('match_obj', None) # For cleaner logging if we print it
            # Perform custom checks if any
            custom_checks_passed = True
            if custom_checks:
                for key, expected_value in custom_checks.items():
                    actual_value = parsed_result.get(key)
                    if actual_value != expected_value:
                        logging.warning(f"    CHECK FAILED for '{key}': Expected '{expected_value}', Got '{actual_value}'. Result: {parsed_result}")
                        custom_checks_passed = False
                        break 
                if custom_checks_passed:
                    logging.info(f"    All custom checks PASSED. Details: {parsed_result}")
            case_passed = custom_checks_passed
        elif not parsed_result and not should_match:
            logging.info(f"  NO MATCH (as expected): '{stripped_line}'")
            case_passed = True
        elif parsed_result and not should_match:
            logging.warning(f"  UNEXPECTED MATCH: '{stripped_line}' was matched, but shouldn't have been. Result: {parsed_result}")
            case_passed = False
        elif not parsed_result and should_match:
            logging.warning(f"  FAILED TO MATCH: '{stripped_line}' should have matched, but didn't.")
            case_passed = False
        
        if case_passed:
            passed_count += 1
            print(f"  RESULT: PASS")
        else:
            print(f"  RESULT: FAIL")
        print("---")

    print("\n--- Summary ---")
    print(f"Total tests defined: {total_tests}")
    print(f"Passed: {passed_count}/{total_tests}")
    print(f"Failed: {total_tests - passed_count}/{total_tests}")
    
    if (total_tests - passed_count) > 0:
        print("\nReview WARNING/FAILURE messages above for details on failed test cases.")
    else:
        print("\nAll tests passed successfully!")

if __name__ == "__main__":
    run_tests() 