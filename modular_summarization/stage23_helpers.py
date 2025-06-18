"""Helpers for Stage-2 (ΚΕΦΑΛΑΙΟ) and Stage-3 (ΜΕΡΟΣ) aggregation.

All functions are deliberately *pure* so that they can be unit-tested without
LLM calls or I/O.  The orchestrator script (`scripts/generate_stage2_3_summaries.py`)
imports these to build prompts, parse results and sort Greek numerals.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import re
import logging
import unicodedata
import csv
import json

from pathlib import Path

from .prompts import get_prompt
from .compression import summarization_budget
from .law_utils import (
    parse_law_mod_json,
    parse_law_new_json,
    get_summary,
)

__all__ = [
    "greek_numeral_to_int",
    "greek_numeral_sort_key",
    "build_bullet_line",
    "build_chapter_prompt",
    "build_part_prompt",
    "parse_chapter_summary",
    "parse_part_summary",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Greek numeral helpers  (auto, up to >= 200)
# ---------------------------------------------------------------------------
_GREEK_DIGITS = {
    "Α": 1,
    "Β": 2,
    "Γ": 3,
    "Δ": 4,
    "Ε": 5,
    "Ϛ": 6,  # stigma character (rarely appears)
    "ΣΤ": 6,  # modern two-letter form
    "Ζ": 7,
    "Η": 8,
    "Θ": 9,
}
_GREEK_TENS = {
    "Ι": 10,
    "Κ": 20,
    "Λ": 30,
    "Μ": 40,
    "Ν": 50,
    "Ξ": 60,
    "Ο": 70,
    "Π": 80,
    "ϟ": 90,  # koppa – hardly used
}
_GREEK_HUNDREDS = {
    "Ρ": 100,
    "Σ": 200,
    "Τ": 300,
    "Υ": 400,
    "Φ": 500,
    "Χ": 600,
    "Ψ": 700,
    "Ω": 800,
}

# Merge dictionaries for single-token lookup
_SINGLE_TOKEN_VALUES = {**_GREEK_DIGITS, **_GREEK_TENS, **_GREEK_HUNDREDS}

_token_re = re.compile(
    r"ΣΤ|Ϛ|[Α-Ω]",  # match two-letter ΣΤ first, then single Greek uppercase letters
    re.IGNORECASE,
)


def _strip_accents(label: str) -> str:
    """Return *label* upper-cased, accents/tonos removed, whitespace stripped."""
    nfkd = unicodedata.normalize("NFD", label)
    stripped = "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")
    return stripped.upper().strip("΄'`·. ")


def greek_numeral_to_int(label: str) -> int:  # noqa: D401
    """Convert Greek numeral string to integer (supports additive notation).

    Examples
    --------
    >>> greek_numeral_to_int("Α΄")
    1
    >>> greek_numeral_to_int("ΙΑ΄")
    11
    >>> greek_numeral_to_int("Ν")
    50
    """
    if not label:
        return 0
    txt = _strip_accents(label)

    total = 0
    idx = 0
    while idx < len(txt):
        # Handle two-letter ΣΤ specially
        if txt[idx : idx + 2] == "ΣΤ":
            total += 6
            idx += 2
            continue
        ch = txt[idx]
        val = _SINGLE_TOKEN_VALUES.get(ch)
        if val is None:
            # Unknown char → treat as 0 but continue to avoid crash
            idx += 1
            continue
        total += val
        idx += 1
    return total


def greek_numeral_sort_key(label: str) -> Tuple[int, str]:
    """Return (numeric_value, original) suitable for `sorted(key=...)`."""
    return (greek_numeral_to_int(label), label)

# ---------------------------------------------------------------------------
# 2. Article → bullet conversion helpers
# ---------------------------------------------------------------------------

def _fmt_law_mod(d: dict) -> str:
    return f"Στο νομοσχέδιο {d['change_type']} το {d['article_number']} του {d['law_reference']}. Η σύνοψη της αλλαγής είναι: {d['major_change_summary']}"


def _fmt_law_new(d: dict) -> str:
    return f"{d['article_title']} ({d['provision_type']}): {d['core_provision_summary']}"


def build_bullet_line(row: Dict[str, str]) -> Optional[str]:
    """Return a formatted bullet or *None* for non-summarisable rows.

    Parameters
    ----------
    row : dict
        A single row from `consN_stage1.csv`.
    """
    decision = row.get("classifier_decision", "")
    parsed_str = row.get("parsed_json", "")
    parsed: Optional[dict] = None
    try:
        parsed = json.loads(parsed_str) if parsed_str else None
    except json.JSONDecodeError:
        parsed = None

    if decision == "modifies" and parsed:
        d = parse_law_mod_json(json.dumps(parsed, ensure_ascii=False))
        return "• " + _fmt_law_mod(d) if d else None
    if decision == "new_provision" and parsed:
        d = parse_law_new_json(json.dumps(parsed, ensure_ascii=False))
        return "• " + _fmt_law_new(d) if d else None
    return None  # skip others

# ---------------------------------------------------------------------------
# 3. Prompt builders
# ---------------------------------------------------------------------------

def build_chapter_prompt(bullets: List[str]) -> Tuple[str, int]:
    joined = "\n".join(bullets)
    words_in = len(joined.split())

    # Calculate target and maximum word counts
    target_words = max(int(words_in * 0.5), 30)  # ensure at least 30 words
    token_limit = int(target_words * 5)
    max_words = int(token_limit / 1.3)  # ~1.3 tokens per word approximation

    prompt = (
        get_prompt("stage2_chapter").format(
            target_words=target_words, max_words=max_words
        )
        + "\n"
        + joined
    )
    return prompt, token_limit


def build_part_prompt(
    intro_lines: List[str],
    chapter_summaries: List[str],
) -> Tuple[str, int]:
    """Build Stage-3 prompt.

    *Intro lines* (Σκοπός / Αντικείμενο) are optional and, if present, are
    prefixed with labels so the LLM grasps their role.
    """
    labelled_intro: List[str] = []
    if intro_lines:
        # Determine up to two intro lines, label them explicitly
        if len(intro_lines) >= 1:
            skopos_prefix = get_prompt("stage3_part_skopos")
            labelled_intro.append(f"{skopos_prefix}{intro_lines[0]}")
        if len(intro_lines) >= 2:
            ant_prefix = get_prompt("stage3_part_antikeimeno")
            labelled_intro.append(f"{ant_prefix}{intro_lines[1]}")

    joined = "\n".join(labelled_intro + chapter_summaries)
    words_in = len(joined.split())

    target_words = max(int(words_in * 0.6), 300)
    token_limit = int(target_words * 3.5)
    max_words = int(token_limit / 1.3)

    prompt = (
        get_prompt("stage3_part").format(
            target_words=target_words, max_words=max_words
        )
        + "\n"
        + joined
    )
    return prompt, token_limit

# ---------------------------------------------------------------------------
# 4. Output parsers
# ---------------------------------------------------------------------------

def _clean_text(txt: str) -> str:
    """Return *txt* stripped of whitespace and leading/trailing markdown fences."""
    return txt.strip().strip("` ")


def parse_chapter_summary(raw: str) -> Optional[str]:
    """Extract stage-2 summary. Accepts either plain text or `{\"summary\":...}` JSON."""
    summ = get_summary(raw)
    if summ is not None:
        return summ
    cleaned = _clean_text(raw)
    return cleaned or None


def parse_part_summary(raw: str) -> Optional[str]:
    """Extract stage-3 summary. Accepts either plain text or JSON wrapper."""
    summ = get_summary(raw)
    if summ is not None:
        return summ
    cleaned = _clean_text(raw)
    return cleaned or None
