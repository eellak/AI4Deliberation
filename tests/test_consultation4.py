import json
import sys
from pathlib import Path
import importlib
import pytest

# Ensure project root is importable when tests run directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modular_summarization.workflow import run_workflow  # noqa: E402
from modular_summarization import config as _cfg  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

DB_CANDIDATES = list(Path("/mnt/data/AI4Deliberation").glob("*.db"))

if not DB_CANDIDATES:
    pytest.skip("No DB found in /mnt/data/AI4Deliberation – skipping consultation4 test", allow_module_level=True)

DB_PATH = DB_CANDIDATES[0]
_cfg.DB_PATH = str(DB_PATH)

CONSULTATION_ID = 4

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _has_valid_json(output_list):
    """Return True if every item in *output_list* has non-None 'parsed'."""
    return all(item.get("parsed") for item in output_list)


def test_consultation4_json_validity(monkeypatch):
    """Run Stage-1 workflow on consultation 4 with stub generator and ensure 100 % JSON validity."""

    # Ensure stub generator by forcing dry_run=True in get_generator
    from modular_summarization.llm import get_generator  # noqa: E402

    dummy_gen = get_generator(dry_run=True)

    res = run_workflow(
        consultation_id=CONSULTATION_ID,
        dry_run=False,  # we want Stage-1 path executed
        db_path=str(DB_PATH),
        generator_fn=dummy_gen,
    )

    assert _has_valid_json(res.get("law_modifications", [])), "Invalid JSON in law_modifications"
    assert _has_valid_json(res.get("law_new_provisions", [])), "Invalid JSON in law_new_provisions" 