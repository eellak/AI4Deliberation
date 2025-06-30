"""<100-line orchestrator for modular summarizer.

Usage::
    from modular_summarization.workflow import run_workflow
    result = run_workflow(consultation_id=123, dry_run=True)
"""
from __future__ import annotations

import json
from typing import List, Dict, Any, Optional, Callable, Set, Tuple
import logging
import re

from .logger_setup import init_logging
from .db_io import fetch_articles
from .advanced_parser import get_article_chunks
from .hierarchy_parser import BillHierarchy
from .compression import summarization_budget, length_metrics
from .prompts import get_prompt
from .validator import generate_plain_with_retry
from .validator import (
    generate_json_with_validation,
    validate_article_summary_output,
    extract_json,
    ValidationError,
)
from modular_summarization.law_utils import (
    article_modifies_law,
    extract_quoted_segments,
    find_law_references,
    is_skopos_article,
    is_antikeimeno_article,
)
from modular_summarization.llm import get_generator
from .trace import ReasoningTracer, TraceEntry
from . import config as cfg

logger = logging.getLogger(__name__)

# initialise root logger on module import (could be moved to CLI entry)
init_logging()

__all__ = ["run_workflow"]

# optional utils for deeper article sequence checking
try:
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    utils_dir = os.path.join(project_root, "utils")
    if utils_dir not in sys.path:
        sys.path.insert(0, utils_dir)
    import article_parser_utils as _apu  # type: ignore
except ImportError:  # pragma: no cover
    _apu = None  # type: ignore

# no more dummy generator; rely on llm.get_generator for stub or real

# -------------------------------------------------------------------------------
# PUBLIC ENTRY
# -------------------------------------------------------------------------------

def run_workflow(
    consultation_id: int,
    *,
    article_id: Optional[int] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
    generator_fn: Optional[Callable[[str, int], str]] = None,
    enable_trace: Optional[bool] = None,
    trace_output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Run summarization pipeline; returns structured result dict.

    Parameters
    ----------
    consultation_id : int
        Target consultation in the SQLite DB.
    article_id : int | None, optional
        Restrict to single article.
    dry_run : bool, optional
        If True, skip LLM calls and return Markdown hierarchy.
    db_path : str | None, optional
        SQLite path (overrides `config.DB_PATH`).
    generator_fn : Callable[[str, int], str] | None, optional
        Optional generator function to use for LLM calls.
    enable_trace : bool | None, optional
        Enable reasoning trace logging. If None, uses config.ENABLE_REASONING_TRACE.
    trace_output_dir : str | None, optional
        Directory for trace files. If None, uses config.TRACE_OUTPUT_DIR.
    """
    # Determine trace settings
    should_trace = enable_trace if enable_trace is not None else cfg.ENABLE_REASONING_TRACE
    
    logger.info("Starting workflow: consultation_id=%s article_id=%s dry=%s trace=%s", 
                consultation_id, article_id, dry_run, should_trace)
    
    # Initialize tracer if enabled and not in dry-run
    tracer = None
    if should_trace and not dry_run:
        tracer = ReasoningTracer(consultation_id, trace_output_dir)
        logger.info("Reasoning trace enabled: %s", tracer.trace_file_path)

    rows = fetch_articles(consultation_id, article_id=article_id, db_path=db_path or None)
    # 1. parse per-row chunks
    all_chunks: List[Dict[str, Any]] = []
    for r in rows:
        for ch in get_article_chunks(r["content"], r["title"]):
            ch["db_id"] = r["id"]
            all_chunks.append(ch)
    logger.info("Parsed %d chunks", len(all_chunks))

    # fast dry-run path ------------------------------------------------------
    if dry_run:
        # Build mapping of article id -> parsed chunks for text presentation
        chunk_map = {}
        for ch in all_chunks:
            chunk_map.setdefault(ch["db_id"], []).append(ch)

        # hierarchy build via section_parser titles + article content merge
        try:
            import section_parser.section_parser as sp
            title_rows = sp.parse_titles(db_path or config.DB_PATH, consultation_id)
            id_to_content = {r["id"]: r for r in rows}
            for tr in title_rows:
                art = id_to_content.get(tr["id"])
                tr["content"] = art["content"] if art else ""
            hierarchy = BillHierarchy.from_db_rows(title_rows)
        except Exception as e:
            logger.warning("section_parser parse failed: %s – falling back", e)
            hier_rows = [
                {"id": c["db_id"], "title": c["title_line"], "content": c["content"]}
                for c in all_chunks
            ]
            hierarchy = BillHierarchy.from_db_rows(hier_rows)

        # continuity checks -------------------------------------------------
        issues: List[str] = []
        try:
            cont_problems = sp.verify_continuity(title_rows)  # type: ignore[name-defined]
            issues.extend(cont_problems)
        except Exception as e:
            logger.warning("continuity verify failed: %s", e)

        # per-article internal sequence integrity using article_parser_utils
        if _apu and hasattr(_apu, "check_overall_article_sequence_integrity"):
            for r in rows:
                try:
                    seq_res = _apu.check_overall_article_sequence_integrity(r["content"])
                    if not seq_res.get("forms_single_continuous_sequence", True):
                        issues.append(
                            f"Article id {r['id']} internal numbering discontinuous ({seq_res.get('count_of_detected_articles', 0)} detected)"
                        )
                except Exception as exc:
                    logger.debug("sequence check failed for id %s: %s", r["id"], exc)

        # article id continuity (simple ascending + gaps)
        article_ids = []
        for p in hierarchy.parts:
            for ch in p.chapters:
                article_ids.extend(a.id for a in ch.articles)
            if hasattr(p, "misc_articles"):
                article_ids.extend(a.id for a in p.misc_articles)  # type: ignore[attr-defined]

        article_ids_sorted = sorted(article_ids)
        for prev, nxt in zip(article_ids_sorted, article_ids_sorted[1:]):
            if nxt <= prev:
                issues.append(f"Article id order anomaly: {nxt} follows {prev}")

        # NOTE: We intentionally no longer flag gaps ("missing" ids) because database IDs are
        # global across all consultations and therefore naturally non-contiguous within a single
        # consultation. The previous implementation was producing false positives (e.g. ids 29-38)
        # and confusing the dry-run output. Continuous numbering integrity is now handled using
        # the parsed article numbers in `parsed_nums` below.

        # parsed sub-article number continuity
        parsed_nums = sorted({ch["article_number"] for lst in chunk_map.values() for ch in lst if ch.get("article_number")})
        for prev, nxt in zip(parsed_nums, parsed_nums[1:]):
            if nxt != prev + 1:
                issues.append(f"Sub-article number jump: {prev} -> {nxt}")

        presentation_md = _build_dry_run_markdown(hierarchy)
        presentation_txt = _build_dry_run_text(hierarchy, chunk_map)

        # prepend issues summary to plain-text output
        if issues:
            header_lines = [
                "=== CONTINUITY ISSUES DETECTED ===",
                *[f"- {msg}" for msg in issues],
                "=" * 80,
                "",
            ]
            presentation_txt = "\n".join(header_lines) + presentation_txt
        return {"dry_run_markdown": presentation_md, "dry_run_text": presentation_txt, "continuity_issues": issues}

    # Stage 1 ---------------------------------------------------------------
    # Token budget for law-mod/new-provision JSON extraction
    CLASSIFIER_TOKEN_LIMIT = 512
    stage1_results: List[str] = []
    law_mod_results: List[Dict[str, Any]] = []
    law_new_results: List[Dict[str, Any]] = []
    intro_articles: List[Dict[str, Any]] = []  # Σκοπός / Αντικείμενο chunks for CSV

    _gen_fn = generator_fn or get_generator(dry_run=dry_run)

    # Track which intro types have been captured per Part (by first DB title)
    seen_intro: Set[Tuple[str, str]] = set()  # (part_name_from_db_title, intro_type)

    for ch in all_chunks:
        art_num = ch.get("article_number")
        content = ch["content"]
        law_refs = find_law_references(content)
        # Detect and store introductory Σκοπός / Αντικείμενο articles ----------------
        # Constraints:
        #   • Article 1  → Σκοπός
        #   • Article 2  → Αντικείμενο
        # Any other article numbers are ignored to avoid false positives.
        # We do the coarse filter here and rely on later Part/Chapter mapping in
        # generate_stage1_csvs for a final sanity-check.
        if art_num == 1 and is_skopos_article(ch):
            intro_articles.append({
                "article_id": ch.get("db_id"),
                "article_number": art_num,
                "type": "skopos",
                "raw_content": ch["content"],
            })
            continue  # no LLM processing needed for proper intro articles
        elif art_num == 2 and is_antikeimeno_article(ch):
            intro_articles.append({
                "article_id": ch.get("db_id"),
                "article_number": art_num,
                "type": "antikeimeno",
                "raw_content": ch["content"],
            })
            continue

        tok, words, _ = length_metrics(ch["content"])
        # Stage1 summarization kept for future use (unchanged logic)
        if words < 80:
            stage1_results.append(ch["content"])
        else:
            budget = summarization_budget(
                ch["content"],
                compression_ratio=0.10,
                min_token_limit=cfg.MAX_TOKENS_STAGE1,
            )
            prompt = get_prompt("stage1_article").format(**budget) + "\n" + ch["content"]
            out_text, plain_retries, _trunc = generate_plain_with_retry(
                prompt,
                budget["token_limit"],
                _gen_fn,
                max_retries=1,
            )
            stage1_results.append(out_text)

        # Binary classifier path -------------------------------------------------
        if article_modifies_law(content):
            # Determine law name and quoted changes
            law_refs = find_law_references(content)
            law_name = law_refs[0]["match"] if law_refs else "τον προηγούμενο νόμο"
            quoted_segments = [qs for qs in extract_quoted_segments(content) if len(qs.split()) >= 10]

            # Fallback to full chunk if no quotes detected (mark truncation)
            truncated_flag_global = False
            if not quoted_segments:
                words = content.split()
                fallback_text = " ".join(words[:900])
                quoted_segments = [fallback_text]
                truncated_flag_global = True

            # Iterate over each quoted change (or fallback segment)
            for quoted_change in quoted_segments:
                prompt_mod = get_prompt("law_mod_json").format(
                    law_name=law_name,
                    quoted_change=quoted_change,
                )

                tokens_in, *_ = length_metrics(quoted_change)
                token_limit = min(768, int(tokens_in * 1.3) + 128)

                try:
                    out_text, retries = generate_json_with_validation(
                        prompt_mod,
                        token_limit,
                        _gen_fn,
                        validate_article_summary_output,
                        max_retries=2,
                    )
                    parsed_json = extract_json(out_text)
                    summary_txt = (
                        parsed_json.get("summary", "") if isinstance(parsed_json, dict) else ""
                    )
                except ValidationError as exc:
                    out_text = exc.last_output or ""
                    retries = 2
                    summary_txt = ""

                # Log to trace if enabled
                if tracer:
                    tracer.log_entry(
                        TraceEntry(
                            article_id=ch.get("db_id"),
                            article_number=ch.get("article_number"),
                            classification="modifies",
                            prompt=prompt_mod,
                            raw_output=out_text,
                            parsed_output=summary_txt,
                            metadata={"retries": retries, "truncated": truncated_flag_global, "law_ref_missing": not law_refs},
                        )
                    )

                law_mod_results.append(
                    {
                        "article_id": ch.get("db_id"),
                        "article_number": ch.get("article_number"),
                        "classifier_decision": "modifies",
                        "truncated": truncated_flag_global,
                        "summary_text": summary_txt,
                        "raw_prompt": prompt_mod,
                        "raw_output": out_text,
                        "retries": retries,
                    }
                )
        else:
            # New provisions JSON extraction (single-field summary)
            prompt_new = get_prompt("law_new_json").format(article=content)

            tokens_in, *_ = length_metrics(content)
            new_token_limit = min(768, int(tokens_in * 1.3) + 128)

            try:
                new_res_text, new_retries = generate_json_with_validation(
                    prompt_new,
                    new_token_limit,
                    _gen_fn,
                    validate_article_summary_output,
                    max_retries=2,
                )
                parsed_json_new = extract_json(new_res_text)
                summary_new = (
                    parsed_json_new.get("summary", "") if isinstance(parsed_json_new, dict) else ""
                )
            except ValidationError as exc:
                new_res_text = exc.last_output or ""
                new_retries = 2
                summary_new = ""

            if tracer:
                tracer.log_entry(
                    TraceEntry(
                        article_id=ch.get("db_id"),
                        article_number=ch.get("article_number"),
                        classification="new_provision",
                        prompt=prompt_new,
                        raw_output=new_res_text,
                        parsed_output=summary_new,
                        metadata={"retries": new_retries},
                    )
                )

            law_new_results.append(
                {
                    "article_id": ch.get("db_id"),
                    "article_number": ch.get("article_number"),
                    "classifier_decision": "new_provision",
                    "truncated": False,
                    "summary_text": summary_new,
                    "raw_prompt": prompt_new,
                    "raw_output": new_res_text,
                    "retries": new_retries,
                }
            )

    # TODO: pipeline Stage 2 & 3 (placeholder)
    
    # Close tracer if it was created
    if tracer:
        tracer.close()
        logger.info("Reasoning trace written to: %s", tracer.trace_file_path)
    
    return {
        "stage1": stage1_results,
        "law_modifications": law_mod_results,
        "law_new_provisions": law_new_results,
        "intro_articles": intro_articles,
    }


# -------------------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------------------

def _build_dry_run_markdown(hierarchy: BillHierarchy) -> str:
    lines: List[str] = ["# Dry-Run Hierarchy View"]
    handled_ids = set()
    for p in hierarchy.parts:
        lines.append(f"\n## Μέρος {p.name}")
        # misc articles directly under part
        misc = getattr(p, "misc_articles", [])
        for art in misc:
            tok, words, _ = length_metrics(art.text)
            lines.append(f"* **Άρθρο {art.id}** – {words} words / ~{tok} tokens (no chapter)")
            handled_ids.add(art.id)
        for ch in p.chapters:
            lines.append(f"\n### Κεφάλαιο {ch.name}")
            for art in ch.articles:
                tok, words, _ = length_metrics(art.text)
                lines.append(f"* **Άρθρο {art.id}** – {words} words / ~{tok} tokens")
                handled_ids.add(art.id)

    # Uncategorised articles
    uncategorised = [
        art for part in hierarchy.parts for ch in part.chapters for art in ch.articles if art.id not in handled_ids
    ]
    if uncategorised:
        lines.append("\n## (Χωρίς Μέρος/Κεφάλαιο)")
        for art in uncategorised:
            tok, words, _ = length_metrics(art.text)
            lines.append(f"* **Άρθρο {art.id}** – {words} words / ~{tok} tokens")
    return "\n".join(lines)


def _build_dry_run_text(hierarchy: BillHierarchy, chunk_map) -> str:
    """Plain-text hierarchy view with indentation."""
    lines: List[str] = []
    handled_ids = set()
    for p in hierarchy.parts:
        lines.append(f"ΜΕΡΟΣ {p.name}")
        # Chapterless articles first
        misc = getattr(p, "misc_articles", [])
        for art in misc:
            _append_article(lines, art, chunk_map, indent=2)
            handled_ids.add(art.id)
        for ch in p.chapters:
            lines.append(f"  ΚΕΦΑΛΑΙΟ {ch.name}")
            for art in ch.articles:
                _append_article(lines, art, chunk_map, indent=4)
                handled_ids.add(art.id)

    # uncategorised
    uncategorised = [
        art for part in hierarchy.parts for ch in part.chapters for art in ch.articles if art.id not in handled_ids
    ]
    if uncategorised:
        lines.append("ΜΕΡΟΣ (Χωρίς) ")
        for art in uncategorised:
            _append_article(lines, art, chunk_map, indent=2)
    return "\n".join(lines)


def _append_article(lines: List[str], art, chunk_map, *, indent: int):
    tok, words, _ = length_metrics(art.text)
    prefix = " " * indent
    lines.append(f"{prefix}ΑΡΘΡΟ {art.id} – {words} words / ~{tok} tokens")
    lines.append(f"{prefix}  Τίτλος: {art.title.strip()}")
    # Full content indented 4 spaces deeper
    content_prefix = prefix + "    "
    content_lines = art.text.strip().splitlines() or [""]
    header_re = re.compile(r"^(?:#+\s*)?(?:\*\*)?\s*[ΆAΑάaα]?ρθρο", re.IGNORECASE)
    for idx, cl in enumerate(content_lines):
        # insert single-dash separator before subsequent sub-article headers inside content
        if idx > 0 and header_re.match(cl.strip()):
            lines.append(f"{content_prefix}{'-'*40}")
        lines.append(f"{content_prefix}{cl}")
    # list parsed sub-article sections
    chunks = chunk_map.get(art.id, [])
    total_chunks = len(chunks)
    for idx, ch in enumerate(chunks):
        tline = ch["title_line"].strip()
        c_words = len(ch["content"].split())
        lines.append(f"{content_prefix}• {tline} – {c_words} words")
        # add dashed separator AFTER each chunk except the last one
        if idx < total_chunks - 1:
            lines.append(f"{content_prefix}{'-'*40}")
    # double line separator after each article for readability
    sep_line = f"{prefix}{'='*80}"
    lines.append(sep_line)
    lines.append(sep_line)
