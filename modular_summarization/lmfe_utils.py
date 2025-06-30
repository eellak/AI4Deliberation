from __future__ import annotations

"""Utility helpers for lm-format-enforcer (LMFE) integration.
Keeps dependency-localised so `llm.py` can import lazily without cluttering.
"""

from typing import Any, TYPE_CHECKING

# ---------------------------------------------------------------------------
# Compatibility shim: Transformers ≥4.41 removed `LogitsWarper` class that
# lm-format-enforcer (≤0.10.x) expects during import.  If it is missing, we
# create a lightweight placeholder that simply forwards the logits unchanged.
# This keeps LMFE working without having to pin an older transformers version
# and allows us to keep Gemma support which requires ≥4.50.
# ---------------------------------------------------------------------------

try:
    from transformers.generation.logits_process import LogitsWarper  # type: ignore
except ImportError:  # pragma: no cover – patch only when new transformers
    from transformers.generation.logits_process import LogitsProcessor  # type: ignore
    import sys
    import types
    import torch

    class LogitsWarper(LogitsProcessor):  # type: ignore
        """Minimal stand-in matching the old API expected by lm-format-enforcer.

        It performs no warping – just returns `scores` untouched – but fulfils
        the inheritance check used by Transformers internals, so LMFE can
        subclass it safely (see LogitsSaverWarper inside lm-format-enforcer).
        """

        def __call__(self, input_ids: "torch.LongTensor", scores: "torch.FloatTensor"):  # noqa: ANN401,F821
            return scores

    # Inject into the originating module so that subsequent imports succeed
    _lp_mod = sys.modules.get("transformers.generation.logits_process")
    if _lp_mod is None:
        import transformers.generation.logits_process as _lp_mod  # type: ignore
    setattr(_lp_mod, "LogitsWarper", LogitsWarper)

# ---------------------------------------------------------------------------
# LMFE imports (now safe even on new transformers)
# ---------------------------------------------------------------------------

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