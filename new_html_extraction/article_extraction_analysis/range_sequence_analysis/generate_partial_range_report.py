#!/usr/bin/env python3
"""
Generate a CSV report for **every** article whose *title* declares a numeric
range – e.g. "(10‑12)" – regardless of whether the body initially contains
none, some, or all of those article headers.

Workflow per article
--------------------
1. Parse the range in the title → `title_expected_sequence`.
2. Detect *true* headers already present in the body → `initial_sequence`.
3. If `initial_sequence` is already perfect (covers the range) we simply note
   it and move on (still included in the CSV for completeness).
4. Otherwise, search for inline mentions with `find_all_article_mentions`, pick
   the best candidate for each missing number (priority 1‑4) and build
   `refined_sequence`.
5. Record whether the article is **perfect** after refinement and how many
   numbers are still missing.
6. For articles that gained at least one new number, reconstruct header/content
   chunks (headers kept *separate* from body) and store as JSON.

CSV columns
-----------
consultation_id,
consultation_url,
article_id,
article_title,
expected_sequence_from_title,
found_sequence_in_content_initial,
missing_articles_initial,
missing_articles_found_by_mentions_count,
refined_sequence_after_mentions,
missing_articles_remaining,
missing_articles_remaining_count,
perfect_after_refinement_bool,
article_content,
refined_article_chunks_json
"""

import os
import sys
import re
import csv
import json
import sqlite3
import logging
from typing import List, Dict, Any, Tuple

# ------------------------------------------------------------
# 1️⃣  Runtime paths & dynamic import
# ------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
GRANDPARENT_DIR = os.path.dirname(PARENT_DIR)

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from article_parser_utils import (
        _get_true_main_article_header_locations,
        find_all_article_mentions,
        reconstruct_article_chunks_with_prioritized_mentions,
    )
except ImportError as exc:
    print("[FATAL] cannot import article_parser_utils –", exc, file=sys.stderr)
    sys.exit(1)

# ------------------------------------------------------------
# 2️⃣  Config
# ------------------------------------------------------------
DB_PATH             = os.path.join(GRANDPARENT_DIR, "deliberation_data_gr_markdownify.db")
ARTICLES_TABLE      = "articles"
CONSULTATIONS_TABLE = "consultations"
OUTPUT_CSV          = "range_match_report.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ------------------------------------------------------------
# 3️⃣  Regex to detect numeric ranges in the title
# ------------------------------------------------------------
TITLE_RANGE_REGEX = re.compile(
    r"""\(\s*(?:
        (?:[ΑAΆÁ]ρθρ?ο?\s+)|        # άρθρο/Αρθρο
        (?:[ΑAΆÁ]ρθρα\s+)           # άρθρα/Αρθρα
    )?(\d{1,3})\s*[-\u2013\u2014]\s*(\d{1,3})\s*\)""",
    re.IGNORECASE | re.VERBOSE,
)

# ------------------------------------------------------------
# 4️⃣  Helpers
# ------------------------------------------------------------

def fetch_consultation_meta(cur: sqlite3.Cursor, cid: int) -> Dict[str, str]:
    cur.execute(f"SELECT title, url FROM {CONSULTATIONS_TABLE} WHERE id = ?", (cid,))
    row = cur.fetchone()
    return {"title": (row[0] if row else "N/A"), "url": (row[1] if row else "N/A")}


def parse_title_range(title: str) -> List[int]:
    m = TITLE_RANGE_REGEX.search(title or "")
    if not m:
        return []
    start, end = int(m.group(1)), int(m.group(2))
    return list(range(start, end + 1)) if start <= end else []


# ------------------------------------------------------------
# 5️⃣  Minimal re‑implementation of missing‑finder (priority logic)
# ------------------------------------------------------------

def _find_missing_via_mentions(text: str, target_numbers: List[int], have_numbers: List[int]) -> Tuple[List[int], List[dict]]:
    """Return (refined_sequence, chosen_mentions)."""
    missing = sorted(set(target_numbers) - set(have_numbers))
    if not text or not missing:
        return have_numbers, []

    mentions = find_all_article_mentions(text)
    candidate_map: Dict[int, dict] = {}
    for m in mentions:
        n = m["parsed_details"].get("main_number")
        if n is None or n not in missing:
            continue
        priority = 1 if m["is_start_of_line"] and not m["is_quoted"] else (
            2 if m["is_start_of_line"] else (3 if not m["is_quoted"] else 4)
        )
        best = candidate_map.get(n)
        if best is None or priority < best["priority"]:
            candidate_map[n] = {**m, "article_number": n, "priority": priority}

    chosen = list(candidate_map.values())
    refined_seq = sorted(set(have_numbers).union({m["article_number"] for m in chosen}))
    return refined_seq, chosen


# ------------------------------------------------------------
# 6️⃣  Reconstruct chunks (header separate)
# ------------------------------------------------------------

def _reconstruct_chunks(text: str, mentions: List[dict]):
    if not mentions:
        return None

    true_headers = _get_true_main_article_header_locations(text)
    main_delims = []
    for h in true_headers:
        raw_line, match_text = h.get("original_line_text", ""), h.get("match_text", "")
        if not raw_line or not match_text:
            continue
        offset = raw_line.find(match_text)
        main_delims.append({
            "line_num": h["line_index"] + 1,
            "parsed_header": h["parsed_header_details_copy"],
            "raw_header_line": match_text,
            "char_offset_in_original_line": max(offset, 0),
        })

    mapped_mentions = [{
        "line_number": m["line_index"] + 1,
        "char_offset_in_line": m["match_start_char_in_line"],
        "match_text": m["match_text"],
        "parsed_info": m["parsed_details"],
    } for m in mentions]

    return reconstruct_article_chunks_with_prioritized_mentions(text, main_delims, mapped_mentions)


# ------------------------------------------------------------
# 7️⃣  Per‑article processing
# ------------------------------------------------------------

def analyse_article(row: Tuple, cur: sqlite3.Cursor) -> Dict[str, Any] | None:
    art_id, cons_id, title, content = row
    title_seq = parse_title_range(title)
    if not title_seq:
        return None  # not in scope

    # true headers present initially
    initial_headers = _get_true_main_article_header_locations(content)
    initial_seq = sorted({h["article_number"] for h in initial_headers})
    missing_initial = sorted(set(title_seq) - set(initial_seq))

    # attempt refinement (even if missing_initial == []) to measure perfection
    refined_seq, chosen_mentions = _find_missing_via_mentions(content, title_seq, initial_seq)
    missing_remaining = sorted(set(title_seq) - set(refined_seq))

    refined_chunks = _reconstruct_chunks(content, chosen_mentions) if chosen_mentions else None

    cons_meta = fetch_consultation_meta(cur, cons_id)

    return {
        "consultation_id": cons_id,
        "consultation_url": cons_meta["url"],
        "article_id": art_id,
        "article_title": title,
        "expected_sequence_from_title": json.dumps(title_seq, ensure_ascii=False),
        "found_sequence_in_content_initial": json.dumps(initial_seq, ensure_ascii=False),
        "missing_articles_initial": json.dumps(missing_initial, ensure_ascii=False),
        "missing_articles_found_by_mentions_count": len(chosen_mentions),
        "refined_sequence_after_mentions": json.dumps(refined_seq, ensure_ascii=False),
        "missing_articles_remaining": json.dumps(missing_remaining, ensure_ascii=False),
        "missing_articles_remaining_count": len(missing_remaining),
        "perfect_after_refinement_bool": (len(missing_remaining) == 0),
        "article_content": content,
        "refined_article_chunks_json": json.dumps(refined_chunks, ensure_ascii=False) if refined_chunks else None,
    }


# ------------------------------------------------------------
# 8️⃣  Main driver
# ------------------------------------------------------------

def main():
    if not os.path.exists(DB_PATH):
        logging.error("Database not found at %s", DB_PATH)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(f"SELECT id, consultation_id, title, content FROM {ARTICLES_TABLE}")
    rows = cur.fetchall()
    logging.info("Fetched %d articles", len(rows))

    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, 1):
        if idx % 250 == 0:
            logging.info("Processed %d / %d", idx, len(rows))
        rec = analyse_article(row, cur)
        if rec:
            out.append(rec)

    logging.info("Total titles with ranges: %d", len(out))

    fieldnames = [
        "consultation_id",
        "consultation_url",
        "article_id",
        "article_title",
        "expected_sequence_from_title",
        "found_sequence_in_content_initial",
        "missing_articles_initial",
        "missing_articles_found_by_mentions_count",
        "refined_sequence_after_mentions",
        "missing_articles_remaining",
        "missing_articles_remaining_count",
        "perfect_after_refinement_bool",
        "article_content",
        "refined_article_chunks_json",
    ]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=fieldnames).writeheader()
        csv.DictWriter(fh, fieldnames=fieldnames).writerows(out)

    logging.info("CSV saved → %s", OUTPUT_CSV)


if __name__ == "__main__":
    main()
