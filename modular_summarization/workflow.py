"""<100-line orchestrator for modular summarizer.

Usage::
    from modular_summarization.workflow import run_workflow
    result = run_workflow(consultation_id=123, dry_run=True)
"""
from __future__ import annotations

import json
from typing import List, Dict, Any, Optional
import logging
import re

from .logger_setup import init_logging
from .db_io import fetch_articles
from .advanced_parser import get_article_chunks
from .hierarchy_parser import BillHierarchy
from .compression import length_metrics, desired_tokens
from .prompts import get_prompt
from .retry import generate_with_retry

logger = logging.getLogger(__name__)

# initialise root logger on module import (could be moved to CLI entry)
init_logging()

__all__ = ["run_workflow"]

# optional utils for deeper article sequence checking
try:
    import article_parser_utils as _apu  # type: ignore
except ImportError:  # pragma: no cover
    _apu = None  # type: ignore

# dummy generator FN placeholder --------------------------------------------------

def _fake_llm_generate(prompt: str, max_tokens: int) -> str:  # noqa: D401
    """TEMP stand-in until LLM module integrated."""
    return f"<LLM output len≤{max_tokens} tokens for prompt: {prompt[:60]}…>"


# -------------------------------------------------------------------------------
# PUBLIC ENTRY
# -------------------------------------------------------------------------------

def run_workflow(
    consultation_id: int,
    *,
    article_id: Optional[int] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
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
    """
    logger.info("Starting workflow: consultation_id=%s article_id=%s dry=%s", consultation_id, article_id, dry_run)
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
    stage1_results: List[str] = []
    for ch in all_chunks:
        tok, words, _ = length_metrics(ch["content"])
        if words < 80:
            stage1_results.append(ch["content"])
            continue
        target_tokens = desired_tokens(tok)
        prompt = get_prompt("stage1_article").format(
            input_tokens=tok, input_words=words, target_tokens=target_tokens
        ) + "\n" + ch["content"]
        res = generate_with_retry(_fake_llm_generate, prompt, target_tokens)
        stage1_results.append(res.text)

    # TODO: pipeline Stage 2 & 3 (placeholder)
    return {"stage1": stage1_results}


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
