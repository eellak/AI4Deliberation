"""Utility functions for detecting references to Greek laws and presidential decrees inside text.

A reference is considered any substring matching the standard pattern
«ν. 1234/2010», «Ν. 4887/2022 (Α' 16)» or similar.  The pattern can be
extended, but for now we cover the common *ν.* / *Ν.* prefix with number and
4-digit year plus optional FEK information.

Presidential Decree references are also detected, with patterns like «π.δ. 123/2022» or «Προεδρικό Διάταγμα 123/2022».
"""
from __future__ import annotations

import re
import json
from typing import List, Dict, Any, Tuple, Match, Optional

__all__ = [
    "LAW_REGEX",
    "PRES_DECREE_REGEX",
    "find_law_references",
    "has_law_reference",
    "has_presidential_decree_reference",
    "extract_quoted_segments",
    "article_modifies_law",
    "parse_law_mod_json",
    "parse_law_new_json",
    "contains_skopos",
    "contains_antikeimeno",
    "detect_scope_and_objective",
    "is_skopos_article",
    "is_antikeimeno_article",
]

# ---------------------------------------------------------------------------
# Regex pattern (verbose, case-insensitive)
# ---------------------------------------------------------------------------

LAW_REGEX_PATTERN = r"""
(?ix)  # Case-insensitive, verbose
# Includes legislative decrees (ν.δ./Ν.Δ.) along with ordinary laws.
\[?                                              # Optional opening bracket
(?P<type>                                          # Type of law
    ν\.|Ν\.|                                     # Standard law
    α\.ν\.|Α\.Ν\.|                              # Emergency law
    κ\.ν\.|Κ\.Ν\.|                              # Codified law
    ν\.?\s*[Α-Ω]+|Ν\.?\s*[Α-Ω]+|               # Prefixed law: ν. ΓΩΠΣΤ
    v\.|                                          # Latin v.
    νόμου                                        # capture "νόμου" / "Νόμου"
    ν\.δ\.|Ν\.Δ\.                                # Legislative decree
)
\s*
(?P<number>\d+)                                   # Law number
\s*/\s*
(?P<year>\d{4})                                   # Year
(?:[\s,]*\(?(?P<fek_series>Α'?|'Α`?'|A'?')\s*(?P<fek_number>\d+)\)?)?  # Optional FEK info
\]?                                              # Optional closing bracket
"""

LAW_REGEX = re.compile(LAW_REGEX_PATTERN, re.VERBOSE | re.IGNORECASE)

# ---------------------------------------------------------------------------
# Presidential Decree regex (borrowed from regex_capture_groups.py snippet)
# ---------------------------------------------------------------------------

PRES_DECREE_REGEX_PATTERN = r"""
(?ix)
(?P<prefix>π\.δ\.|Π\.Δ\.|Π\.δ\.|πδ|π\.δ|προεδρικ[οό] διάταγμα)
(?:
    \s*(?P<number>\d+)\s*/\s*(?P<year_num>\d{4})
|
    \s+της\s+
    (?P<date1_day>\d{1,2}(?:ης)?)
    (?:\.|\s+|η)?
    (?P<date1_month>[α-ωΑ-Ω]+\d{1,2})
    (?:\s*/\s*
        (?P<date2_day>\d{1,2}(?:ης)?)
        (?:\.|\s+|η)?
        (?P<date2_month>[α-ωΑ-Ω]+\d{1,2})
    )?
    (?:\.|\s+)?(?P<year_date>\d{4})
)
"""

PRES_DECREE_REGEX = re.compile(PRES_DECREE_REGEX_PATTERN, re.VERBOSE | re.IGNORECASE)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _match_to_dict(m: Match[str]) -> Dict[str, Any]:
    """Convert regex match object to serialisable dict."""
    gd = m.groupdict()
    return {
        "match": m.group(0).strip(),
        "type": gd.get("type"),
        "number": int(gd["number"]),
        "year": int(gd["year"]),
        "fek_series": gd.get("fek_series"),
        "fek_number": int(gd["fek_number"]) if gd.get("fek_number") else None,
        "span": m.span(),
    }


def find_law_references(text: str) -> List[Dict[str, Any]]:
    """Return list of law-reference dicts found in *text*.

    Each dict includes keys: *match*, *type*, *number*, *year*, *fek_series*,
    *fek_number*, *span*.
    """
    return [_match_to_dict(m) for m in LAW_REGEX.finditer(text)]


def has_law_reference(text: str) -> bool:
    """Quick boolean check."""
    return bool(LAW_REGEX.search(text))


def has_presidential_decree_reference(text: str) -> bool:
    """Return True if text contains reference to a Presidential Decree."""
    return bool(PRES_DECREE_REGEX.search(text))


# ---------------------------------------------------------------------------
# Quote handling helpers
# ---------------------------------------------------------------------------

_GREEK_QUOTE_RE = re.compile(r"«([^»]{5,})»", re.DOTALL)

_MULTILINE_QUOTE_RE = re.compile(r"«[^»]*\n[^»]*»", re.DOTALL)


def extract_quoted_segments(text: str) -> List[str]:
    """Return list of string segments enclosed in Greek quotes « » of at least 5 chars."""
    return [m.group(1).strip() for m in _GREEK_QUOTE_RE.finditer(text)]


def has_multiline_quote(text: str) -> bool:
    """Return True if there is a quoted segment that contains a line break."""
    return bool(_MULTILINE_QUOTE_RE.search(text))


def article_modifies_law(text: str) -> bool:
    """Return *True* when a law article *likely* modifies a previous law.

    Criteria implemented:
    1. There must be **at least one** match of ``LAW_REGEX`` or ``PRES_DECREE_REGEX`` – i.e. a citation like
       ``ν. 4887/2022`` or similar, or a Presidential Decree reference.
    2. *After* that citation, there must exist **at least one** Greek quoted segment
       (enclosed in « … »).  We do **not** inspect the quote's content – just that the
       quoted text logically follows the law citation.  This ordering constraint helps
       avoid false-positives where random quotes appear in a preamble and a law citation
       follows later for an unrelated reason.

    This simple heuristic is robust enough for batch labelling while remaining very
    cheap to compute (single regex + single search).  It can be further refined later
    if recall/precision metrics on manually-labelled sets suggest adjustments.
    """
    law_match = LAW_REGEX.search(text)
    decree_match = PRES_DECREE_REGEX.search(text)

    # Pick whichever match appears first (if both exist) because ordering matters for quote search
    candidate_match = None
    if law_match and decree_match:
        candidate_match = law_match if law_match.start() < decree_match.start() else decree_match
    else:
        candidate_match = law_match or decree_match

    if not candidate_match:
        return False

    # Accept either (a) multiline quote or (b) a *full-line* single quote (starts with «, ends with » or ». )
    start_idx = candidate_match.end()

    if _MULTILINE_QUOTE_RE.search(text, pos=start_idx):
        return True

    # Fallback: scan line-by-line for a standalone quoted segment
    for line in text[start_idx:].splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("«") and (s.endswith("»") or s.endswith("».")) and len(s) > 7:
            return True

    return False


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

def parse_law_mod_json(raw: str) -> Optional[Dict[str, str]]:
    """Attempt to load JSON returned by the LLM prompt.

    Handles common wrapping such as Markdown code fences or triple backticks.
    Returns dict if valid and contains required keys, else ``None``.
    """
    # strip fences and whitespace
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # remove first and last fence lines
        parts = cleaned.split("```", 2)
        if len(parts) >= 3:
            cleaned = parts[1].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    # Accept both legacy and new schema (with key_themes list)
    required_basic = {"law_reference", "article_number", "change_type", "major_change_summary"}
    required_extended = required_basic | {"key_themes"}

    if required_basic.issubset(data.keys()):
        # If extended keys exist validate type
        if "key_themes" in data:
            if not isinstance(data["key_themes"], list):
                return None
            # normalise list to str items
            data["key_themes"] = [str(x).strip() for x in data["key_themes"][:3]]  # keep max 3
        return {k: data.get(k) for k in (required_basic | {"key_themes"}) if k in data}
    return None


def parse_law_new_json(raw: str) -> Optional[Dict[str, Any]]:
    """Validate JSON from LAW_NEW_JSON_PROMPT.

    Expected keys: article_title, provision_type, core_provision_summary, key_themes (list).
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```", 2)
        if len(parts) >= 3:
            cleaned = parts[1].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    required = {"article_title", "provision_type", "core_provision_summary", "key_themes"}
    if not required.issubset(data.keys()):
        return None
    if not isinstance(data["key_themes"], list):
        return None
    data["key_themes"] = [str(x).strip() for x in data["key_themes"][:3]]
    return {k: data[k] for k in required}


# ---------------------------------------------------------------------------
# Scope & Objective detectors (Σκοπός / Αντικείμενο)
# ---------------------------------------------------------------------------

_RE_SKOPOS = re.compile(r"\bΣκοπός\b", re.IGNORECASE)
_RE_ANTIKEIMENO = re.compile(r"\bΑντικείμενο\b", re.IGNORECASE)


def contains_skopos(text: str) -> bool:  # noqa: D401
    """Return True if *text* contains the word «Σκοπός» (case-insensitive)."""
    return bool(_RE_SKOPOS.search(text))


def contains_antikeimeno(text: str) -> bool:  # noqa: D401
    """Return True if *text* contains the word «Αντικείμενο» (case-insensitive)."""
    return bool(_RE_ANTIKEIMENO.search(text))


def detect_scope_and_objective(article1_text: str, article2_text: str) -> dict[str, bool]:
    """Return dict with booleans for Σκοπός in *article1_text* and Αντικείμενο in *article2_text*."""
    return {
        "has_skopos": contains_skopos(article1_text),
        "has_antikeimeno": contains_antikeimeno(article2_text),
    }


def is_skopos_article(text: str) -> bool:  # noqa: D401
    """Dummy detector – always returns False. To be implemented."""
    return False


def is_antikeimeno_article(text: str) -> bool:  # noqa: D401
    """Dummy detector – always returns False. To be implemented."""
    return False
