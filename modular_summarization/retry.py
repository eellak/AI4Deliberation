"""Retry & truncation heuristics separated from prompts.
Keeps generation-logic concerns isolated for easier testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .config import TARGET_COMPRESSION_RATIO, PUNCTUATION_ENDINGS
from .prompts import get_prompt

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
    """Call `generator_fn` with continuation / shortening retry logic."""
    retries = 0
    while True:
        output = generator_fn(prompt, max_tokens)
        if not _is_truncated(output) or retries >= max_retries:
            return LLMGenerationResult(text=output, truncated=_is_truncated(output), retries=retries)

        # Determine continuation strategy
        continuation_prompt = f"{get_prompt('concise_continuation')}\n{output}"
        max_tokens = int(max_tokens * (1 - TARGET_COMPRESSION_RATIO))
        prompt = continuation_prompt
        retries += 1
