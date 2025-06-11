"""Token/word budget helpers."""
from __future__ import annotations

from typing import Tuple

from .config import TARGET_COMPRESSION_RATIO, MAX_CONTEXT_TOKENS

__all__ = ["length_metrics", "desired_tokens", "should_split"]

_TOKEN_PER_WORD = 0.75  # rough heuristic


def length_metrics(text: str) -> Tuple[int, int, int]:
    """Return (tokens, words, sentences) for *text* using heuristics."""
    words = text.split()
    num_words = len(words)
    num_tokens = int(num_words / _TOKEN_PER_WORD)
    sentences = text.count(".") + text.count(";")
    return num_tokens, num_words, max(1, sentences)


def desired_tokens(input_tokens: int) -> int:
    return max(1, int(input_tokens * TARGET_COMPRESSION_RATIO))


def should_split(input_tokens: int, stage: str) -> bool:
    """Return True if we should chunk before summarization due to context window."""
    return input_tokens > MAX_CONTEXT_TOKENS
