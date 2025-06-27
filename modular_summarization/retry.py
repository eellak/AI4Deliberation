"""Retry & truncation heuristics separated from prompts.
Keeps generation-logic concerns isolated for easier testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .config import PUNCTUATION_ENDINGS

__all__ = ["LLMGenerationResult", "generate_with_retry"]


@dataclass
class LLMGenerationResult:
    text: str
    truncated: bool = False
    num_tokens: int | None = None
    retries: int = 0


def _is_truncated(text: str) -> bool:
    """Simple heuristic: missing ending punctuation or trailing ellipsis."""
    stripped = text.rstrip()
    return not stripped.endswith(PUNCTUATION_ENDINGS)


def generate_with_retry(
    generator_fn: Callable[[str, int], str],
    prompt: str,
    max_tokens: int,
    max_retries: int = 2,
) -> LLMGenerationResult:
    """Deprecated wrapper kept for backward compatibility.

    Fresh-restart retries using *validator.generate_plain_with_retry* under the hood.
    Continuation prompt logic has been removed."""

    Uses a simple truncation heuristic to decide if the model response is
    incomplete and, if so, asks the model to continue up to `max_retries`
    times.  This helper is generic and may be reused by other workflows that
    still need automatic continuation.
    """
    from .validator import generate_plain_with_retry

    out_text, retries, trunc = generate_plain_with_retry(
        prompt,
        max_tokens,
        generator_fn,
        max_retries=max_retries,
    )
    return LLMGenerationResult(text=out_text, truncated=trunc, retries=retries)
