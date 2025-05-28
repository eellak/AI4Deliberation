#!/usr/bin/env python3
"""
Consultation‑wide *Article Sequence Extractor*
============================================

Purpose
-------
End‑to‑end pipeline that, for **every consultation** that contains *any* sign
of an article sequence (either in the title range or detected headers in the
body), produces a **clean, duplication‑free JSON dump** of *every* recovered
article with its header **and** body.

Key features
------------
1. **Internal completion** – For each article, fill gaps by comparing against
   its *title* range (if present) plus mention search inside its own body.
2. **Bridge completion** – For every neighbouring pair of articles (id +1),
   fill numeric gaps between their max/min by scanning **both** bodies.
3. **De‑duplication** – When a bridge number is found, it is attached to the
   article in which the mention is discovered.  A global registry prevents
   the same header chunk from being emitted twice when analysing overlapping
   pairs `(A1,A2)`, `(A2,A3)`, …
4. **Optional pass‑through** – Articles **without** sequences can be emitted
   as a single block when `--include‑singletons` flag is provided.

Output
------
* **CSV**: One row per article chunk with columns:
    consultation_id,
    consultation_title,
    article_id,
    article_title,
    final_sequence_numbers (JSON list),
    source_of_completion   (internal | bridge | none),
    article_json           (header & content)

* **JSONL** (same base name) – each line is the `article_json` column for
  quick programmatic use.

Implementation notes (duplication guard)
---------------------------------------
* We keep a `seen_key = (consultation_id, article_number)` set.  When we emit
  a chunk for `article_number`, we mark it; subsequent pair analyses skip it.

* Bridge search attaches a found number **exclusively** to the article whose
  text contained the mention.  If it is somehow found in *both* articles, we
  prefer the left article to keep ordering natural.

* When reconstructing header/body blocks we use
  `reconstruct_article_chunks_with_prioritized_mentions` so each chunk has
  **exact** text boundaries (no overlap).

Run
---
```bash
python consultation_article_sequence_extractor.py  \
       --db /path/to/db.sqlite                     \
       --include-singletons                        
```

If `--include-singletons` is omitted (default) articles lacking any numeric
sequence are ignored.
"""
"""
Consultation-wide *Article Sequence Extractor*  – **bug‑fix revision**
---------------------------------------------------------------------
Fixes a `KeyError: 'title_line'` when reconstructing chunks: depending on the
version of `reconstruct_article_chunks_with_prioritized_mentions`, article
chunks may expose their header under `raw_header` and the body under
`content`, not `title_line` / `content_text`.

The update guards against both variants.
"""

import os, sys, csv, json, sqlite3, logging, argparse, re
from typing import List, Dict, Any, Tuple, Set

# ------------------------------------------------------------------
# CLI & logging
# ------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Extract de‑duplicated article chunks per consultation.")
parser.add_argument("--db", default="deliberation_data_gr_markdownify.db")
parser.add_argument("--outbase", default="consultation_article_dump")
parser.add_argument("--include-singletons", action="store_true")
args = parser.parse_args()
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

# ------------------------------------------------------------
DB_PATH = args.db
ARTICLES = "articles"
CONSULTATIONS = "consultations"

# ------------------------------------------------------------
TITLE_RANGE_RE = re.compile(r"\(\s*(\d{1,3})\s*[–\-]\s*(\d{1,3})\s*\)")


def title_range(title: str) -> List[int]:
    m = TITLE_RANGE_RE.search(title or "")
    if not m:
        return []
    a, b = int(m.group(1)), int(m.group(2))
    return list(range(a, b + 1)) if a <= b else []


def fill_missing(text: str, need: List[int]):
    if not need or not text:
        return [], need
    need_set, best = set(need), {}
    for m in find_all_article_mentions(text):
        n = m["parsed_details"].get("main_number")
        if n not in need_set:
            continue
        pr = 1 if m["is_start_of_line"] and not m["is_quoted"] else (2 if m["is_start_of_line"] else (3 if not m["is_quoted"] else 4))
        if n not in best or pr < best[n]["priority"]:
            best[n] = {**m, "priority": pr}
    found = sorted(best)
    return found, sorted(need_set - set(found))


def complete_internal(text: str, title: str):
    hdrs = _get_true_main_article_header_locations(text)
    seq = sorted({h["article_number"] for h in hdrs})
    target = title_range(title)
    missing_vs_title = sorted(set(target) - set(seq)) if target else []
    found_title, _ = fill_missing(text, missing_vs_title)
    seq = sorted(set(seq).union(found_title))
    gaps = [n for a, b in zip(seq, seq[1:]) if b - a > 1 for n in range(a + 1, b)]
    found_internal, _ = fill_missing(text, gaps)
    seq = sorted(set(seq).union(found_internal))
    return seq, ("internal" if (found_title or found_internal) else "none")


def bridge_numbers(seq_l, seq_r):
    if not seq_l or not seq_r:
        return []
    return list(range(max(seq_l) + 1, min(seq_r)))


def reconstruct_chunks(text: str, mentions):
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

# ------------------------------------------------------------
# main processing
# ------------------------------------------------------------
if not os.path.exists(DB_PATH):
    logging.error("DB missing: %s", DB_PATH)
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute(f"SELECT DISTINCT consultation_id FROM {ARTICLES}")
CIDS = [r[0] for r in cur.fetchall()]

csv_rows, seen_keys = [], set()
jsonl_path = f"{args.outbase}.jsonl"
with open(jsonl_path, "w", encoding="utf-8") as jsonl_fp:
    for cid in CIDS:
        cur.execute(f"SELECT id,title,content FROM {ARTICLES} WHERE consultation_id=? ORDER BY id", (cid,))
        arts = cur.fetchall()
        if not arts:
            continue
        cons_title = cur.execute(f"SELECT title FROM {CONSULTATIONS} WHERE id=?", (cid,)).fetchone()
        cons_title = cons_title[0] if cons_title else "N/A"

        contents = {aid: txt for aid, _, txt in arts}
        seqs, srcs = {}, {}
        for aid, atitle, atext in arts:
            seqs[aid], srcs[aid] = complete_internal(atext, atitle)
        # bridge
        extra_mentions = {aid: [] for aid, _, _ in arts}
        for (aid1, *_), (aid2, *_ ) in zip(arts, arts[1:]):
            if aid2 - aid1 != 1:
                continue
            gap = bridge_numbers(seqs[aid1], seqs[aid2])
            if not gap:
                continue
            f1, rem = fill_missing(contents[aid1], gap)
            f2, rem = fill_missing(contents[aid2], rem)
            if f1:
                for n in f1:
                    extra_mentions[aid1].append({"line_index":0,"match_start_char_in_line":0,"match_text":f"Άρθρο {n}","parsed_details":{"main_number":n}})
                seqs[aid1] = sorted(set(seqs[aid1]).union(f1))
            if f2:
                for n in f2:
                    extra_mentions[aid2].append({"line_index":0,"match_start_char_in_line":0,"match_text":f"Άρθρο {n}","parsed_details":{"main_number":n}})
                seqs[aid2] = sorted(set(seqs[aid2]).union(f2))

        # emit
        for aid, atitle, atext in arts:
            if not seqs[aid] and not args.include_singletons:
                continue
            chunks = reconstruct_chunks(atext, extra_mentions[aid])
            for ch in chunks:
                if ch["type"] != "article":
                    continue
                num = ch["article_number"]
                key = (cid, num)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                header = ch.get("title_line") or ch.get("raw_header") or ""
                body   = ch.get("content_text") or ch.get("content") or ""
                art_json = {"article_number":num,"header":header,"body":body}
                jsonl_fp.write(json.dumps(art_json, ensure_ascii=False)+"\n")
                csv_rows.append({
                    "consultation_id": cid,
                    "consultation_title": cons_title,
                    "article_id": aid,
                    "article_title": atitle,
                    "final_sequence_numbers": json.dumps(seqs[aid], ensure_ascii=False),
                    "source_of_completion": srcs[aid],
                    "article_json": json.dumps(art_json, ensure_ascii=False),
                })

# CSV
csv_path = f"{args.outbase}.csv"
with open(csv_path, "w", newline="", encoding="utf-8") as fh:
    fieldnames = ["consultation_id","consultation_title","article_id","article_title","final_sequence_numbers","source_of_completion","article_json"]
    w = csv.DictWriter(fh, fieldnames=fieldnames)
    w.writeheader(); w.writerows(csv_rows)
logging.info("CSV → %s  | JSONL → %s", csv_path, jsonl_path)
