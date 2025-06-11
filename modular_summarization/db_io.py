"""Lightweight DB helpers for fetching article data.
Isolated here to keep workflow runner slim and unit-testable.
"""
from __future__ import annotations

import sqlite3
import logging
from typing import List, Dict, Any, Optional

from .config import DB_PATH, TABLE_NAME, TITLE_COLUMN, CONTENT_COLUMN

logger = logging.getLogger(__name__)

__all__ = ["ArticleRow", "fetch_articles"]

ArticleRow = Dict[str, Any]


def fetch_articles(
    consultation_id: int,
    *,
    db_path: Optional[str] = None,
    article_id: Optional[int] = None,
) -> List[ArticleRow]:
    """Return list of article rows as dicts.

    Parameters
    ----------
    db_path : str | None
        SQLite file path; when None uses `config.DB_PATH`.

    Columns returned: id, consultation_id, title, content
    """
    path = db_path or DB_PATH
    logger.info("Fetching articles from SQLite: %s", path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if article_id is not None:
        cur.execute(
            f"SELECT id, consultation_id, {TITLE_COLUMN} AS title, {CONTENT_COLUMN} AS content "
            f"FROM {TABLE_NAME} WHERE consultation_id = ? AND id = ? ORDER BY id",
            (consultation_id, article_id),
        )
    else:
        cur.execute(
            f"SELECT id, consultation_id, {TITLE_COLUMN} AS title, {CONTENT_COLUMN} AS content "
            f"FROM {TABLE_NAME} WHERE consultation_id = ? ORDER BY id",
            (consultation_id,),
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    logger.info("Fetched %d rows", len(rows))
    return rows
