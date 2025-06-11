"""Prompt templates & retry-handling utilities.
Focuses on Stage 1–3 without 2.4–2.6 re-join logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

# ---------------------------------------------------------------------------
# RAW PROMPT TEMPLATES (GREEK)
# ---------------------------------------------------------------------------
STAGE1_PROMPT = (
    "Δημιούργησε μια σύντομη περίληψη (έως 3 προτάσεις) για το παρακάτω άρθρο, χωρίς πρόσθετο σχολιασμό."
)

STAGE2_COHESIVE_PROMPT = (
    "Συνόψισε όλες τις παρακάτω περιλήψεις άρθρων σε ένα συνεκτικό κείμενο που παρουσιάζει το νομοσχέδιο."
)

STAGE2_THEMES_PROMPT = (
    "Κατάγραψε τα κύρια θέματα που επηρεάζουν τους πολίτες, βάσει των παρακάτω περιλήψεων άρθρων."
)

STAGE2_PLAN_PROMPT = (
    "Σκιαγράφησε ένα ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ (6–7 ενότητες) με τίτλο και σύντομη περιγραφή για καθεμία, ακολουθώντας δομή αρχή–μέση–τέλος."
)

STAGE3_EXPOSITION_PROMPT = (
    "Με βάση (1) τη Συνολική Περίληψη, (2) τα Κύρια Θέματα και (3) το Σχέδιο Αφήγησης, συνέθεσε ένα ουδέτερο ενημερωτικό κείμενο."
)

CONCISE_CONTINUATION_PROMPT = (
    "Η απάντησή σας διακόπηκε. Ολοκληρώστε άμεσα την τελευταία πρόταση με ελάχιστες λέξεις:"
)

SHORTENING_CORRECTION_PROMPT = (
    "Η περίληψη είναι υπερβολικά μεγάλη ή ατελής. Δημιουργήστε μια νέα, συντομότερη περίληψη, επικεντρωμένη στα κυριότερα σημεία:"
)

# ---------------------------------------------------------------------------
# PUBLIC REGISTRY & FACTORY
# ---------------------------------------------------------------------------
PROMPTS: Dict[str, str] = {
    "stage1_article": STAGE1_PROMPT,
    "stage2_cohesive": STAGE2_COHESIVE_PROMPT,
    "stage2_themes": STAGE2_THEMES_PROMPT,
    "stage2_plan": STAGE2_PLAN_PROMPT,
    "stage3_exposition": STAGE3_EXPOSITION_PROMPT,
    "concise_continuation": CONCISE_CONTINUATION_PROMPT,
    "shortening_correction": SHORTENING_CORRECTION_PROMPT,
}

def get_prompt(key: str) -> str:
    """Return prompt text; raises KeyError if not found."""
    return PROMPTS[key]

__all__ = list(PROMPTS.keys()) + [
    "PROMPTS",
    "get_prompt",
]

# NOTE: Retry logic moved to `retry.py` to decouple generation heuristics from templates.
