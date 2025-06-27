#!/usr/bin/env python3
"""Batch script to run the modular summarization *Stage 1* workflow for one or
multiple consultations and emit one CSV per consultation.

Fixes compared with the original version
----------------------------------------
1. **Robust handling of `parsed` objects** – only a real ``dict`` is treated as
   valid JSON.  Strings/lists now safely fall back to empty cells instead of
   crashing with ``AttributeError``.
2. **Safe string operations** – all ``.replace`` calls are guarded so they do
   not crash when the value is ``None``.
3. **Per‑consultation logging** – ``logging.basicConfig`` is executed once; a
   dedicated ``FileHandler`` is attached for each consultation so trace files
   are created reliably.
4. **Minor clean‑ups** – clarified variable names, ensured prompt/raw content
   never write ``None`` into the CSV, and added explicit flushing *and* a final
   ``f.flush()`` before closing.

Usage examples are unchanged; see the top‑level README in the repo or run
``python generate_stage1_csvs_fixed.py -h``.
"""
from __future__ import annotations

import argparse
import csv
from modular_summarization.validator import is_truncated_text
import csv, json, logging, os, re, sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

# ---------------------------------------------------------------------------
# Ensure project root available on PYTHONPATH
# ---------------------------------------------------------------------------
# Resolve repository root as the *parent* directory that contains this script
ROOT_DIR = Path(__file__).resolve().parents[1]  # e.g. .../AI4Deliberation

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Local imports *after* mutating sys.path
from modular_summarization.workflow import run_workflow  # noqa: E402
from modular_summarization.db_io import fetch_articles  # noqa: E402
from modular_summarization.hierarchy_parser import BillHierarchy  # noqa: E402
from modular_summarization.advanced_parser import get_article_chunks  # noqa: E402
from modular_summarization import config as cfg  # noqa: E402

# ---------------------------------------------------------------------------
# Regex helpers for fallback part / chapter detection when hierarchy fails
# ---------------------------------------------------------------------------
_PART_RE = re.compile(r"ΜΕΡΟΣ\s+([Α-Ω])['΄]?")
_CHAP_RE = re.compile(r"ΚΕΦΑΛΑΙΟ\s+([Α-Ω])['΄]?")

def _extract_part_chap(title: str) -> Tuple[str, str]:
    part = chap = ""
    if (m := _PART_RE.search(title)):
        part = f"{m.group(1)}'"
    if (m := _CHAP_RE.search(title)):
        chap = f"{m.group(1)}'"
    return part, chap

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

# Configure root logger once so libraries (openai etc.) also respect it.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

LOGGER = logging.getLogger("generate_stage1_csvs")

# ---------------------------------------------------------------------------
# Core per‑consultation logic (adapted from tests/run_consultation4.py)
# ---------------------------------------------------------------------------

def process_consultation(
     consultation_id: int,
     db_path: str,
     output_dir: Path,
     *,
     use_real_model: bool = False,
     article_id: int | None = None,
     enable_trace: bool = False,
     resume: bool = False,
    ) -> bool:
    """Run workflow for a single consultation and write its Stage 1 CSV.

    Returns ``True`` if workflow finished without raising and CSV written.
    """
    csv_path = output_dir / f"cons{consultation_id}_stage1.csv"

    # already-processed article IDs when resuming ---------------------------
    processed_ids: set[int] = set()
    if resume and csv_path.exists():
        with csv_path.open("r", newline="", encoding="utf-8") as _existing:
            rdr = csv.DictReader(_existing)
            if "article_id" in rdr.fieldnames:  # header check
                for row in rdr:
                    try:
                        processed_ids.add(int(row["article_id"]))
                    except (KeyError, ValueError):
                        continue
    trace_path = output_dir / f"cons{consultation_id}_trace.log"

    # ---------------------------------------------------------------------
    # Per‑consultation trace logger
    # ---------------------------------------------------------------------
    log = logging.getLogger(f"trace_{consultation_id}")
    log.propagate = False  # avoid double logging to root
    # wipe previous handlers if any (when re‑running in same process)
    log.handlers.clear()
    handler = logging.FileHandler(trace_path, mode="w", encoding="utf‑8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    dry_run_mode = not use_real_model
    log.debug("Starting process_consultation: id=%s dry=%s article_id=%s", consultation_id, dry_run_mode, article_id)

    # ---------------------------------------------------------------------
    # 1. Run main workflow (returns structured dict)
    # ---------------------------------------------------------------------
    log.info("Running modular_summarization.workflow.run_workflow(...) – real=%s", use_real_model)
    wf_start = datetime.now()
    result = run_workflow(
        consultation_id=consultation_id,
        article_id=article_id,
        dry_run=dry_run_mode,
        db_path=db_path,
        enable_trace=enable_trace,
        trace_output_dir=str(output_dir),
    )

    wf_dur = datetime.now() - wf_start
    log.info("Workflow returned in %.1fs", wf_dur.total_seconds())

    # ---------------------------------------------------------------------
    # 2. Build mapping helpers (Part / Chapter / ArticleNumber)
    # ---------------------------------------------------------------------
    rows = fetch_articles(consultation_id, article_id=article_id, db_path=db_path)

    # Hierarchy – first try full BillHierarchy from section parser titles
    part_map: dict[int, Tuple[str, str, str]] = {}
    try:
        sys.path.insert(0, str(ROOT_DIR))
        import section_parser.section_parser as sp  # type: ignore

        title_rows = sp.parse_titles(db_path, consultation_id)  # type: ignore[arg-type]
        id_to_content = {r["id"]: r for r in rows}
        for tr in title_rows:
            art = id_to_content.get(tr["id"])
            tr["content"] = art["content"] if art else ""
        hierarchy = BillHierarchy.from_db_rows(title_rows)
    except Exception:
        hier_rows = [{"id": r["id"], "title": r["title"], "content": r["content"]} for r in rows]
        hierarchy = BillHierarchy.from_db_rows(hier_rows)

    for p in hierarchy.parts:
        for ch in p.chapters:
            for a in ch.articles:
                part_map[a.id] = (p.name, ch.name, a.title)
        for a in getattr(p, "misc_articles", []):
            part_map[a.id] = (p.name, "", a.title)

    # Fallback via regex for any article IDs we could not map
    for r in rows:
        if r["id"] not in part_map:
            part, chap = _extract_part_chap(r["title"])
            part_map[r["id"]] = (part, chap, r["title"])

    # Map article_id → logical article_number (via first chunk)
    article_num_map: dict[int, int | None] = {}
    for r in rows:
        chunks = get_article_chunks(r["content"], r["title"])
        if chunks:
            article_num_map[r["id"]] = chunks[0].get("article_number")

    # ---------------------------------------------------------------------
    # 3. Write CSV
    # ---------------------------------------------------------------------
    mode = "a" if resume and csv_path.exists() else "w"
    with csv_path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Write header only if we opened in write mode
        if mode == "w":
            writer.writerow([
                "consultation_id",
                "article_id",
                "part",
                "chapter",
                "article_number",
                "classifier_decision",
                "status",
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
                "raw_content",
            ])

        row_counter = 0
        gen_is_stub = getattr(_gen_fn, "IS_STUB", False)

        # -------------------------------------------------------------
        # Internal helper – robust row writer
        # -------------------------------------------------------------
        def _write_row(
             
            article_id: int,
            decision: str,
            parsed: object | None,
            raw: str | None,
            prompt: str | None,
            raw_content: str | None = "",
        ) -> None:
            nonlocal row_counter, processed_ids
            # Skip any output from stub generator to avoid contaminating real CSV
            if gen_is_stub:
                return
            if article_id in processed_ids:
                return
            log.debug("Preparing CSV row for article_id=%s decision=%s", article_id, decision)
            part, chap, _ = part_map.get(article_id, ("", "", ""))
            art_num = article_num_map.get(article_id)

            is_dict = isinstance(parsed, dict)
            json_valid = bool(is_dict)

            # Determine validation / truncation status
            if decision in ("modifies", "new_provision"):
                status = "ok" if json_valid else "invalid"
            else:
                status = "truncated" if is_truncated_text(raw or "") else "ok"

            # convenient helper to pull value when we *know* parsed is a dict
            def _g(key: str, default: str = "") -> str:
                return parsed.get(key, default) if is_dict else default  # type: ignore[attr-defined]

            law_reference        = _g("law_reference")
            change_type          = _g("change_type")
            major_change_summary = _g("major_change_summary")
            article_title_json   = _g("article_title")
            provision_type       = _g("provision_type")
            core_provision_sum   = _g("core_provision_summary")

            key_themes_raw: list[str] | str = _g("key_themes", [])  # type: ignore[assignment]
            if isinstance(key_themes_raw, list):
                key_themes = "|".join(map(str, key_themes_raw))
            else:  # sometimes comes back as str already
                key_themes = str(key_themes_raw)

            # safe replacements – never call .replace on None
            raw_safe = (raw or "").replace("\n", "\\n")
            parsed_field = (
                json.dumps(parsed, ensure_ascii=False, separators=(",", ":")) if is_dict else str(parsed or "")
            )
            content_safe = (raw_content or "").replace("\n", " ")

            writer.writerow(
                [
                    consultation_id,
                    article_id,
                    part,
                    chap,
                    art_num,
                    decision,
                    status,
                    json_valid,
                    law_reference,
                    change_type,
                    major_change_summary,
                    article_title_json,
                    provision_type,
                    core_provision_sum,
                    key_themes,
                    raw_safe,
                    parsed_field,
                    content_safe,
                ]
            )

            # Mark as processed only if JSON is valid
            if json_valid and status == "ok":
                processed_ids.add(article_id)
            row_counter += 1
            if row_counter % 5 == 0:
                f.flush()
                os.fsync(f.fileno())

            # add prompt/output trace
            log.info("ID %s | Part %s | Chap %s | ArtNum %s | Decision %s", article_id, part, chap, art_num, decision)
            log.info("PROMPT:\n%s", prompt or "")
            log.info("OUTPUT:\n%s", raw or "")
            log.info("-" * 40)

        # Combine Stage‑1 results
        combined: List[tuple[int, str, dict]] = []
        for item in result.get("law_modifications", []):
            parsed_field = item.get("parsed")
            if isinstance(parsed_field, list):
                # multiple modifications – replicate item per entry
                for sub in parsed_field:
                    dup = item.copy()
                    dup["parsed"] = sub
                    combined.append((item["article_id"], "modifies", dup))
            else:
                combined.append((item["article_id"], "modifies", item))
        for item in result.get("law_new_provisions", []):
            parsed_field = item.get("parsed")
            if isinstance(parsed_field, list):
                for sub in parsed_field:
                    dup = item.copy()
                    dup["parsed"] = sub
                    combined.append((item["article_id"], "new_provision", dup))
            else:
                combined.append((item["article_id"], "new_provision", item))

        log.debug("Writing %d law_mod/new_provision rows", len(combined))
        for art_id, decision, item in sorted(combined, key=lambda t: t[0]):
            _write_row(
                art_id,
                decision,
                item.get("parsed"),
                item.get("llm_output"),
                item.get("prompt"),
            )

        log.debug("Writing %d intro rows", len(result.get("intro_articles", [])))
        # Introductory Σκοπός / Αντικείμενο rows – no LLM JSON
        for intro in sorted(result.get("intro_articles", []), key=lambda d: d["article_id"]):
            _write_row(
                intro["article_id"],
                intro["type"],
                parsed=None,
                raw="",
                prompt="",
                raw_content=intro.get("raw_content", ""),
            )

        # final flush to guarantee file integrity even if <5 rows remaining
        f.flush()
        os.fsync(f.fileno())

    LOGGER.info("CSV written: %s | Trace: %s", csv_path, trace_path)
    return True

# ---------------------------------------------------------------------------
# Argument parsing & runner
# ---------------------------------------------------------------------------

def _parse_id_args(ids: List[str]) -> List[int]:
    """Convert list of CLI id tokens to ``list[int]``. Supports ranges like ``1-5``."""
    out: set[int] = set()
    for tok in ids:
        if "-" in tok:
            start, end = map(int, tok.split("-", 1))
            out.update(range(start, end + 1))
        else:
            out.add(int(tok))
    return sorted(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Stage 1 CSVs for consultations")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--ids", nargs="+", help="Explicit list of consultation IDs or ranges (e.g. 1 3 5-7)")
    grp.add_argument("--range", nargs=2, metavar=("START", "END"), help="Inclusive start & end consultation IDs")

    parser.add_argument(
        "--db",
        default=cfg.DB_PATH,
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "tests" / "output"),
        help="Directory to write CSV & trace files",
    )
    parser.add_argument("--real", action="store_true", help="Use real LLM instead of dry‑run stub")
    parser.add_argument("--article-id", type=int, default=None, help="Process only this article ID (debug)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--resume", action="store_true", help="Append to existing CSV and skip already processed article IDs")
    parser.add_argument("--trace", action="store_true", help="Write detailed reasoning trace via ReasoningTracer")

    args = parser.parse_args()

    # Elevate logging level if --debug passed
    if getattr(args, "debug", False):
        logging.getLogger().setLevel(logging.DEBUG)
        LOGGER.setLevel(logging.DEBUG)
        LOGGER.debug("Debug logging enabled")

    # --- Determine consultations list -----------------------------------
    if args.ids:
        consultation_ids = _parse_id_args(args.ids)
    else:
        start, end = map(int, args.range)
        consultation_ids = list(range(start, end + 1))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"\n🚀 Generating CSVs for consultations {consultation_ids} (real={args.real})\nDB: {args.db}\nOutput dir: {output_dir}\n"
    )

    start_time = datetime.now()
    successes = 0
    for cid in consultation_ids:
        LOGGER.info("=== Processing consultation %s ===", cid)
        print(f"→ Consultation {cid}…")
        try:
            ok = process_consultation(
                cid,
                args.db,
                output_dir,
                use_real_model=args.real,
                article_id=args.article_id,
                enable_trace=args.trace,
            )
        except Exception as exc:
            LOGGER.exception("Failed consultation %s", cid)
            print(f"   💥 Failed: {exc}")
            ok = False
        successes += int(ok)

    total = len(consultation_ids)
    duration = datetime.now() - start_time
    print(f"\n🏁 Done in {duration.total_seconds():.1f}s. Success: {successes}/{total} | Fail: {total - successes}")


if __name__ == "__main__":
    main()
