"""LLM helper utilities for the modular summarizer.

Provides a common `get_generator` function that returns a callable `(prompt:str, max_tokens:int)->str`.
If `dry_run=True` it returns a fast stub generator for CI/testing. Otherwise it will attempt to
lazily load the Gemma-3 model and create a real inference function.  All modules should rely on this
instead of rolling their own loaders or dummy generators.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable
import logging
import os
import json
import re
from threading import local

logger = logging.getLogger(__name__)

# Disable TorchDynamo/Inductor graph compilation to avoid recompile limits in generation loops
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

MODEL_ID = "google/gemma-3-4b-it"

try:
    import torch  # noqa: F401
    from transformers import AutoProcessor, AutoTokenizer, AutoModelForCausalLM  # type: ignore
    try:
        from transformers import Gemma3ForConditionalGeneration  # type: ignore
        _GEMMA_CLASS_AVAILABLE = True
    except Exception:  # pragma: no cover – older transformers
        Gemma3ForConditionalGeneration = None  # type: ignore
        _GEMMA_CLASS_AVAILABLE = False
except Exception as e:  # pragma: no cover – import failure fallback
    Gemma3ForConditionalGeneration = None  # type: ignore
    AutoProcessor = None  # type: ignore
    AutoTokenizer = None  # type: ignore
    AutoModelForCausalLM = None  # type: ignore
    logger.warning("transformers/Gemma3 not available: %s", e)

# ---------------------------------------------------------------------------
# Helper exported for advanced callers
# ---------------------------------------------------------------------------

def get_model_and_tokenizer():  # noqa: D401
    """Return (model, tokenizer) pair if available, loading the model if needed."""
    model, processor = _load_model_and_processor()
    if processor is None:
        return model, None
    tok = getattr(processor, "tokenizer", processor)
    return model, tok

# ---------------------------------------------------------------------------
# Optional LM-Format-Enforcer integration
# ---------------------------------------------------------------------------

# Toggle via env var to enable constrained JSON generation
USE_LMFE = bool(int(os.getenv("USE_LMFE", "1")))  # default ON

try:
    if USE_LMFE:
        from .schemas import (
            LAW_MOD_SCHEMA,
            LAW_NEW_SCHEMA,
            CHAPTER_SUMMARY_SCHEMA,
            PART_SUMMARY_SCHEMA,
            POLISHED_SUMMARY_SCHEMA,
            CITIZEN_POLISH_SUMMARY_SCHEMA,
            NARRATIVE_PLAN_SCHEMA,
            NARRATIVE_SECTION_SCHEMA,
            DRAFT_PARAGRAPHS_SCHEMA,
            STYLISTIC_CRITIQUE_SCHEMA,
        )  # noqa: F401

        from .lmfe_utils import build_prefix_fn  # noqa: F401
        _LMFE_AVAILABLE = True
    else:
        _LMFE_AVAILABLE = False
except Exception as _lmfe_exc:  # pragma: no cover – dependency missing
    _LMFE_AVAILABLE = False
    if USE_LMFE:
        logger.warning("lm-format-enforcer not available: %s – constrained generation disabled", _lmfe_exc)

# Local-thread storage for cached objects
_thread_locals = local()

@lru_cache(maxsize=1)
def _load_model_and_processor():  # noqa: D401 – simple helper
    """Lazily load Gemma-3 and return (model, processor) or (None, None) on failure."""
    if AutoModelForCausalLM is None and Gemma3ForConditionalGeneration is None:
        return None, None
    try:
        logger.info("Loading model: %s", MODEL_ID)
        if Gemma3ForConditionalGeneration is not None and _GEMMA_CLASS_AVAILABLE:
            model = Gemma3ForConditionalGeneration.from_pretrained(
                MODEL_ID,
                device_map="auto",
                torch_dtype=getattr(torch, "bfloat16", torch.float32),
            ).eval()
            processor = AutoProcessor.from_pretrained(MODEL_ID)
        else:
            # Fallback to generic causal LM + tokenizer
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID,
                device_map="auto",
                torch_dtype=getattr(torch, "bfloat16", torch.float32),
            ).eval()
            tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
            # build simple processor-like wrapper for compatibility
            class _TokWrapper:  # noqa: D401
                def __init__(self, tok):
                    self.tokenizer = tok

                def __call__(self, prompt, **kw):
                    # ensure return_tensors='pt' for parity with AutoProcessor
                    kw.setdefault("return_tensors", "pt")
                    kw.setdefault("add_special_tokens", True)
                    return self.tokenizer(prompt, **kw)

            processor = _TokWrapper(tokenizer)

        logger.info("Model loaded successfully (%s parameters).", getattr(model, "num_parameters", lambda: "?")())
        return model, processor
    except Exception as exc:  # pragma: no cover – runtime failures (GPU, etc.)
        logger.error("Failed to load model: %s", exc)
        return None, None


def _stub_generator(prompt: str, max_tokens: int) -> str:  # noqa: D401
    """Return deterministic minimal JSON depending on prompt type for tests/dry-run."""
    if "[SCHEMA:LAW_MOD]" in prompt:
        return json.dumps(
            {
                "law_reference": "ν. 0/0000",
                "article_number": "άρθρο Χ",
                "change_type": "τροποποιείται",
                "major_change_summary": "stub",
                "key_themes": ["stub"],
            },
            ensure_ascii=False,
        )
    elif "[SCHEMA:NARRATIVE_PLAN]" in prompt:
        return json.dumps(
            {
                "overall_narrative_arc": "stub arc",
                "protagonist": "stub protagonist",
                "problem": "stub problem",
                "narrative_sections": [
                    {
                        "section_title": "Ενότητα 1",
                        "section_role": "stub role",
                        "source_chapters": [0, 1],
                    }
                ],
            },
            ensure_ascii=False,
        )
    elif "[SCHEMA:NARRATIVE_SECTION]" in prompt:
        return json.dumps({"current_section_text": "stub section"}, ensure_ascii=False)
    else:
        # Default stub for Stage-2/3 prompts: simple summary wrapper
        return json.dumps({"summary": "stub"}, ensure_ascii=False)


def _build_real_generator() -> Callable[[str, int], str]:
    model, processor = _load_model_and_processor()
    if model is None or processor is None:
        logger.warning("Falling back to stub generator because real model is unavailable.")
        return _stub_generator

    # Import torch lazily (already imported if _load succeeded)
    import torch  # noqa: F401 – needed for type checker

    def _to_inputs(tok, prompt_str):
        return tok(text=prompt_str, return_tensors="pt") if "text" in tok.__call__.__code__.co_varnames else tok(prompt_str, return_tensors="pt")

    def _gemma_generate_plain(prompt: str, max_tokens: int) -> str:  # type: ignore[override]
        # Always use tokenizer for encoding to ensure tensor outputs
        tok = getattr(processor, "tokenizer", processor)
        inputs = tok(prompt, return_tensors="pt").to(model.device)  # type: ignore[arg-type]
        input_len = inputs["input_ids"].shape[1]
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=False,
        )
        gen_only = output_ids[0][input_len:]
        if len(gen_only) == 0:
            gen_only = output_ids[0]
        return tok.decode(gen_only, skip_special_tokens=True)

    # ------------------------------------------------------------------
    # Constrained JSON generation path via LM-Format-Enforcer (preferred)
    # ------------------------------------------------------------------

    if _LMFE_AVAILABLE:

        tokenizer = getattr(processor, "tokenizer", processor)

        def _get_prefix_fn(schema):  # noqa: D401
            key = f"pfx_{id(schema)}"
            fn = getattr(_thread_locals, key, None)
            if fn is None:
                fn = build_prefix_fn(tokenizer, schema)
                setattr(_thread_locals, key, fn)
            return fn

        schema_map = {
            "LAW_MOD": LAW_MOD_SCHEMA,
            "LAW_NEW": LAW_NEW_SCHEMA,
            "CHAPTER_SUM": CHAPTER_SUMMARY_SCHEMA,
            "PART_SUM": PART_SUMMARY_SCHEMA,
            "POLISHED_SUMMARY": POLISHED_SUMMARY_SCHEMA,
            "CITIZEN_POLISH_SUMMARY": CITIZEN_POLISH_SUMMARY_SCHEMA,
            "NARRATIVE_PLAN": NARRATIVE_PLAN_SCHEMA,
            "NARRATIVE_SECTION": NARRATIVE_SECTION_SCHEMA,
            "DRAFT_PARAGRAPHS": DRAFT_PARAGRAPHS_SCHEMA,
            "STYLISTIC_CRITIQUE": STYLISTIC_CRITIQUE_SCHEMA,
        }

        def _gemma_generate_lmfe(prompt: str, max_tokens: int) -> str:  # type: ignore[override]
            # Schema routing via explicit tag
            match = re.match(r"\[SCHEMA:(\w+)\]", prompt)
            if match:
                schema_name = match.group(1)
                schema = schema_map.get(schema_name)
            else:
                schema = None

            if schema is not None:
                pfx_fn = _get_prefix_fn(schema)
            else:
                pfx_fn = None

            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)  # type: ignore[arg-type]
            input_len = inputs["input_ids"].shape[1]
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=False,
                temperature=0.0,
                prefix_allowed_tokens_fn=pfx_fn,
            )
            gen_only = output_ids[0][input_len:]
            return tokenizer.decode(gen_only, skip_special_tokens=True)

        return _gemma_generate_lmfe

    # ------------------------------------------------------------------
    # Fallback to vanilla generation when Jsonformer disabled/unavailable
    # ------------------------------------------------------------------
    return _gemma_generate_plain


def get_generator(*, dry_run: bool = False) -> Callable[[str, int], str]:
    """Return an LLM generation function.

    Parameters
    ----------
    dry_run : bool, default False
        If True, returns a lightweight stub generator (no model loading).
    """
    if dry_run:
        return _stub_generator
    return _build_real_generator()
