"""Regression tests for dry-run hierarchy generation."""
from pathlib import Path
import re
import importlib
import pytest
import sqlite3
from modular_summarization.workflow import run_workflow
from modular_summarization.hierarchy_parser import BillHierarchy
from modular_summarization import config as _cfg

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def _detect_db() -> Path:
    """Return path to SQLite DB or skip tests if not found."""
    candidates = list(Path("/mnt/data/AI4Deliberation").glob("*.db"))
    if not candidates:
        pytest.skip("No .db file found – skipping dry-run tests", allow_module_level=True)
    return candidates[0]

def _sample_consultation_ids(db_path: Path, limit: int = 2):
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT consultation_id FROM articles ORDER BY consultation_id LIMIT ?", (limit,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

# --------------------------------------------------------------------
# Fixtures / globals
# --------------------------------------------------------------------

DB_PATH = _detect_db()

# Patch config DB_PATH for runtime modules
_cfg.DB_PATH = str(DB_PATH)

# Import legacy parser after patch so it picks updated path when called
sp = importlib.import_module("section_parser.section_parser")

CONSULTATION_IDS = _sample_consultation_ids(DB_PATH)

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------

def _hierarchy_to_indent_txt(h: BillHierarchy) -> str:
    lines = []
    for p in h.parts:
        lines.append(f"ΜΕΡΟΣ {p.name}")
        for ch in p.chapters:
            lines.append(f"  ΚΕΦΑΛΑΙΟ {ch.name}")
            for art in ch.articles:
                lines.append(f"    ΑΡΘΡΟ {art.id}: {art.title}")
    return "\n".join(lines)

@pytest.mark.parametrize("cid", CONSULTATION_IDS)
def test_dry_run_hierarchy(cid):
    """Dry-run workflow & continuity checks for real consultations."""
    # Section parser continuity -------------------------------------------------
    rows = sp.parse_titles(str(DB_PATH), cid)
    problems = sp.verify_continuity(rows)
    assert not problems, f"Continuity issues for consultation {cid}: {problems}"

    # Build hierarchy object for additional structure validation ---------------
    h = BillHierarchy.from_db_rows(rows)
    assert h.parts, "No parts built"

    # Ensure ascending article IDs across hierarchy ----------------------------
    prev_id = 0
    for p in h.parts:
        for ch in p.chapters:
            for art in ch.articles:
                assert art.id > prev_id, "Article IDs not ascending"
                prev_id = art.id

    # workflow dry-run ---------------------------------------------------------
    res = run_workflow(cid, dry_run=True, db_path=str(DB_PATH))
    md = res["dry_run_markdown"]
    assert "# Dry-Run" in md

    # Save human-readable artifacts
    (OUT_DIR / f"{cid}_hierarchy.md").write_text(md, encoding="utf-8")
    (OUT_DIR / f"{cid}_hierarchy.txt").write_text(_hierarchy_to_indent_txt(h), encoding="utf-8")
