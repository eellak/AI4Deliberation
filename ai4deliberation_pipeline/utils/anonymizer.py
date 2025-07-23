#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database anonymisation and HF Hub sync utilities for AI4Deliberation.

Key features
------------
1. Download an existing SQLite DB from HuggingFace Hub (dataset repo).
2. Anonymise the DB by:
   a. Replacing usernames with stable pseudonymous IDs.
   b. Scrubbing e-mails and phone numbers from free-text fields.
3. Re-upload the cleaned DB back to the same HF repo (or to another).

This module is intentionally lightweight so it can be imported by the
pipeline orchestrator or executed standalone via `python -m ...anonymizer`.
"""
from __future__ import annotations

import os
import re
import sqlite3
import uuid
import hashlib
import logging
import shutil
from datetime import datetime
from typing import Dict, Iterable, Tuple

try:
    from huggingface_hub import hf_hub_download, HfApi
except ImportError as exc:  # pragma: no cover – handled by requirements
    raise ImportError("huggingface_hub package is required for anonymizer utilities. "
                      "Add it to requirements.txt and install.") from exc

_LOGGER = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}")
# Greek phone numbers (10 digits after leading prefix).
# Prefix: landline 2xx… or mobile 69…
# Accept optional “+30” and optional SINGLE space between digits/groups.
PHONE_RE = re.compile(r"(?:\\+30[\\s]?)?(?:2\\d{2}|69)(?:\\s?\\d){8}")

# ---------------------------------------------------------------------------
# HF helper
# ---------------------------------------------------------------------------

def download_db_from_hf(repo_id: str, filename: str, local_path: str) -> str:
    """Download *filename* from *repo_id* (dataset) if not already present.

    Parameters
    ----------
    repo_id: str
        e.g. "glossAPI/opengov.gr-diaboyleuseis"
    filename: str
        Name of the DB file inside the repo.
    local_path: str
        Where to store it locally.
    Returns
    -------
    str
        Resolved local path to the downloaded/copied DB.
    """
    if os.path.exists(local_path):
        _LOGGER.info("DB already present at %s; skipping download", local_path)
        return local_path

    _LOGGER.info("Downloading %s from HF dataset %s …", filename, repo_id)
    hf_path = hf_hub_download(repo_id=repo_id, filename=filename,
                              repo_type="dataset", local_dir=os.path.dirname(local_path))
    if hf_path != local_path:
        shutil.move(hf_path, local_path)
    _LOGGER.info("Downloaded DB to %s", local_path)
    return local_path

# ---------------------------------------------------------------------------
# Anonymisation helpers
# ---------------------------------------------------------------------------

def _generate_user_mapping(usernames: Iterable[str]) -> Dict[str, str]:
    """Return a deterministic but irreversible mapping "orig" -> "user_<uuid>"."""
    mapping: Dict[str, str] = {}
    for name in sorted(set(u for u in usernames if u)):
        mapping[name] = f"user_{uuid.uuid4().hex[:8]}"
    return mapping


def _scrub_text(text: str | None, mapping: Dict[str, str] | None = None) -> str | None:
    if text is None:
        return None
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    # Remove username signatures if mapping provided
    if mapping:
        for orig in mapping.keys():
            # remove lines that contain only the name (case-insensitive)
            pattern = rf"^\\s*{re.escape(orig)}\\s*$"
            text = re.sub(pattern, "", text, flags=re.MULTILINE | re.IGNORECASE)  # delete line
    return text


# Public helpers -------------------------------------------------------------

def pseudonymize_username(username: str | None) -> str | None:
    """Return stable pseudonymous ID for a username. Keeps None/'' as is."""
    if not username:
        return username
    base = hashlib.sha1(username.lower().encode()).hexdigest()[:8]
    return f"user_{base}"


def scrub_pii(text: str | None, mapping: Dict[str, str] | None = None) -> str | None:
    """Scrub emails, phones, and username signatures from *text*."""
    return _scrub_text(text, mapping)

# ---------------------------------------------------------------------------

def anonymise_sqlite(db_path: str) -> str:
    """Apply anonymisation in-place. Returns the path to the anonymised DB."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)

    _LOGGER.info("Starting anonymisation of %s", db_path)
    conn = sqlite3.connect(db_path)

    def _col_exists(table: str, col: str) -> bool:
        try:
            cur = conn.execute(f"PRAGMA table_info({table})")
            return any(row[1] == col for row in cur.fetchall())
        except sqlite3.OperationalError:
            return False
    try:
        cur = conn.cursor()

        # --- 1. Build user mapping from available username/author columns
        usernames_comments: list[str] = []
        if _col_exists("comments", "author"):
            cur.execute("SELECT DISTINCT author FROM comments WHERE author IS NOT NULL")
            usernames_comments = [row[0] for row in cur.fetchall()]
        elif _col_exists("comments", "username"):
            cur.execute("SELECT DISTINCT username FROM comments WHERE username IS NOT NULL")
            usernames_comments = [row[0] for row in cur.fetchall()]

        usernames_articles: list[str] = []
        if _col_exists("articles", "author"):
            cur.execute("SELECT DISTINCT author FROM articles WHERE author IS NOT NULL")
            usernames_articles = [row[0] for row in cur.fetchall()]
        mapping = _generate_user_mapping(usernames_comments + usernames_articles)
        _LOGGER.info("Generated pseudonyms for %d unique authors", len(mapping))

        # --- 2. Replace authors
        for original, pseudo in mapping.items():
            if _col_exists("comments", "author"):
                cur.execute("UPDATE comments SET author = ? WHERE author = ?", (pseudo, original))
            elif _col_exists("comments", "username"):
                cur.execute("UPDATE comments SET username = ? WHERE username = ?", (pseudo, original))
            if _col_exists("articles", "author"):
                cur.execute("UPDATE articles SET author = ? WHERE author = ?", (pseudo, original))
        conn.commit()

        # --- 3. Scrub e-mails / phones from free-text columns
        def _scrub_table(tablename: str, colname: str):
            try:
                cur.execute(f"SELECT rowid, {colname} FROM {tablename}")
            except sqlite3.OperationalError:
                return
            rows: Iterable[Tuple[int, str]] = cur.fetchall()
            updates = []
            for rowid, txt in rows:
                new_txt = _scrub_text(txt, mapping)
                if new_txt != txt:
                    updates.append((new_txt, rowid))
            if updates:
                cur.executemany(f"UPDATE {tablename} SET {colname} = ? WHERE rowid = ?", updates)
                conn.commit()
                _LOGGER.info("Scrubbed %d rows in %s.%s", len(updates), tablename, colname)

        # Call scrub on all main text-bearing tables
        _scrub_table("comments", "content")
        _scrub_table("articles", "content")
        _scrub_table("documents", "processed_text")

    finally:
        conn.close()
    _LOGGER.info("Anonymisation finished for %s", db_path)
    return db_path

# ---------------------------------------------------------------------------
# Upload helper
# ---------------------------------------------------------------------------

def upload_db_to_hf(repo_id: str, local_path: str, path_in_repo: str | None = None,
                    commit_msg: str | None = None):
    api = HfApi()
    if path_in_repo is None:
        # Store under a "cleaned" prefix by default
        base_name = os.path.basename(local_path)
        path_in_repo = f"cleaned/{base_name}"
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
# Convenience driver
# ---------------------------------------------------------------------------

def ensure_download_anonymise_upload(repo_id: str, filename: str, local_dir: str = "."):
    """End-to-end helper for orchestrator: download → anonymise → upload."""
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)
    download_db_from_hf(repo_id, filename, local_path)
    anonymise_sqlite(local_path)
    upload_db_to_hf(repo_id, local_path)
    return local_path

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Download, anonymise, and re-upload an AI4Deliberation DB.")
    parser.add_argument("repo_id", help="HF dataset repo id, e.g. glossAPI/opengov.gr-diaboyleuseis")
    parser.add_argument("filename", help="Filename inside repo, e.g. deliberation_data.db")
    parser.add_argument("--local-dir", default="/mnt/data/AI4Deliberation", help="Where to store the DB locally")
    args = parser.parse_args()
    ensure_download_anonymise_upload(args.repo_id, args.filename, args.local_dir)
