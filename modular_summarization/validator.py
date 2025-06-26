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
# Generic JSON-schema validator helpers
# ---------------------------------------------------------------------------

try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover
    jsonschema = None  # handled at runtime


def validate_schema(data, schema):
    """Return list[str] of validation errors (empty if valid)."""
    if jsonschema is None:
        return []  # skip if library not present (should not happen in prod)
    try:
        jsonschema.validate(data, schema)
        return []
    except jsonschema.ValidationError as e:  # type: ignore[attr-defined]
        return [e.message]


# ---------------------------------------------------------------------------
# Law-specific JSON validators --------------------------------------------------
from . import schemas as _schemas
from .law_utils import parse_law_mod_json, parse_law_new_json


def validate_law_mod_output(text: str) -> list[str]:
    """Return errors if *text* does not conform to LAW_MOD_SCHEMA (or list)."""
    objs = parse_law_mod_json(text)
    if objs is None:
        return ["not_valid_json"]
    errors: list[str] = []
    for idx, obj in enumerate(objs):
        errs = validate_schema(obj, _schemas.LAW_MOD_SCHEMA)
        if errs:
            errors.append(f"item_{idx}:{'|'.join(errs)}")
    return errors


def validate_law_new_output(text: str) -> list[str]:
    """Return errors if *text* does not conform to LAW_NEW_SCHEMA (or list)."""
    objs = parse_law_new_json(text)
    if objs is None:
        return ["not_valid_json"]
    errors: list[str] = []
    for idx, obj in enumerate(objs):
        errs = validate_schema(obj, _schemas.LAW_NEW_SCHEMA)
        if errs:
            errors.append(f"item_{idx}:{'|'.join(errs)}")
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
    """Call *gen_fn* with *prompt* and JSON-schema validation.

    Behaviour changes (2025-06-26):
    1. *Temperature control*: first attempt uses ``cfg.INITIAL_TEMPERATURE`` (0.01).
    2. *Sampling parameters per attempt*: first attempt uses ``cfg.INITIAL_TOP_P`` (0.95), subsequent attempts use ``cfg.RETRY_TOP_P`` (0.9)
    3. *Skip non-schema prompts*: if the *prompt* does **not** contain a
       ``[SCHEMA:`` tag we execute **one** generation (no retries) because there
       is nothing to validate against.
    4. Maximum of *max_retries* attempts (default 2 = 1 primary + 1 retry).

    Returns ``(output:str, retries:int)`` where *retries* is the number of extra
    attempts performed after the first call.
    """
    from . import config as cfg  # local import to avoid cycles during tests

    # Fast path – plain-text prompt, no validation possible ------------------
    if "[SCHEMA:" not in prompt:
        cfg.CURRENT_TEMPERATURE = cfg.INITIAL_TEMPERATURE
        return gen_fn(prompt, max_tokens), 0

    last_errs: List[str] | None = None
    for attempt in range(max_retries + 1):
        # Sampling parameters per attempt -----------------------------------
        is_first = attempt == 0
        cfg.CURRENT_TEMPERATURE = cfg.INITIAL_TEMPERATURE if is_first else cfg.RETRY_TEMPERATURE
        cfg.CURRENT_TOP_P = cfg.INITIAL_TOP_P if is_first else cfg.RETRY_TOP_P
        out = gen_fn(prompt, max_tokens)
        errs = validator_fn(out, *validator_args) if callable(validator_fn) else []
        if not errs:
            return out, attempt
        last_errs = errs
    raise ValueError("Validation failed after retries: " + "; ".join(last_errs or []))
