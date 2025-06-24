"""Token/word budget helpers."""
from __future__ import annotations

from typing import Tuple, Dict
from .config import TARGET_COMPRESSION_RATIO, MAX_CONTEXT_TOKENS
import math

__all__ = [
    "length_metrics",
    "desired_tokens",
    "should_split",
    "summarization_budget",
    "dynamic_budget",
]

# --- Heuristics & constants ---------------------------------------------------
_TOKEN_PER_WORD = 0.75  # rough heuristic for *input* text length metrics

# New budgeting defaults
AVG_WORDS_PER_SENTENCE: int = 20
TOKENS_PER_WORD_GEN: float = 2.5  # expected tokens generated per word
OVERSHOOT_RATIO: float = 1.10     # +10 % buffer to avoid early cut-off


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


# -----------------------------------------------------------------------------
# New public helper ------------------------------------------------------------
# -----------------------------------------------------------------------------
def summarization_budget(
    text: str,
    *,
    compression_ratio: float = 0.10,
    avg_words_per_sentence: int = AVG_WORDS_PER_SENTENCE,
    tokens_per_word: float = TOKENS_PER_WORD_GEN,
    overshoot: float = OVERSHOOT_RATIO,
) -> Dict[str, int]:
    """Return budgeting dict for summarisation.

    Parameters
    ----------
    text : str
        Full input text to be summarised.
    compression_ratio : float, optional
        Target output word count as fraction of *original* words (default 0.10 = 10%).
    avg_words_per_sentence : int, optional
        Heuristic average words per sentence (default 20).
    tokens_per_word : float, optional
        Estimated model-generated tokens per word (default 2.5).
    overshoot : float, optional
        Extra safety margin multiplier for token_limit (default +10 %).

    Returns
    -------
    dict with keys ``target_words``, ``target_sentences``, ``token_limit``.
    """
    words = len(text.split())
    target_words = max(1, math.floor(words * compression_ratio))
    target_sentences = max(1, round(target_words / avg_words_per_sentence))
    token_limit = int(math.ceil(target_words * tokens_per_word * overshoot))
    return {
        "target_words": target_words,
        "target_sentences": target_sentences,
        "token_limit": token_limit,
    }

# -----------------------------------------------------------------------------
# New public helper ------------------------------------------------------------
# -----------------------------------------------------------------------------

def dynamic_budget(
    text: str,
    *,
    ratio: float = 0.12,
    variance: float = 0.2,
) -> Dict[str, int]:
    """Return dynamic budgeting dict used by Stage-3/4.

    Parameters
    ----------
    text : str
        Full source text to be summarised.
    ratio : float, optional
        Target compression ratio (default 0.12 ⇒ 12 % of original words).
    variance : float, optional
        Allowed ± variance around the target (default 0.2 = ±20 %).

    Returns
    -------
    dict with ``min_words``, ``max_words``, ``token_limit`` suitable for prompt
    formatting.
    """
    base = summarization_budget(text, compression_ratio=ratio)
    tgt = base["target_words"]
    return {
        "min_words": int(tgt * (1 - variance)),
        "max_words": int(tgt * (1 + variance)),
        "token_limit": base["token_limit"],
    }
