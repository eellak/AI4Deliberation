from __future__ import annotations

"""Utility helpers for lm-format-enforcer (LMFE) integration.
Keeps dependency-localised so `llm.py` can import lazily without cluttering.
"""

from typing import Any

try:
    from lmformatenforcer import JsonSchemaParser  # type: ignore
    from lmformatenforcer.integrations.transformers import (
        build_transformers_prefix_allowed_tokens_fn,
    )
except Exception as exc:  # pragma: no cover – optional dependency missing
    raise ImportError("lm-format-enforcer not available: {}".format(exc))

__all__ = ["build_prefix_fn"]


def build_prefix_fn(tokenizer: Any, schema: dict) -> Any:  # noqa: ANN401
    """Return a `prefix_allowed_tokens_fn` callable for HF `.generate`.

    Parameters
    ----------
    tokenizer : PreTrainedTokenizerBase
        The tokenizer associated with the causal LM.
    schema : dict
        A JSON schema dict understood by `JsonSchemaParser`.
    """
    parser = JsonSchemaParser(schema)
    return build_transformers_prefix_allowed_tokens_fn(tokenizer, parser) 