"""Clean, self-contained helpers for Stage-2 (ΚΕΦΑΛΑΙΟ) and Stage-3 (ΜΕΡΟΣ)
aggregation.

This module supersedes the earlier *stage23_helpers.py* which became hard to
maintain after experimental edits.  It purposefully re-implements only the
functions required by the orchestrator and Stage-3 expanded workflow while
keeping the same public API so that downstream code can switch imports with a
single line change.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Dict, List, Optional, Tuple, Union, Any
from pathlib import Path

from .prompts import get_prompt
from .law_utils import get_summary
from .law_types import NarrativePlan, PlanningInput, SynthesisInput

__all__ = [
    "greek_numeral_to_int",
    "greek_numeral_sort_key",
    "build_bullet_line",
    "build_chapter_prompt",
    "build_part_prompt",
    "construct_stage3_plan_input",
    "construct_stage3_synth_input",
    "parse_chapter_summary",
    "parse_part_summary",
]  # unchanged

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Greek numeral helpers
# ---------------------------------------------------------------------------
_GREEK_DIGITS = {
    "Α": 1,
    "Β": 2,
    "Γ": 3,
    "Δ": 4,
    "Ε": 5,
    "Ϛ": 6,  # stigma character (rare)
    "ΣΤ": 6,  # two-letter modern form
    "Ζ": 7,
    "Η": 8,
    "Θ": 9,
}
_GREEK_TENS = {"Ι": 10, "Κ": 20, "Λ": 30, "Μ": 40, "Ν": 50, "Ξ": 60, "Ο": 70, "Π": 80, "ϟ": 90}
_GREEK_HUNDS = {"Ρ": 100, "Σ": 200, "Τ": 300, "Υ": 400, "Φ": 500, "Χ": 600, "Ψ": 700, "Ω": 800}
_SINGLE_VALUES = {**_GREEK_DIGITS, **_GREEK_TENS, **_GREEK_HUNDS}
_token_re = re.compile(r"ΣΤ|Ϛ|[Α-Ω]", re.IGNORECASE)


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
# Article → bullet helpers
# ---------------------------------------------------------------------------

def build_bullet_line(row: Dict[str, str]) -> Optional[str]:
    """Return a Greek bullet line for Stage-2 aggregation.

    Simply prefixes the single-field summary text from Stage-1 with "• ".
    Returns None for rows without a usable summary (e.g. intro articles).
    """
    sum_txt = (row.get("summary_text") or "").strip()
    return f"• {sum_txt}" if sum_txt else None

# ---------------------------------------------------------------------------
# Prompt builders (Stage-2 & legacy Stage-3)
# ---------------------------------------------------------------------------

def build_chapter_prompt(bullets: List[str]) -> Tuple[str, int]:
    joined = "\n".join(bullets)
    words_in = len(joined.split())
    target_words = max(int(words_in * 0.5), 30)
    token_limit = int(target_words * 5)
    prompt = (
        get_prompt("stage2_chapter").format(target_words=target_words, max_words=int(token_limit / 1.3))
        + "\n"
        + joined
    )
    return prompt, token_limit


def build_part_prompt(intro_lines: List[str], chapter_summaries: List[str]) -> Tuple[str, int]:
    labelled_intro: List[str] = []
    if intro_lines:
        if len(intro_lines) >= 1:
            labelled_intro.append(f"{get_prompt('stage3_part_skopos')}{intro_lines[0]}")
        if len(intro_lines) >= 2:
            labelled_intro.append(f"{get_prompt('stage3_part_antikeimeno')}{intro_lines[1]}")
    joined = "\n".join(labelled_intro + chapter_summaries)
    words_in = len(joined.split())
    target_words = max(int(words_in * 0.6), 300)
    token_limit = int(target_words * 3.5)
    prompt = (
        get_prompt("stage3_part").format(target_words=target_words, max_words=int(token_limit / 1.3))
        + "\n"
        + joined
    )
    return prompt, token_limit

# ---------------------------------------------------------------------------
# Output parsers
# ---------------------------------------------------------------------------

def _clean_text(txt: str) -> str:
    return txt.strip().strip("` ")


def parse_chapter_summary(raw: str) -> Optional[str]:
    summ = get_summary(raw)
    return summ if summ is not None else _clean_text(raw) or None


def parse_part_summary(raw: str) -> Optional[str]:
    summ = get_summary(raw)
    return summ if summ is not None else _clean_text(raw) or None

# ---------------------------------------------------------------------------
# Stage-3 two-step helpers
# ---------------------------------------------------------------------------

def construct_stage3_plan_input(
    chapter_summaries: Union[List[str], Dict[str, str]],
    intro_lines: Optional[List[str]] = None,
) -> PlanningInput:
    if isinstance(chapter_summaries, dict):
        mapping = chapter_summaries
    else:
        # Enumerate chapters starting from 0 for full consistency
        mapping = {f"kefalaio_{i}": txt for i, txt in enumerate(chapter_summaries, start=0)}

    payload: PlanningInput = {"περιλήψεις_κεφαλαίων": mapping}

    if intro_lines:
        if len(intro_lines) >= 1 and intro_lines[0]:
            payload["skopos"] = intro_lines[0]
        if len(intro_lines) >= 2 and intro_lines[1]:
            payload["antikeimeno"] = intro_lines[1]
    return payload


def construct_stage3_synth_input(
    narrative_plan: NarrativePlan,
    chapter_summaries: Union[List[str], Dict[str, str]],
    beat_index: int,
    previous_paragraphs: Optional[List[str]] = None,
) -> SynthesisInput:
    sections = narrative_plan.get("narrative_sections", [])
    if not isinstance(sections, list) or beat_index >= len(sections):
        raise ValueError(f"Beat index {beat_index} out of bounds")

    target = sections[beat_index]
    keys = target.get("source_chapters", []) or []

    texts: List[str] = []
    if isinstance(chapter_summaries, dict):
        for k in keys:
            txt = chapter_summaries.get(k)
            if txt:
                texts.append(txt)
    else:
        for k in keys:
            try:
                idx = int(str(k).split("_")[-1])
            except ValueError:
                continue
            if 0 <= idx < len(chapter_summaries):
                texts.append(chapter_summaries[idx])

    return {
        "narrative_plan": narrative_plan,
        "current_beat_index": beat_index,
        "current_beat_title": target.get("section_title"),
        "current_beat_role": target.get("section_role"),
        "source_chapter_texts": texts,
        "previous_paragraphs": previous_paragraphs or [],
    }
