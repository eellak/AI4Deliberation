"""Unit tests for helper functions in law_utils.py"""
from __future__ import annotations

import pytest

from modular_summarization.law_utils import get_summary


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"summary": "Hello"}', 'Hello'),
        ('```json\n{\n  "summary": "Hi there"\n}\n```', 'Hi there'),
        ('Some preface text {"summary": "Inside"} trailing', 'Inside'),
        ('Not JSON at all', None),
        ('{"foo": 123}', None),
    ],
)
def test_get_summary(raw: str, expected: str | None):
    assert get_summary(raw) == expected
