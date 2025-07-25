"""Central configuration constants for modular summarization pipeline.
Adjust values here to fine-tune token limits, compression ratios, etc.
"""
from datetime import datetime

# ---------------------------------------------------------------------------
# MODEL & DEVICE
# ---------------------------------------------------------------------------
DEFAULT_MODEL_ID: str = "google/gemma-4b-it"  # <-- change if needed
TORCH_DTYPE = "bfloat16"  # string to avoid hard torch import here

# ---------------------------------------------------------------------------
# TOKEN BUDGETS PER STAGE (rough defaults – override via kwargs)
# ---------------------------------------------------------------------------
MAX_TOKENS_STAGE1: int = 400   # per-article summary
MAX_TOKENS_STAGE2: int = 400   # per-chapter / cohesive summary
MAX_TOKENS_STAGE3: int = 1600   # per-part exposition
MAX_TOKENS_FINAL:  int = 2_000  # final exposition

# ---------------------------------------------------------------------------
# COMPRESSION SETTINGS
# ---------------------------------------------------------------------------
TARGET_COMPRESSION_RATIO: float = 0.30  # output token count / input token count
MIN_WORDS_FOR_SUMMARY: int = 80         # below this => use original text verbatim

# ---------------------------------------------------------------------------
# CONTEXT WINDOW & TRUNCATION HEURISTICS
# ---------------------------------------------------------------------------
MAX_CONTEXT_TOKENS: int = 8192  # Gemma-7B window (approx.)
# Sentence endings signalling likely completeness – used by retry.py
PUNCTUATION_ENDINGS: tuple[str, ...] = (".", "?", "!", "…", ".”", "?")

# ---------------------------------------------------------------------------
# LOGGING / MISC
# ---------------------------------------------------------------------------
RUN_TIMESTAMP: str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

# Default SQLite columns – update if schema differs
DB_PATH: str = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"
TABLE_NAME: str = "articles"
TITLE_COLUMN: str = "title"
CONTENT_COLUMN: str = "content"

# ---------------------------------------------------------------------------
# REASONING TRACE SETTINGS
# ---------------------------------------------------------------------------
ENABLE_REASONING_TRACE: bool = False  # toggled by CLI or env var
TRACE_OUTPUT_DIR: str = "traces"
TRACE_FILENAME_TEMPLATE: str = "reasoning_trace_c{consultation_id}_{timestamp}.log"

__all__ = [
    "DEFAULT_MODEL_ID",
    "TORCH_DTYPE",
    "MAX_TOKENS_STAGE1",
    "MAX_TOKENS_STAGE2",
    "MAX_TOKENS_STAGE3",
    "MAX_TOKENS_FINAL",
    "TARGET_COMPRESSION_RATIO",
    "MIN_WORDS_FOR_SUMMARY",
    "MAX_CONTEXT_TOKENS",
    "PUNCTUATION_ENDINGS",
    "RUN_TIMESTAMP",
    "DB_PATH",
    "TABLE_NAME",
    "TITLE_COLUMN",
    "CONTENT_COLUMN",
    "ENABLE_REASONING_TRACE",
    "TRACE_OUTPUT_DIR",
    "TRACE_FILENAME_TEMPLATE",
]
