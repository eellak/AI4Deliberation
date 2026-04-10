#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from urllib.parse import urlparse


def normalize_consultation_url(url):
    """Normalize URL for robust matching across http/https and trailing slash differences."""
    if not url:
        return None

    try:
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower()
        path = parsed.path or ""
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        query = parsed.query or ""
        if query:
            return f"{netloc}{path}?{query}"
        return f"{netloc}{path}"
    except Exception:
        return None


def extract_ministry_code_from_url(url):
    """Extract ministry code from URL path, e.g. '/yme/?p=5739' -> 'yme'."""
    try:
        parsed = urlparse((url or "").strip())
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        return path_parts[0].lower() if path_parts else None
    except Exception:
        return None


def find_existing_consultation(session, consultation_model, url, post_id, logger=None):
    """
    Resolve an existing consultation using URL first and post_id only within
    the same ministry namespace.
    """
    normalized_url = normalize_consultation_url(url)

    if normalized_url:
        consultations = session.query(consultation_model).all()
        for consultation in consultations:
            if normalize_consultation_url(consultation.url) == normalized_url:
                if logger:
                    logger.info(f"Found existing consultation by URL match: {consultation.title}")
                return consultation

    if not post_id:
        return None

    post_id_matches = session.query(consultation_model).filter_by(post_id=post_id).all()
    if not post_id_matches:
        return None

    target_ministry = extract_ministry_code_from_url(url)
    if target_ministry:
        ministry_matches = [
            consultation
            for consultation in post_id_matches
            if extract_ministry_code_from_url(consultation.url) == target_ministry
        ]
        if not ministry_matches:
            if logger:
                logger.warning(
                    f"Ignoring {len(post_id_matches)} consultation(s) with post_id={post_id} "
                    f"because none match ministry '{target_ministry}'"
                )
            return None
        post_id_matches = ministry_matches

    if len(post_id_matches) == 1:
        consultation = post_id_matches[0]
        if logger:
            logger.info(f"Found existing consultation by post_id match: {consultation.title}")
        return consultation

    unfinished = [consultation for consultation in post_id_matches if not consultation.is_finished]
    consultation = unfinished[0] if unfinished else post_id_matches[0]

    if logger:
        ministry_note = target_ministry or "unknown"
        logger.warning(
            f"Found {len(post_id_matches)} consultations with post_id={post_id} "
            f"for ministry '{ministry_note}'; selected URL={consultation.url}"
        )

    return consultation
