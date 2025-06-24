"""Utilities for validating LLM JSON outputs used in Stage-3.

The goal is to *fail fast* on malformed or semantically-invalid outputs so that
higher-level orchestrators can trigger retry logic before falling back to the
legacy one-shot summariser.

Design principles
-----------------
* **Pure functions** – no external state so they can be unit-tested easily.
* **Lax parsing** – rely on upstream LM-Format-Enforcer to deliver *syntactic*
  JSON.  We still guard against truncation (empty / None) and semantic errors
  (unknown chapter keys).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence, Set, Tuple
import logging

_log = logging.getLogger(__name__)

_JSON = Dict[str, Any]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def extract_json(text: str) -> _JSON:
    """Return the first JSON object found or raise *ValueError*.

    We purposefully **do not** try fancy repairs here – that logic lives in
    *stage3_expanded.extract_json_from_text*.  This util should be used **after**
    that function when we already believe we have a JSON string.
    """
    try:
        return json.loads(text)
    except Exception as e:  # pragma: no cover – unified handling
        raise ValueError(f"Not valid JSON: {e}") from e


# ---------------------------------------------------------------------------
# Narrative-plan specific validation
# ---------------------------------------------------------------------------

REQ_TOP_KEYS: Set[str] = {
    "overall_narrative_arc",
    "protagonist",
    "problem",
    "narrative_sections",
}
REQ_SECTION_KEYS: Set[str] = {"section_title", "section_role", "source_chapters"}


def validate_narrative_plan(plan: _JSON, allowed_keys: Sequence[str]) -> List[str]:
    """Return *error list*; empty means *plan* passes checks."""

    errors: List[str] = []

    # 1. Basic shape ---------------------------------------------------------
    missing = REQ_TOP_KEYS - plan.keys()
    if missing:
        errors.append(f"Missing top-level keys: {sorted(missing)}")
        # Can't continue further if core keys absent.
        return errors

    if not isinstance(plan["narrative_sections"], list) or not plan["narrative_sections"]:
        errors.append("narrative_sections must be a non-empty list")
        return errors

    # 2. Per-section checks --------------------------------------------------
    for idx, sec in enumerate(plan["narrative_sections"]):
        if not isinstance(sec, dict):
            errors.append(f"Section {idx} is not a JSON object")
            continue
        missing_sec = REQ_SECTION_KEYS - sec.keys()
        if missing_sec:
            errors.append(f"Section {idx} missing keys: {sorted(missing_sec)}")
            continue
        if not isinstance(sec["source_chapters"], list):
            errors.append(f"Section {idx} source_chapters not list")
            continue

        # Normalise chapter references ----------------------------------
        normalised_chapters: List[str] = []
        for ch in sec["source_chapters"]:
            if isinstance(ch, int):
                errors.append(
                    f"Section {idx} has numeric chapter reference {ch}; πρέπει να χρησιμοποιήσεις μορφή 'kefalaio_N'"
                )
            elif isinstance(ch, str):
                normalised_chapters.append(ch)
            else:
                errors.append(
                    f"Section {idx} has invalid chapter reference type: {type(ch).__name__}"
                )

        # Check against allowed keys -------------------------------------
        unknown = [k for k in normalised_chapters if k not in allowed_keys]
        if unknown:
            if len(unknown) == len(normalised_chapters):
                # Every reference invalid – real error
                errors.append(
                    f"Section {idx} references only unknown chapter keys: {unknown}"
                )
            else:
                # Partial mismatch – keep valid ones but log warning
                _log.warning(
                    "Section %s has some unknown chapter keys that will be ignored: %s",
                    idx,
                    unknown,
                )

    return errors


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def generate_with_validation(
    prompt: str,
    max_tokens: int,
    gen_fn,
    validator_fn,
    validator_args: Tuple[Any, ...] = (),
    max_retries: int = 2,
):
    """Call *gen_fn* with *prompt* until *validator_fn* returns no errors.

    Returns tuple *(output:str, retries:int).*  Raises *ValueError* if all tries
    fail.
    """
    last_errs: List[str] | None = None
    for attempt in range(max_retries + 1):
        out = gen_fn(prompt, max_tokens)
        errs = validator_fn(out, *validator_args) if callable(validator_fn) else []
        if not errs:
            return out, attempt
        last_errs = errs
    raise ValueError("Validation failed after retries: " + "; ".join(last_errs or []))
