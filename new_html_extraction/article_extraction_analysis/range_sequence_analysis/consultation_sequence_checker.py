#!/usr/bin/env python3
"""
Consultation‑level sequence integrity checker
===========================================

Fix 2025‑05‑28
--------------
* **BUG:** `cur.fetchone()` was called twice when fetching the consultation
  title, so the second call returned *None* → `TypeError: 'NoneType' object is
  not subscriptable`.
* **FIX:** store the single fetch in a variable and reuse it.

The rest of the logic is unchanged.
"""

import os
import sys
import csv
import json
import sqlite3
import logging
from typing import List, Dict, Any, Tuple

# ------------------------------------------------------------------
# 1️⃣  Runtime paths / imports
# ------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
GRANDPARENT_DIR = os.path.dirname(PARENT_DIR)

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from article_parser_utils import (
        _get_true_main_article_header_locations,
        find_all_article_mentions,
    )
except ImportError as exc:
    print("[FATAL] cannot import article_parser_utils –", exc, file=sys.stderr)
    sys.exit(1)

# ------------------------------------------------------------------
# 2️⃣  Config
# ------------------------------------------------------------------
DB_PATH             = os.path.join(GRANDPARENT_DIR, "deliberation_data_gr_markdownify.db")
ARTICLES_TABLE      = "articles"
CONSULTATIONS_TABLE = "consultations"
OUTPUT_CSV          = "consultation_sequence_report.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ------------------------------------------------------------------
# 3️⃣  Mention‑based gap filler (priority 1‑4)
# ------------------------------------------------------------------

def _fill_missing_with_mentions(text: str, need: List[int]) -> Tuple[List[int], List[int]]:
    if not need or not text:
        return [], need
    mentions = find_all_article_mentions(text)
    need_set, best = set(need), {}
    for m in mentions:
        n = m["parsed_details"].get("main_number")
        if n not in need_set:
            continue
        pr = 1 if m["is_start_of_line"] and not m["is_quoted"] else (
            2 if m["is_start_of_line"] else (3 if not m["is_quoted"] else 4)
        )
        incumbent = best.get(n)
        if incumbent is None or pr < incumbent["priority"]:
            best[n] = {**m, "priority": pr}
    found = sorted(best)
    return found, sorted(need_set - set(found))

# ------------------------------------------------------------------
# 4️⃣  Within‑article repair
# ------------------------------------------------------------------

def repair_article_sequence(content: str) -> List[int]:
    headers = _get_true_main_article_header_locations(content)
    seq = sorted({h["article_number"] for h in headers})
    if len(seq) < 2:
        return seq
    gaps = [n for a, b in zip(seq, seq[1:]) if b - a > 1 for n in range(a + 1, b)]
    if not gaps:
        return seq
    found, _ = _fill_missing_with_mentions(content, gaps)
    return sorted(set(seq).union(found))

# ------------------------------------------------------------------
# 5️⃣  Bridge repair between two consecutive articles
# ------------------------------------------------------------------

def bridge_sequences(seq_l: List[int], seq_r: List[int], text_l: str, text_r: str):
    if not seq_l or not seq_r:
        return seq_l, seq_r
    gap = list(range(max(seq_l) + 1, min(seq_r)))
    if not gap:
        return seq_l, seq_r
    found_l, remaining = _fill_missing_with_mentions(text_l, gap)
    found_r, remaining = _fill_missing_with_mentions(text_r, remaining)
    return sorted(set(seq_l).union(found_l)), sorted(set(seq_r).union(found_r))

# ------------------------------------------------------------------
# 6️⃣  Consultation processing
# ------------------------------------------------------------------

def analyse_consultation(cur: sqlite3.Cursor, cid: int) -> Dict[str, Any]:
    cur.execute(f"SELECT id, title, content FROM {ARTICLES_TABLE} WHERE consultation_id = ? ORDER BY id", (cid,))
    articles = cur.fetchall()
    if not articles:
        return {}

    cur.execute(f"SELECT title FROM {CONSULTATIONS_TABLE} WHERE id = ?", (cid,))
    title_row = cur.fetchone()
    cons_title = title_row[0] if title_row else "N/A"

    contents, refined_seqs = [], []
    for aid, atitle, acontent in articles:
        contents.append(acontent)
        refined_seqs.append(repair_article_sequence(acontent))

    for i in range(len(articles) - 1):
        id_curr, *_ = articles[i]
        id_next, *_ = articles[i + 1]
        if id_next - id_curr == 1:
            refined_seqs[i], refined_seqs[i + 1] = bridge_sequences(
                refined_seqs[i], refined_seqs[i + 1], contents[i], contents[i + 1]
            )

    def concat(seqs):
        return [n for seq in seqs for n in seq]

    initial_concat = concat([
        sorted({h["article_number"] for h in _get_true_main_article_header_locations(c)}) for c in contents
    ])
    refined_concat = concat(refined_seqs)

    def missing(nums: List[int]):
        if not nums:
            return []
        full = range(min(nums), max(nums) + 1)
        return [n for n in full if n not in nums]

    missing_init = missing(initial_concat)
    missing_after = missing(refined_concat)

    return {
        "consultation_id": cid,
        "consultation_title": cons_title,
        "initial_continuous_bool": not missing_init,
        "missing_numbers_initial": json.dumps(missing_init, ensure_ascii=False),
        "continuous_after_refinement_bool": not missing_after,
        "missing_numbers_after": json.dumps(missing_after, ensure_ascii=False),
        "missing_remaining_count": len(missing_after),
    }

# ------------------------------------------------------------------
# 7️⃣  Main driver
# ------------------------------------------------------------------

def main():
    if not os.path.exists(DB_PATH):
        logging.error("DB not found → %s", DB_PATH)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT consultation_id FROM {ARTICLES_TABLE}")
    cids = [r[0] for r in cur.fetchall()]
    logging.info("Total consultations: %d", len(cids))

    rows = []
    for idx, cid in enumerate(cids, 1):
        if idx % 50 == 0:
            logging.info("Processed %d / %d consultations", idx, len(cids))
        r = analyse_consultation(cur, cid)
        if r:
            rows.append(r)

    fields = [
        "consultation_id",
        "consultation_title",
        "initial_continuous_bool",
        "missing_numbers_initial",
        "continuous_after_refinement_bool",
        "missing_numbers_after",
        "missing_remaining_count",
    ]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=fields).writeheader()
        csv.DictWriter(fh, fieldnames=fields).writerows(rows)

    logging.info("Report saved → %s", OUTPUT_CSV)


if __name__ == "__main__":
    main()
