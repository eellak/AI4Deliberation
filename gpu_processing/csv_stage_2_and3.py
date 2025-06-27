#!/usr/bin/env python3
"""Batch aggregator for Stage-2 (ΚΕΦΑΛΑΙΟ) & Stage-3 (ΜΕΡΟΣ).

Reads the authoritative Stage-1 CSVs (``consN_stage1.csv``) that already exist,
invokes an LLM (real or stub) via the *modular_summarization* helpers, and
writes:
    • ``consN_stage2.csv``   – one row per (part, chapter)
    • ``consN_stage3.csv``   – one row per part
    • ``consN_final_summary.txt`` – concatenated ordered part summaries
    • ``consN_stage23_trace.log`` – full prompt/output trace

The script is idempotent: re-running will overwrite previous outputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from types import SimpleNamespace
from pathlib import Path
from collections import defaultdict, OrderedDict, Counter
from typing import Dict, List, Tuple
import re
import unicodedata

# ---------------------------------------------------------------------------
# Greek numeral conversion helpers
# ---------------------------------------------------------------------------
_GREEK_DIGITS = {
    "Α": 1, "Β": 2, "Γ": 3, "Δ": 4, "Ε": 5,
    "Ϛ": 6, "ΣΤ": 6, "Ζ": 7, "Η": 8, "Θ": 9
}
_GREEK_TENS = {"Ι": 10, "Κ": 20, "Λ": 30, "Μ": 40, "Ν": 50, "Ξ": 60, "Ο": 70, "Π": 80, "ϟ": 90}
_GREEK_HUNDS = {"Ρ": 100, "Σ": 200, "Τ": 300, "Υ": 400, "Φ": 500, "Χ": 600, "Ψ": 700, "Ω": 800}
_SINGLE_VALUES = {**_GREEK_DIGITS, **_GREEK_TENS, **_GREEK_HUNDS}


def _strip_accents(label: str) -> str:
    nfkd = unicodedata.normalize("NFD", label)
    return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn").upper().strip("΄'`·. ")


def greek_numeral_to_int(label: str) -> int:
    if not label:
        return 0
    txt = _strip_accents(label)
    total, idx = 0, 0
    while idx < len(txt):
        if txt[idx : idx + 2] == "ΣΤ":
            total += 6
            idx += 2
            continue
        val = _SINGLE_VALUES.get(txt[idx])
        if val:
            total += val
        idx += 1
    return total


def greek_numeral_sort_key(label: str) -> Tuple[int, str]:
    return greek_numeral_to_int(label), label

# ---------------------------------------------------------------------------
# Ensure project root on PYTHONPATH so `modular_summarization` imports resolve
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
import sys  # stdlib; placed here to avoid circular
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Public helpers
from modular_summarization.stage23_helpers_v2 import (
    build_bullet_line,
    build_chapter_prompt,
    build_part_prompt,
    parse_chapter_summary,
    parse_part_summary,
    greek_numeral_sort_key,
)
from modular_summarization.stage3_expanded import generate_part_summary
from modular_summarization.validator import (
    generate_json_with_validation,
    validate_chapter_summary_output,
    ValidationError,
)
# from modular_summarization.retry import generate_with_retry  # legacy
from modular_summarization.llm import get_generator
from modular_summarization.logger_setup import init_logging
from modular_summarization.prompts import get_prompt, CITIZEN_POLISH_PROMPT


# Initialise logging once; default INFO, changed to DEBUG via CLI
init_logging()
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core processing helpers
# ---------------------------------------------------------------------------

def _write_trace(fp, header: str, prompt: str, output: str) -> None:
    fp.write(f"=== {header} ===\n")
    fp.write("PROMPT:\n")
    fp.write(prompt)
    fp.write("\nOUTPUT:\n")
    fp.write(output)
    fp.write("\n\n---\n\n")
    fp.flush()


def _load_stage1_rows(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _derive_structures(rows: List[Dict[str, str]]):
    """Return (chapter_bullets, intro_lines, chapter_order).

    * chapter_bullets: mapping (part, chapter) -> list of bullet strings (ordered)
    * intro_lines: mapping part -> [skopos_line?, antikeimeno_line?]
    * chapter_order: mapping (part, chapter) -> article_number list (for sorting)  
      (helps to keep chapter order when writing Stage-2 CSV)
    """
    chapter_bullets: Dict[Tuple[str, str], List[Tuple[int, str]]] = defaultdict(list)
    intro_lines: Dict[str, List[str]] = defaultdict(list)

    for row in rows:
        part, chap = row["part"], row["chapter"]
        key = (part, chap)
        art_num_raw = row.get("article_number") or "0"
        try:
            art_num = int(art_num_raw)
        except ValueError:
            art_num = 0

        decision = row["classifier_decision"]
        if decision in {"skopos", "antikeimeno"}:
            txt = (row.get("raw_content", "") or "").strip()
            if txt:
                intro_lines[part].append(txt)
            continue

        bullet = build_bullet_line(row)
        if bullet:
            chapter_bullets[key].append((art_num, bullet))

    # sort bullet lists by article number
    final_bullets: Dict[Tuple[str, str], List[str]] = {}
    for key, lst in chapter_bullets.items():
        final_bullets[key] = [b for _, b in sorted(lst)]

    return final_bullets, intro_lines



# ---------------------------------------------------------------------------
# Polishing helper
# ---------------------------------------------------------------------------

def _polish_summary(text: str, part: str, generator_fn):
    """Single-stage citizen-style polishing for a Stage-3 summary.

    Returns
    -------
    tuple[str, str, str]
        clean_text – the polished `summary_text` (falls back to original),
        prompt_used – the prompt sent to the LLM,
        raw_output – the raw LLM response (for trace logging).
    """
    # Lazy import to avoid circular deps & heavy cost at startup.
    from modular_summarization.stage3_expanded import extract_json_from_text  # type: ignore

    if not text.strip():
        return "", "", ""

    prompt = CITIZEN_POLISH_PROMPT.replace("{part_name}", f"ΜΕΡΟΣ {part}") + "\n" + text.strip()
    tok_lim = int(len(text.split()) * 5) + 400  # generous budget to allow reasoning
    raw_out = generator_fn(prompt, tok_lim)

    clean_text: str = ""
    try:
        payload = json.loads(extract_json_from_text(raw_out))
        clean_text = (payload.get("summary_text") or "").strip()
    except Exception:
        clean_text = ""

    if not clean_text:
        clean_text = text.strip()

    return clean_text, prompt, raw_out

# ---------------------------------------------------------------------------
# Law modification analysis helper
# ---------------------------------------------------------------------------

def generate_part_modifications_summary(stage1_rows: List[Dict[str, str]], part: str) -> str:
    """Generate a brief Greek summary of law modifications for a specific part."""
    # Filter rows for this part that modify laws
    part_modifying_rows = [
        row for row in stage1_rows 
        if row.get('part') == part and row.get('classifier_decision') == 'modifies'
    ]
    
    if not part_modifying_rows:
        return ""
    
    # Group by law reference
    law_refs = defaultdict(list)
    
    for row in part_modifying_rows:
        law_ref = row.get('law_reference', '').strip()
        change_type = row.get('change_type', '').strip()
        
        if law_ref and law_ref != 'nan' and law_ref != '':
            law_refs[law_ref].append({
                'type': change_type,
                'article': row.get('article_number', '')
            })
    
    if not law_refs:
        return ""
    
    # Build summary - one line per law
    summary_lines = []
    
    # Sort laws by number of modifications (descending)
    sorted_laws = sorted(law_refs.items(), key=lambda x: len(x[1]), reverse=True)
    
    for law, mods in sorted_laws:
        # Count modification types for this law
        law_mod_types = Counter(mod['type'] for mod in mods)
        
        # Build the modification types part
        type_parts = []
        if 'αντικαθίσταται' in law_mod_types:
            count = law_mod_types['αντικαθίσταται']
            type_parts.append(f"{count} {'αντικατάσταση' if count == 1 else 'αντικαταστάσεις'}")
        if 'τροποποιείται' in law_mod_types:
            count = law_mod_types['τροποποιείται']
            type_parts.append(f"{count} {'τροποποίηση' if count == 1 else 'τροποποιήσεις'}")
        if 'προστίθεται' in law_mod_types:
            count = law_mod_types['προστίθεται']
            type_parts.append(f"{count} {'προσθήκη' if count == 1 else 'προσθήκες'}")
        if 'συμπληρώνεται' in law_mod_types:
            count = law_mod_types['συμπληρώνεται']
            type_parts.append(f"{count} {'συμπλήρωση' if count == 1 else 'συμπληρώσεις'}")
        if 'καταργείται' in law_mod_types:
            count = law_mod_types['καταργείται']
            type_parts.append(f"{count} {'κατάργηση' if count == 1 else 'καταργήσεις'}")
        if 'διαγράφεται' in law_mod_types:
            count = law_mod_types['διαγράφεται']
            type_parts.append(f"{count} {'διαγραφή' if count == 1 else 'διαγραφές'}")
        
        # Format the line
        num_changes = len(mods)
        if num_changes == 1:
            change_word = "αλλαγή"
        else:
            change_word = "αλλαγές"
        
        if type_parts:
            # Include breakdown of modification types
            type_str = ', '.join(type_parts)
            summary_lines.append(f"{num_changes} {change_word} του {law} ({type_str}).")
        else:
            # Simple format without breakdown
            summary_lines.append(f"{num_changes} {change_word} του {law}.")
    
    return '\n'.join(summary_lines)

# ---------------------------------------------------------------------------
# Final summary export helper
# ---------------------------------------------------------------------------

def _export_final_from_stage3(stage3_csv: Path, final_txt: Path, source_column: str, stage1_csv: Path = None) -> None:
    """Write consN_final_summary.txt using given column from Stage-3 CSV with optional law modifications."""
    if not stage3_csv.exists():
        return
    with stage3_csv.open(newline="", encoding="utf-8") as f_in:
        rows = list(csv.DictReader(f_in))

    # Load stage1 data if available for law modification summaries
    stage1_rows = []
    if stage1_csv and stage1_csv.exists():
        with stage1_csv.open(newline="", encoding="utf-8") as f1:
            stage1_rows = list(csv.DictReader(f1))

    rows_sorted = sorted(rows, key=lambda r: greek_numeral_sort_key(r["part"]))
    with final_txt.open("w", encoding="utf-8") as f_out:
        for row in rows_sorted:
            part = row['part']
            text = (row.get(source_column) or row.get("summary_text") or "").strip()
            if not text:
                continue
            
            f_out.write(f"ΜΕΡΟΣ {part}:\n")
            
            # Add law modifications summary if we have stage1 data
            if stage1_rows:
                mod_summary = generate_part_modifications_summary(stage1_rows, part)
                if mod_summary:
                    f_out.write(f"\nΑλλαγές:\n{mod_summary}\n")
            
            # Add summary sub-header
            f_out.write(f"\nΠερίληψη:\n{text}\n\n")

# ---------------------------------------------------------------------------
# Main per-consultation processing
# ---------------------------------------------------------------------------

def process_consultation(
    consultation_id: int,
    csv_dir: Path,
    out_dir: Path,
    generator_fn,
    max_retries: int = 2,
    stage3_only: bool = False,
    polish: bool = False,
    polish_only: bool = False,
    final_source: str = "raw",
):
    log.info("Processing consultation %s", consultation_id)
    if polish_only:
        # Polishing only mode – load existing Stage-3 CSV and enrich *with* reasoning trace
        stage3_csv = out_dir / f"cons{consultation_id}_stage3.csv"
        if not stage3_csv.exists():
            raise FileNotFoundError(stage3_csv)

        trace_log = out_dir / f"cons{consultation_id}_stage23_trace.log"
        polish_trace_log = out_dir / f"cons{consultation_id}_polish_trace.log"
        final_txt = out_dir / f"cons{consultation_id}_final_summary.txt"

        # Read all rows first -------------------------------------------------
        with stage3_csv.open(newline="", encoding="utf-8") as f_in:
            reader = csv.DictReader(f_in)
            rows: list[dict] = list(reader)
            fieldnames = reader.fieldnames or []

        # Ensure new column exists
        if "citizen_summary_text" not in fieldnames:
            fieldnames.append("citizen_summary_text")

        # Open CSV (rewrite) and dedicated polish trace (fresh write) --------
        with stage3_csv.open("w", newline="", encoding="utf-8") as f_out, polish_trace_log.open("w", encoding="utf-8") as trace_fp:
            writer = csv.DictWriter(f_out, fieldnames=fieldnames)
            writer.writeheader()

            for row in rows:
                # Clear previous polished value and re-polish every time
                polished, p_prompt, p_raw = _polish_summary(row.get("summary_text", ""), row.get("part", ""), generator_fn)
                # Record reasoning trace for each attempt (helps debugging)
                _write_trace(trace_fp, f"POLISH {row.get('part', 'NA')}", p_prompt, p_raw)
                row["citizen_summary_text"] = polished
                writer.writerow(row)

        # Regenerate final summary after polishing
        source_col = "citizen_summary_text" if final_source == "polished" else "summary_text"
        csv_stage1 = csv_dir / f"cons{consultation_id}_stage1.csv"
        _export_final_from_stage3(stage3_csv, final_txt, source_col, csv_stage1)

        log.info("Polishing only mode complete for consultation %s (polish trace written to %s)", consultation_id, polish_trace_log)
        return

    csv_stage1 = csv_dir / f"cons{consultation_id}_stage1.csv"
    rows = _load_stage1_rows(csv_stage1)

    chapter_bullets, intro_lines = _derive_structures(rows)

    # Prepare output paths
    stage2_csv   = out_dir / f"cons{consultation_id}_stage2.csv"
    stage3_csv   = out_dir / f"cons{consultation_id}_stage3.csv"
    final_txt    = out_dir / f"cons{consultation_id}_final_summary.txt"
    trace_log    = out_dir / f"cons{consultation_id}_stage23_trace.log"
    polish_trace_log = out_dir / f"cons{consultation_id}_polish_trace.log"

    out_dir.mkdir(parents=True, exist_ok=True)

    with trace_log.open("w", encoding="utf-8") as trace_fp, polish_trace_log.open("w", encoding="utf-8") as polish_fp:
        # -------------------------- Stage 2 ---------------------------------
        if not stage3_only:
            with stage2_csv.open("w", newline="", encoding="utf-8") as f2:
                w2 = csv.writer(f2)
                w2.writerow([
                    "consultation_id",
                    "part",
                    "chapter",
                    "summary_text",
                    "raw_prompt",
                    "raw_output",
                    "retries",
                ])

                for (part, chap), bullets in sorted(
                    chapter_bullets.items(),
                    key=lambda kv: (
                        greek_numeral_sort_key(kv[0][0])[0],  # part numeric
                        greek_numeral_sort_key(kv[0][1])[0],  # chapter numeric
                    ),
                ):
                    if not bullets:
                        continue
                    prompt, tok_lim = build_chapter_prompt(bullets)

                    # Use retry logic *and* benefit from LMFE schema enforcement.
                    try:
                        gen_text, retries = generate_json_with_validation(
                            prompt,
                            tok_lim,
                            generator_fn,
                            validate_chapter_summary_output,
                            max_retries=2,
                        )
                    except ValidationError as exc:
                        LOGGER.warning("ValidationError on chapter %s/%s – salvaging last output", part, chap)
                        gen_text = exc.last_output or ""
                        retries = 2
                    class _Result:  # mimic SimpleNamespace used elsewhere
                        def __init__(self, text, retries):
                            self.text = text
                            self.retries = retries
                    gen_res = _Result(gen_text, retries)
                    summary = parse_chapter_summary(gen_res.text) or ""

                    w2.writerow([
                        consultation_id,
                        part,
                        chap,
                        summary,
                        prompt,
                        gen_res.text,
                        gen_res.retries,
                    ])
                    _write_trace(trace_fp, f"Stage-2 {part}/{chap}", prompt, gen_res.text)

        # -------------------------- Stage 3 ---------------------------------
        # Load chapter summaries (either newly written or pre-existing)
        if not stage2_csv.exists():
            raise FileNotFoundError(stage2_csv)  # ensure Stage-2 CSV exists
        part_summaries: Dict[str, List[str]] = defaultdict(list)
        with stage2_csv.open(newline="", encoding="utf-8") as f2_in:
            for r in csv.DictReader(f2_in):
                part = r["part"]
                summ = r["summary_text"]
                if summ.strip():
                    part_summaries[part].append(summ.strip())

        with stage3_csv.open("w", newline="", encoding="utf-8") as f3:
            w3 = csv.writer(f3)
            w3.writerow([
                "consultation_id",
                "part",
                "summary_text",
                "citizen_summary_text",
                "raw_prompt",
                "raw_output",
                "retries",
                "narrative_plan_json",
            ])

            ordered_parts = sorted(part_summaries.keys(), key=greek_numeral_sort_key)
            final_lines: List[str] = []
            for part in ordered_parts:
                intro = intro_lines.get(part, [])
                chap_summs = part_summaries[part]
                
                log.info(f"Processing part {part} with {len(chap_summs)} chapters")
                log.debug(f"Chapter summaries: {chap_summs[:2]}{'...' if len(chap_summs) > 2 else ''}")
                log.debug(f"Intro lines: {intro if intro else 'None'}")
                
                # Use the new two-stage narrative summarization process
                log.info(f"Running expanded Stage 3 summarization for part {part}")
                import traceback
                from modular_summarization.stage3_expanded import extract_json_from_text

                try:
                    if not chap_summs:
                        log.warning(f"No chapter summaries found for part {part}, cannot proceed with narrative planning")
                        raise ValueError(f"No chapter summaries for part {part}")

                    # Wrap the real generator so we can capture every prompt/output
                    trace_records = []

                    def tracing_gen(prompt: str, max_tokens: int):
                        out = generator_fn(prompt, max_tokens)
                        # Determine header before appending (so len==current index)
                        idx_local = len(trace_records)
                        header = (
                            f"Stage-3 {part} PLAN" if idx_local == 0 else
                            f"Stage-3 {part} BEAT {idx_local-1}"
                        )
                        _write_trace(trace_fp, header, prompt, out)
                        trace_records.append((prompt, out))
                        return out

                    # Run the full Stage-3 workflow
                    log.debug("Calling generate_part_summary for complete Stage-3 workflow")
                    summary = generate_part_summary(chap_summs, intro, tracing_gen)
                    log.info(f"Successfully generated part summary: {len(summary)} chars")

                    # Narrative-plan JSON is the first LLM output (planning step)
                    narrative_plan_json = ""
                    if trace_records:
                        try:
                            narrative_plan_json = extract_json_from_text(trace_records[0][1])
                        except Exception:
                            narrative_plan_json = ""

                    result = SimpleNamespace(text=summary, retries=0)

                    # Write every prompt/output pair to the trace file
                    for idx, (pp, out) in enumerate(trace_records):
                        header = f"Stage-3 {part} PLAN" if idx == 0 else f"Stage-3 {part} BEAT {idx-1}"
                        _write_trace(trace_fp, header, pp, out)

                    trace_prompt = trace_records[0][0] if trace_records else "(No prompt recorded)"

                except Exception as e:
                    log.error(f"Error in Stage 3 expanded workflow: {e}")
                    log.error(f"Exception details: {traceback.format_exc()}")
                    log.warning("Falling back to legacy one-shot Stage 3 summarization")

                    # Write ALL collected Stage-3 prompts/outputs (invalid)
                    if trace_records:
                        for idx, (pp, out) in enumerate(trace_records):
                            header = (
                                f"Stage-3 {part} PLAN (INVALID)" if idx == 0 else
                                f"Stage-3 {part} RETRY {idx}"  # retries start at 1
                            )
                            _write_trace(trace_fp, header, pp, out)

                    # Build and run the legacy summariser ------------------
                    prompt, tok_lim = build_part_prompt(intro, chap_summs)
                    log.debug(f"Using legacy prompt with token limit {tok_lim}")
                    _txt = generator_fn(prompt, tok_lim)
                    result = SimpleNamespace(text=_txt, retries=0)
                    summary = parse_part_summary(result.text) or ""
                    log.info(f"Generated legacy summary: {len(summary)} chars")
                    narrative_plan_json = ""
                    trace_prompt = prompt
                    _write_trace(trace_fp, f"Stage-3 {part} LEGACY", prompt, result.text)

                # Optional polishing
                citizen_summary_text = ""
                if polish and summary.strip():
                    citizen_summary_text, polish_prompt, polish_raw = _polish_summary(summary, part, generator_fn)
                    _write_trace(polish_fp, f"POLISH {part}", polish_prompt, polish_raw)

                w3.writerow([
                    consultation_id,
                    part,
                    summary,
                    citizen_summary_text,
                    trace_prompt,
                    result.text,
                    result.retries,
                    narrative_plan_json,
                ])

                use_text = citizen_summary_text if (final_source == "polished" and citizen_summary_text.strip()) else summary
                if use_text:
                    final_lines.append(f"ΜΕΡΟΣ {part}:\n{use_text}\n")

        # -------------------------- Final aggregation -----------------------
        # Instead of writing directly, use the enhanced export function
        _export_final_from_stage3(stage3_csv, final_txt, source_column='summary_text' if final_source == 'raw' else 'citizen_summary_text', stage1_csv=csv_stage1)

    log.info("Consultation %s done", consultation_id)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description="Generate Stage-2/3 summaries from Stage-1 CSVs")
    p.add_argument("--ids", nargs="*", type=int, help="Consultation IDs, e.g. 1 2 3", default=[])
    p.add_argument("--range", nargs=2, type=int, metavar=("START", "END"), help="Inclusive range of consultation IDs")
    p.add_argument("--csv-dir", default="tests/output", help="Directory containing consN_stage1.csv")
    p.add_argument("--output-dir", default="tests/output", help="Write Stage-2/3 outputs here")
    p.add_argument("--real", action="store_true", help="Use real model instead of stub")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--polish", action="store_true", help="Run polishing after Stage 3 summarization")
    p.add_argument("--polish-only", action="store_true", help="Run polishing only on existing Stage 3 CSVs")
    p.add_argument("--stage3-only", action="store_true", help="Skip Stage-2 generation and only run Stage-3 using existing Stage-2 CSVs")
    p.add_argument("--final-source", choices=["raw", "polished"], help="Column to use when building consN_final_summary.txt (default: uses 'polished' when polishing is enabled, otherwise 'raw')")
    p.add_argument("--export-final-only", action="store_true", help="Just rebuild consN_final_summary.txt from existing Stage-3 CSVs without any LLM calls")
    return p.parse_args()


def _main():
    args = _parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    ids: List[int] = args.ids[:]

    # ----------------------------------------------
    # Only export final summaries then exit
    # ----------------------------------------------
    if args.export_final_only:
        if not ids and not args.range:
            raise SystemExit("--export-final-only requires --ids or --range")
        csv_dir = Path(args.csv_dir)
        out_dir = Path(args.output_dir)
        if args.final_source is None:
            source_col = "citizen_summary_text"
        else:
            source_col = "citizen_summary_text" if args.final_source == "polished" else "summary_text"
        if args.range and len(args.range) == 2:
            ids.extend(list(range(args.range[0], args.range[1] + 1)))
        for cid in ids:
            stage3_csv = out_dir / f"cons{cid}_stage3.csv"
            final_txt = out_dir / f"cons{cid}_final_summary.txt"
            csv_stage1 = csv_dir / f"cons{cid}_stage1.csv"
            _export_final_from_stage3(stage3_csv, final_txt, source_col, csv_stage1)
            print(f"Exported {final_txt}")
        return
    if args.range and len(args.range) == 2:
        ids.extend(list(range(args.range[0], args.range[1] + 1)))
    if not ids:
        raise SystemExit("No consultation IDs provided")

    csv_dir = Path(args.csv_dir)
    out_dir = Path(args.output_dir)

    # Decide which column to use for the final summary
    if args.final_source is None:
        final_source = "polished" if (args.polish or args.polish_only) else "raw"
    else:
        final_source = args.final_source

    generator_fn = get_generator(dry_run=not args.real)

    for cid in ids:
        process_consultation(
            cid,
            csv_dir,
            out_dir,
            generator_fn,
            stage3_only=args.stage3_only,
            polish=args.polish,
            polish_only=args.polish_only,
            final_source=final_source,
        )


if __name__ == "__main__":
    _main()
