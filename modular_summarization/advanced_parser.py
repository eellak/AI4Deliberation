"""Advanced parsing utilities extracted from original script.
Focuses on splitting a DB article into true article chunks, with gap-filling.
"""
from __future__ import annotations

import re
from typing import List, Dict, Any

# Import original helpers if available
try:
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    utils_dir = os.path.join(project_root, "utils")
    if utils_dir not in sys.path:
        sys.path.insert(0, utils_dir)
    import article_parser_utils as _apu
except ImportError:  # when running outside original repo
    _apu = None  # type: ignore

__all__ = [
    "get_article_chunks",
]


# Matches lines like:
#   Άρθρο 1
#   ### Άρθρο 2
#   **Άρθρο 3**
#   ### **Άρθρο 4**
# Optional leading markdown heading symbols (e.g. ###) or bold markers (one to three '*').
# Match article headers at line start (for content)
_ARTICLE_REGEX = re.compile(
    r"^\s*(?:#+\s*)?(?:\*{1,3}\s*)?(?:Άρθρο|ΑΡΘΡΟ|ΆΡΘΡΟ|άρθρο|article)\s+(\d+)",
    re.IGNORECASE | re.MULTILINE,
)

# Separate lightweight pattern for grabbing number anywhere inside a single line (DB title)
_INLINE_ARTICLE_RE = re.compile(r"(?:Άρθρο|ΑΡΘΡΟ|ΆΡΘΡΟ|άρθρο|article)\s+(\d+)", re.IGNORECASE)


def _extract_header_numbers(text: str) -> List[int]:
    """Detect main headers (outside quotes) and return sorted article numbers."""
    numbers: List[int] = []
    for match in _ARTICLE_REGEX.finditer(text):
        if _inside_quotes(text, match.start()):
            continue
        num = int(match.group(1))
        numbers.append(num)
    return sorted(set(numbers))


def _inside_quotes(text: str, idx: int) -> bool:
    """Naive quote check: count quotes before idx, odd => inside quotes."""
    return text[:idx].count("\"") % 2 == 1 or text[:idx].count("'") % 2 == 1


# -------------------------------------------------------------
# Public API
# -------------------------------------------------------------

def get_article_chunks(db_content: str, db_title: str) -> List[Dict[str, Any]]:
    """Return list of article chunks with metadata.
    Much lighter than original: only header detection + simple splits.
    """
    if not db_content.strip():
        return []

    header_iter = list(_ARTICLE_REGEX.finditer(db_content))
    if not header_iter:
        # Try extract number from DB title line
        m = _INLINE_ARTICLE_RE.search(db_title)
        art_num = int(m.group(1)) if m else None
        return [{
            "title_line": db_title.strip(),
            "content": db_content.strip(),
            "source_db_title": db_title,
            "article_number": art_num,
        }]

    chunks: List[Dict[str, Any]] = []
    for i, match in enumerate(header_iter):
        start = match.end()
        end = header_iter[i + 1].start() if i + 1 < len(header_iter) else len(db_content)
        content_slice = db_content[start:end].strip()
        title_line = match.group(0).strip()
        chunks.append({
            "title_line": title_line,
            "content": content_slice,
            "article_number": int(match.group(1)),
            "source_db_title": db_title,
        })
    return chunks
