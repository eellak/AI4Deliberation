"""Advanced parsing utilities extracted from original script.
Focuses on splitting a DB article into true article chunks, with gap-filling.
"""
from __future__ import annotations

import re
from typing import List, Dict, Any

# Import original helpers if available
try:
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
_ARTICLE_REGEX = re.compile(
    r"^\s*(?:#+\s*)?(?:\*{1,3}\s*)?Ά?ρθρο\s+(\d+)",
    re.IGNORECASE | re.MULTILINE,
)


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
        return [{"title_line": db_title, "content": db_content, "source_db_title": db_title}]

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
