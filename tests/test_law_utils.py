"""Quick tests for article modification detection logic in law_utils.
Run via:
    python -m pytest -q tests/test_law_utils.py
or simply:
    python tests/test_law_utils.py
"""

import sys
from pathlib import Path
import textwrap

# Ensure project root is on sys.path when running tests directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import json

from modular_summarization.law_utils import article_modifies_law

# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        (
            textwrap.dedent(
                """
                Με βάση τον Ν. 4887/2022, «Η ισχύς του άρθρου 5 επεκτείνεται σε...». Το παρόν άρθρο ...
                """
            ),
            True,
        ),
        (
            textwrap.dedent(
                """
                «Η ισχύς του άρθρου 5 επεκτείνεται σε...». Η τροποποίηση αφορά τον Ν. 4887/2022.
                """
            ),
            False,  # quote precedes law reference
        ),
        (
            "Δεν υπάρχει καμία αναφορά σε προηγούμενο νόμο σε αυτό το κείμενο.",
            False,
        ),
    ],
)
def test_article_modifies_law(text: str, expected: bool):
    assert article_modifies_law(text) is expected


if __name__ == "__main__":
    # Simple CLI runner
    for sample in [
        "Με βάση τον Ν. 4887/2022, «Η ισχύς του άρθρου 5 επεκτείνεται σε...».",
        "«Η ισχύς του άρθρου 5 επεκτείνεται σε...». Η τροποποίηση αφορά τον Ν. 4887/2022.",
        "Απλό άρθρο χωρίς καμία αναφορά.",
    ]:
        print("-" * 40)
        print(sample)
        print("modifies_law:", article_modifies_law(sample))
