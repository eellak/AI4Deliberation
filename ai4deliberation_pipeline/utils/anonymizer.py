#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Light-weight username anonymiser + HF Hub helpers for the AI4Deliberation
pipeline.

Key points
==========
1. **Username only**: replaces `comments.username` with pseudonyms. No in-text
   e-mail / phone scrubbing – keeps the run fast.
2. **Deterministic mapping**: a username is hashed to `user_<8-hex>`. Runs are
   idempotent – re-running does *not* change existing pseudonyms.
3. **Per-consultation updates** with progress logging so the orchestrator log
   shows:
   ``Consultation 42 anonymised: 123 usernames across 456 comments in 0.72s``
4. **HF helpers**: download existing DB, anonymise it, upload back. Exposed via
   `ensure_download_anonymise_upload()` which the orchestrator uses when
   `--sync-db` is supplied.

The module is intentionally dependency-free apart from `huggingface_hub`.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable

try:
    from huggingface_hub import hf_hub_download, HfApi
except ImportError as exc:  # pragma: no cover – handled in requirements
    raise ImportError(
        "huggingface_hub package is required. Add it to requirements.txt and install."
    ) from exc

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Helper: deterministic pseudonym
# ---------------------------------------------------------------------------

_USER_RE = re.compile(r"^user_[0-9a-f]{8}$", re.I)

def pseudonymize(username: str | None) -> str | None:
    """Map *username* → ``user_<sha1[:8]>``. Returns the original value for None/empty."""
    if not username:
        return username
    if _USER_RE.match(username):
        return username  # already anonymised
    digest = hashlib.sha1(username.lower().encode()).hexdigest()[:8]
    return f"user_{digest}"

# Backwards-compatibility aliases used by scraper modules

def pseudonymize_username(username: str | None) -> str | None:  # noqa: N802
    """Alias for old import path."""
    return pseudonymize(username)

def scrub_pii(text: str | None, mapping: Dict[str, str] | None = None) -> str | None:  # noqa: N802
    """No-op: full text scrubbing removed for performance, kept for import compatibility."""
    return text

# ---------------------------------------------------------------------------
# HF Hub helpers
# ---------------------------------------------------------------------------

def download_db_from_hf(repo_id: str, filename: str, local_path: str) -> str:
    """Download *filename* from *repo_id* (a dataset) unless it already exists."""
    if os.path.exists(local_path):
        _LOGGER.info("DB already present at %s; skipping download", local_path)
        return local_path

    _LOGGER.info("Downloading %s from HF dataset %s …", filename, repo_id)
    hf_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        local_dir=os.path.dirname(local_path),
    )
    if hf_path != local_path:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        os.replace(hf_path, local_path)
    _LOGGER.info("Downloaded DB to %s", local_path)
    return local_path


def upload_db_to_hf(
    repo_id: str,
    local_path: str,
    path_in_repo: str | None = None,
    commit_msg: str | None = None,
):
    """Upload *local_path* to *repo_id* (dataset)."""
    api = HfApi()
    if path_in_repo is None:
        path_in_repo = f"cleaned/{os.path.basename(local_path)}"
    if commit_msg is None:
        commit_msg = f"Upload cleaned DB on {datetime.utcnow().isoformat()}"

    _LOGGER.info("Uploading %s to %s:%s", local_path, repo_id, path_in_repo)
    api.upload_file(
        path_or_fileobj=local_path,
        path_in_repo=path_in_repo,
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=commit_msg,
    )
    _LOGGER.info("Upload complete.")


# ---------------------------------------------------------------------------
# Username-only anonymisation
# ---------------------------------------------------------------------------

def _ensure_username_column(conn: sqlite3.Connection):
    cur = conn.execute("PRAGMA table_info(comments)")
    cols = [row[1] for row in cur.fetchall()]
    if "username" not in cols and "author" in cols:
        _LOGGER.info("Renaming legacy column 'author' → 'username' in comments table")
        conn.execute("ALTER TABLE comments RENAME COLUMN author TO username")
        conn.commit()


def _consultation_ids(conn: sqlite3.Connection) -> list[int]:
    cur = conn.execute(
        "SELECT DISTINCT consultation_id FROM articles WHERE consultation_id IS NOT NULL"
    )
    return [row[0] for row in cur.fetchall()]


def _usernames_for_consultation(conn: sqlite3.Connection, cid: int) -> list[str]:
    cur = conn.execute(
        """
        SELECT DISTINCT username FROM comments
        WHERE article_id IN (
            SELECT id FROM articles WHERE consultation_id = ?
        ) AND username IS NOT NULL
        """,
        (cid,),
    )
    return [row[0] for row in cur.fetchall()]


def anonymise_sqlite(db_path: str) -> str:
    """In-place username anonymisation. Returns *db_path* for convenience."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)

    _LOGGER.info("Starting anonymisation of %s", db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous  = OFF")

    try:
        _ensure_username_column(conn)
        consultations = _consultation_ids(conn)

        for cid in consultations:
            start = time.perf_counter()
            usernames = _usernames_for_consultation(conn, cid)
            if not usernames:
                continue

            mapping: Dict[str, str] = {u: pseudonymize(u) for u in usernames}
            col = "username"
            cases = "\n".join([f"WHEN {col} = ? THEN ?" for _ in mapping])
            sql = (
                f"UPDATE comments SET {col} = CASE {cases} END WHERE article_id IN ("
                "SELECT id FROM articles WHERE consultation_id = ?) AND "
                f"{col} IN ({','.join('?' for _ in mapping)})"
            )
            params: list[str] = []
            for u, p in mapping.items():
                params.extend([u, p])
            params.append(cid)
            params.extend(mapping.keys())
            conn.execute("BEGIN TRANSACTION")
            conn.execute(sql, params)
            conn.commit()

            cur = conn.execute(
                "SELECT COUNT(*) FROM comments WHERE article_id IN (SELECT id FROM articles WHERE consultation_id = ?)",
                (cid,),
            )
            n_comments = cur.fetchone()[0]
            _LOGGER.info(
                "Consultation %s anonymised: %d usernames across %d comments in %.2fs",
                cid,
                len(mapping),
                n_comments,
                time.perf_counter() - start,
            )

    finally:
        conn.close()
        _LOGGER.info("Anonymisation finished for %s", db_path)

    return db_path


# ---------------------------------------------------------------------------
# High-level helper used by orchestrator --sync-db
# ---------------------------------------------------------------------------

def ensure_download_anonymise_upload(repo_id: str, filename: str, local_dir: str) -> str:
    """Download → anonymise → upload flow used by the orchestrator."""
    local_path = os.path.join(local_dir, filename)
    download_db_from_hf(repo_id, filename, local_path)
    anonymise_sqlite(local_path)
    upload_db_to_hf(repo_id, local_path)
    return local_path


if __name__ == "__main__":  # manual CLI helper
    import argparse

    p = argparse.ArgumentParser(description="Username anonymiser for AI4Deliberation")
    p.add_argument("db", help="Path to SQLite file to anonymise in-place")
    args = p.parse_args()

    anonymise_sqlite(args.db)
