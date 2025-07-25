"""Regression test ensuring SageMaker generator obeys LM-Format-Enforcer
JSON-schema constraints 100 % of the time.

The test is skipped automatically when the SageMaker endpoint is not
configured (e.g. in CI without AWS credentials).
"""
from __future__ import annotations

import json
import os
import logging
from typing import Callable

import pytest

from pathlib import Path
import sys

# ---------------------------------------------------------------------------
# Ensure project root on PYTHONPATH so modular_summarization resolves
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from modular_summarization.sagemaker_llm import (
    get_sagemaker_generator,
    _TAG_TO_SCHEMA,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper – very light custom validators for a couple of schemas.
# We purposely avoid bringing in the heavy ``jsonschema`` dependency; instead
# we do minimal key checks that are enough to catch malformed output.
# ---------------------------------------------------------------------------

def _validate_chapter_sum(obj: dict) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("summary"), str) and obj["summary"].strip() != ""

def _validate_part_sum(obj: dict) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("summary"), str)

_SCHEMA_VALIDATORS: dict[str, Callable[[dict], bool]] = {
    "CHAPTER_SUM": _validate_chapter_sum,
    "PART_SUM": _validate_part_sum,
}


@pytest.mark.parametrize("schema_tag", ["CHAPTER_SUM", "PART_SUM"])
def test_sagemaker_schema_enforcement(schema_tag: str) -> None:
    """Ensure zero schema violations when hitting the SageMaker endpoint.

    The test is skipped automatically when either:
    1. No SageMaker generator can be instantiated (no env-vars / deps)
    2. The endpoint itself is unreachable (invalid name, network, etc.)
    """

    from modular_summarization.sagemaker_llm import test_sagemaker_connection

    gen = get_sagemaker_generator()
    if gen is None:
        pytest.skip("SageMaker generator unavailable – set SAGEMAKER_ENDPOINT_NAME")

    if not test_sagemaker_connection():
        pytest.skip("SageMaker endpoint unreachable – skipping schema test")

    validator = _SCHEMA_VALIDATORS[schema_tag]
    prompt = f"[SCHEMA:{schema_tag}] Compliance test prompt"

    iterations = 10
    violations = 0

    for _ in range(iterations):
        output = gen(prompt, max_tokens=512)
        try:
            parsed = json.loads(output)
        except Exception:
            violations += 1
            continue

        if not validator(parsed):
            violations += 1

    assert violations == 0, (
        f"{violations}/{iterations} generations violated the {schema_tag} schema"
    )

