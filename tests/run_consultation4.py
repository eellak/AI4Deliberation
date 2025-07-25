import csv
import json
import logging
import re
from pathlib import Path
import sys
import os
import argparse

# Ensure project root is on PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from modular_summarization.workflow import run_workflow
from modular_summarization.db_io import fetch_articles
from modular_summarization.hierarchy_parser import BillHierarchy
from modular_summarization.advanced_parser import get_article_chunks
from modular_summarization.law_utils import article_modifies_law

OUTPUT_DIR = ROOT_DIR / "tests" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TRACE_PATH = OUTPUT_DIR / "cons4_trace.log"
CSV_PATH = OUTPUT_DIR / "cons4_results.csv"

logging.basicConfig(filename=TRACE_PATH, level=logging.INFO, format="%(message)s")
log = logging.getLogger("trace")

CONSULTATION_ID = 4
DB_PATH = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"

# ---------------------------------------------------------------------------
# Helper regex for fallback extraction of part/chapter from title lines
# ---------------------------------------------------------------------------
_PART_RE = re.compile(r"ΜΕΡΟΣ\s+([Α-Ω])['΄]?")
_CHAP_RE = re.compile(r"ΚΕΦΑΛΑΙΟ\s+([Α-Ω])['΄]?")

def _extract_part_chap(title: str):
    part = None
    chap = None
    m = _PART_RE.search(title)
    if m:
        part = m.group(1) + "'"
    m = _CHAP_RE.search(title)
    if m:
        chap = m.group(1) + "'"
    return part or "", chap or ""

# 1. Run workflow (uses fake LLM unless --real)
parser = argparse.ArgumentParser()
parser.add_argument("--real", action="store_true", help="Use real Gemma 3 model for generation")
parser.add_argument("--article-id", type=int, default=None, help="Run only this article id (optional)")
args = parser.parse_args()

# Determine dry_run flag for workflow
dry_run_mode = not args.real
art_id = args.article_id

# Run workflow – rely on modular_summarization.llm for generator selection
result = run_workflow(
    consultation_id=CONSULTATION_ID,
    article_id=art_id,
    dry_run=dry_run_mode,
    db_path=DB_PATH,
)

# 2. Fetch raw rows + build hierarchy for context
rows = fetch_articles(CONSULTATION_ID, article_id=art_id, db_path=DB_PATH)
# ensure content joined for BillHierarchy
try:
    import section_parser.section_parser as sp
    title_rows = sp.parse_titles(DB_PATH, CONSULTATION_ID)  # type: ignore[arg-type]
    id_to_content = {r["id"]: r for r in rows}
    for tr in title_rows:
        art = id_to_content.get(tr["id"])
        tr["content"] = art["content"] if art else ""
    hierarchy = BillHierarchy.from_db_rows(title_rows)
except Exception:
    hier_rows = [
        {"id": r["id"], "title": r["title"], "content": r["content"]}
        for r in rows
    ]
    hierarchy = BillHierarchy.from_db_rows(hier_rows)

# Map article ID => (part, chapter)
part_map = {}
for p in hierarchy.parts:
    for ch in p.chapters:
        for a in ch.articles:
            part_map[a.id] = (p.name, ch.name, a.title)
    for a in getattr(p, "misc_articles", []):
        part_map[a.id] = (p.name, "", a.title)

# Fallback: ensure every article_id has part_map; if missing, extract from its own title
for r in rows:
    if r["id"] not in part_map:
        part, chap = _extract_part_chap(r["title"])
        part_map[r["id"]] = (part, chap, r["title"])

# Build mapping of article_id -> article_number via advanced_parser
article_num_map = {}
for r in rows:
    chunks = get_article_chunks(r["content"], r["title"])
    for ch in chunks:
        article_num_map[r["id"]] = ch.get("article_number")
        break  # first chunk number

# Build CSV
with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "consultation_id",
        "part",
        "chapter",
        "article_number",
        "classifier_decision",
        "json_valid",
        "law_reference",
        "change_type",
        "major_change_summary",
        "article_title_json",
        "provision_type",
        "core_provision_summary",
        "key_themes",
        "llm_output_raw",
        "parsed_json",
    ])

    # Helper to write rows
    def _write_row(article_id, decision, parsed, raw, prompt):
        part, chap, _title = part_map.get(article_id, ("", "", ""))
        art_num = article_num_map.get(article_id)
        json_valid = parsed is not None
        # Extract JSON fields with defaults
        law_reference = parsed.get("law_reference", "") if parsed else ""
        change_type = parsed.get("change_type", "") if parsed else ""
        major_change_summary = parsed.get("major_change_summary", "") if parsed else ""
        article_title_json = parsed.get("article_title", "") if parsed else ""
        provision_type = parsed.get("provision_type", "") if parsed else ""
        core_provision_summary = parsed.get("core_provision_summary", "") if parsed else ""
        key_themes = "|".join(parsed.get("key_themes", [])) if (parsed and isinstance(parsed.get("key_themes", []), list)) else ""

        writer.writerow([
            CONSULTATION_ID,
            part,
            chap,
            art_num,
            decision,
            json_valid,
            law_reference,
            change_type,
            major_change_summary,
            article_title_json,
            provision_type,
            core_provision_summary,
            key_themes,
            raw.replace("\n", "\\n"),
            json.dumps(parsed, ensure_ascii=False, separators=(",", ":")) if parsed else "",
        ])
        # log reasoning trace
        log.info("ID %s | Part %s | Chap %s | ArtNum %s | Decision %s", article_id, part, chap, art_num, decision)
        log.info("PROMPT:\n%s", prompt)
        log.info("OUTPUT:\n%s", raw)
        log.info("-"*40)

    # Collect all result items then sort by article_id to maintain natural order
    combined = []
    for item in result.get("law_modifications", []):
        combined.append((item["article_id"], "modifies", item))
    for item in result.get("law_new_provisions", []):
        combined.append((item["article_id"], "new_provision", item))

    for art_id, decision, item in sorted(combined, key=lambda t: t[0]):
        _write_row(art_id, decision, item["parsed"], item["llm_output"], item.get("prompt", ""))

print(f"Trace written to {TRACE_PATH}\nCSV written to {CSV_PATH}")
