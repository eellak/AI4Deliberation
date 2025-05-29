#!/usr/bin/env python3
"""
Extended Consultation-wide Article Sequence Extractor
=====================================================

Modes
-----
1. --all
   Scan *all* consultations and emit a CSV of which features were used in each:
     feature1 = title-range completions
     feature2 = in-text start-of-line matches
     feature3 = internal gap completions
     feature4 = bridge gap completions

2. --consultation-id CID
   Dump all article chunks for the given CID into consultation_CID.txt
"""

import os, sys, csv, json, sqlite3, logging, argparse, re
from typing import List, Dict, Any, Tuple, Set

# ------------------------------------------------------------------
# CLI & logging
# ------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Extract article sequences or feature-usage summary.")
parser.add_argument("--db", default="deliberation_data_gr_markdownify.db",
                    help="Path to SQLite DB")
parser.add_argument("--outbase", default="consultation_article_dump",
                    help="Base name for outputs")
parser.add_argument("--include-singletons", action="store_true",
                    help="When dumping, include articles without any numbers")
parser.add_argument("--all", action="store_true",
                    help="Run on *all* consultations and emit features CSV")
parser.add_argument("--consultation-id", type=int,
                    help="ID of one consultation to dump to TXT")
args = parser.parse_args()

if not args.all and args.consultation_id is None:
    parser.error("Please specify either --all or --consultation-id CID")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ------------------------------------------------------------------
# Dynamic import of utils
# ------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from article_parser_utils import (
    _get_true_main_article_header_locations,
    find_all_article_mentions,
    reconstruct_article_chunks_with_prioritized_mentions,
)

# ------------------------------------------------------------------
# Regex & helpers
# ------------------------------------------------------------------
TITLE_RANGE_RE = re.compile(r"\(\s*(\d{1,3})\s*[–\-]\s*(\d{1,3})\s*\)")

def title_range(title: str) -> List[int]:
    """Extract [a..b] from title "(a–b)"."""
    m = TITLE_RANGE_RE.search(title or "")
    if not m:
        return []
    a, b = int(m.group(1)), int(m.group(2))
    return list(range(a, b+1)) if a <= b else []

def fill_missing(text: str, need: List[int]) -> Tuple[List[int], List[int], List[Dict[str,Any]]]:
    """
    Return (found_nums, still_missing, all_matches)
    where all_matches are the raw mention dicts selected.
    """
    if not need or not text:
        return [], need, []
    need_set = set(need)
    # best per number
    best: Dict[int, Dict[str,Any]] = {}
    for m in find_all_article_mentions(text):
        n = m["parsed_details"].get("main_number")
        if n not in need_set:
            continue
        # priority: 1 = start-of-line & not quoted, 2 = start-of-line,
        # 3 = not quoted, 4 = else
        pr = 1 if (m["is_start_of_line"] and not m["is_quoted"]) \
             else 2 if m["is_start_of_line"] \
             else 3 if not m["is_quoted"] else 4
        if n not in best or pr < best[n]["priority"]:
            best[n] = {**m, "priority": pr}
    found = sorted(best)
    remaining = sorted(need_set - set(found))
    matches = [best[n] for n in found]
    return found, remaining, matches

def complete_internal(text: str, title: str) -> Tuple[List[int], bool, bool]:
    """
    Returns (sequence, used_title_range, used_internal_gaps).
    """
    # get all real headers
    hdrs = _get_true_main_article_header_locations(text)
    seq = sorted({h["article_number"] for h in hdrs})
    # --- feature 1: title-range completion ---
    target = title_range(title)
    missing_vs_title = sorted(set(target) - set(seq)) if target else []
    found_title, _, matches_title = fill_missing(text, missing_vs_title)
    used_f1 = bool(found_title)
    seq = sorted(set(seq).union(found_title))

    # --- feature 3: internal gap completion ---
    # find gaps in seq
    gaps = [n for a,b in zip(seq, seq[1:]) if b - a > 1 for n in range(a+1, b)]
    found_int, _, matches_int = fill_missing(text, gaps)
    used_f3 = bool(found_int)
    seq = sorted(set(seq).union(found_int))

    return seq, used_f1, used_f3

def bridge_numbers(seq_l: List[int], seq_r: List[int]) -> List[int]:
    if not seq_l or not seq_r:
        return []
    return list(range(max(seq_l)+1, min(seq_r)))

def reconstruct_chunks(text: str, mentions: List[Dict[str,Any]]):
    """Same as in original script."""
    true_headers = _get_true_main_article_header_locations(text)
    main_delims = []
    for h in true_headers:
        raw, match = h["original_line_text"], h["match_text"]
        main_delims.append({
            "line_num": h["line_index"] + 1,
            "parsed_header": h["parsed_header_details_copy"],
            "raw_header_line": match,
            "char_offset_in_original_line": max(raw.find(match), 0),
        })
    mapped = [{
        "line_number": m["line_index"] + 1,
        "char_offset_in_line": m["match_start_char_in_line"],
        "match_text": m["match_text"],
        "parsed_info": m["parsed_details"],
    } for m in mentions]
    return reconstruct_article_chunks_with_prioritized_mentions(text, main_delims, mapped)

# ------------------------------------------------------------------
# DB init
# ------------------------------------------------------------------
if not os.path.exists(args.db):
    logging.error("DB missing: %s", args.db)
    sys.exit(1)
conn = sqlite3.connect(args.db)
cur = conn.cursor()

# ------------------------------------------------------------------
# MODE 1: --all → features CSV
# ------------------------------------------------------------------
if args.all:
    # fetch all consultation IDs
    cur.execute("SELECT DISTINCT consultation_id FROM articles")
    cids = [r[0] for r in cur.fetchall()]
    rows = []
    for cid in cids:
        # load articles for this consultation
        cur.execute("SELECT id, title, content FROM articles WHERE consultation_id=? ORDER BY id", (cid,))
        arts = cur.fetchall()
        if not arts:
            continue

        # feature flags for this consultation
        f1 = f2 = f3 = f4 = False

        # we'll need contents by id for bridging
        contents = {aid: txt for aid,_,txt in arts}

        # step A: per-article internal completion, and detect method2
        seqs: Dict[int,List[int]] = {}
        for aid, title, text in arts:
            # complete_internal gives f1 and f3
            seq, used1, used3 = complete_internal(text, title)
            seqs[aid] = seq
            if used1:
                f1 = True
            if used3:
                f3 = True

            # method2: ANY start-of-line & not quoted mention?
            for m in find_all_article_mentions(text):
                if m["is_start_of_line"] and not m["is_quoted"]:
                    f2 = True
                    break
            # early exit if all three are already True
            if f1 and f2 and f3:
                # but we still need to check f4 below
                pass

        # step B: bridge completion → feature4
        # for every adjacent pair
        for (aid1, *_), (aid2, *_) in zip(arts, arts[1:]):
            if aid2 - aid1 != 1:
                continue
            gap = bridge_numbers(seqs[aid1], seqs[aid2])
            if not gap:
                continue
            # try filling from left
            f1_left, rem_left, _ = fill_missing(contents[aid1], gap)
            # then from right
            _, rem2, _     = fill_missing(contents[aid2], rem_left)
            if f1_left or (len(rem_left) > len(rem2)):
                f4 = True
                break

        # only include if any feature fired
        if any((f1, f2, f3, f4)):
            rows.append({
                "consultation_id": cid,
                "feature1_title_range": int(f1),
                "feature2_line_begins":     int(f2),
                "feature3_internal_gaps":   int(f3),
                "feature4_bridge_gaps":     int(f4),
            })

    # write CSV
    csv_path = f"{args.outbase}_features.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "consultation_id",
            "feature1_title_range",
            "feature2_line_begins",
            "feature3_internal_gaps",
            "feature4_bridge_gaps"
        ])
        writer.writeheader()
        writer.writerows(rows)

    logging.info("Features summary → %s", csv_path)
    sys.exit(0)

# ------------------------------------------------------------------
# MODE 2: --consultation-id → dump TXT
# ------------------------------------------------------------------
cid = args.consultation_id
cur.execute("SELECT id, title, content FROM articles WHERE consultation_id=? ORDER BY id", (cid,))
arts = cur.fetchall()
if not arts:
    logging.error("No articles found for consultation %s", cid)
    sys.exit(1)

# re-run full pipeline for this one consultation
contents = {aid: txt for aid,_,txt in arts}
# first do internal
seqs, srcs = {}, {}
for aid, title, text in arts:
    seq, _, _ = complete_internal(text, title)
    seqs[aid] = seq
# now bridge → collect extra mentions
extra_mentions: Dict[int,List[Dict[str,Any]]] = {aid: [] for aid,_,_ in arts}
for (aid1, *_), (aid2, *_ ) in zip(arts, arts[1:]):
    if aid2 - aid1 != 1:
        continue
    gap = bridge_numbers(seqs[aid1], seqs[aid2])
    if not gap:
        continue
    f1l, rem, _ = fill_missing(contents[aid1], gap)
    if f1l:
        for n in f1l:
            extra_mentions[aid1].append({
                "line_index": 0,
                "match_start_char_in_line": 0,
                "match_text": f"Άρθρο {n}",
                "parsed_details": {"main_number": n}
            })
        seqs[aid1] = sorted(set(seqs[aid1]).union(f1l))
    f1r, rem2, _ = fill_missing(contents[aid2], rem)
    if f1r:
        for n in f1r:
            extra_mentions[aid2].append({
                "line_index": 0,
                "match_start_char_in_line": 0,
                "match_text": f"Άρθρο {n}",
                "parsed_details": {"main_number": n}
            })
        seqs[aid2] = sorted(set(seqs[aid2]).union(f1r))

# now reconstruct & dump to TXT
txt_path = f"consultation_{cid}.txt"
with open(txt_path, "w", encoding="utf-8") as out:
    for aid, _, text in arts:
        # skip singletons if flag off
        if not seqs[aid] and not args.include_singletons:
            continue
        chunks = reconstruct_chunks(text, extra_mentions[aid])
        for ch in chunks:
            if ch.get("type") != "article":
                continue
            num = ch["article_number"]
            header = ch.get("title_line") or ch.get("raw_header_line") or ""
            body   = ch.get("content_text") or ch.get("content") or ""
            out.write(f"--- Άρθρο {num} ---\n")
            out.write(header.strip() + "\n\n")
            out.write(body.strip() + "\n\n")

logging.info("Dumped consultation %s → %s", cid, txt_path)
