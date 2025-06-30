LAW_MOD_SCHEMA = {
    "type": "object",
    "properties": {
        "law_reference": {"type": "string"},
        "article_number": {"type": "string"},
        "change_type": {
            "type": "string",
            "enum": [
                "τροποποιείται",
                "καταργείται",
                "αντικαθίσταται",
                "προστίθεται",
                "συμπληρώνεται",
                "διαγράφεται",
            ],
        },
        "major_change_summary": {"type": "string", "maxLength": 550},
        "key_themes": {
            "type": "array",
            "items": {
                "type": "string",
                "pattern": r"[a-z0-9]+(_[a-z0-9]+)*",
            },
            "minItems": 1,
            "maxItems": 3,
        },
    },
    "required": [
        "law_reference",
        "article_number",
        "change_type",
        "major_change_summary",
        "key_themes",
    ],
}

LAW_NEW_SCHEMA = {
    "type": "object",
    "properties": {
        "article_title": {"type": "string"},
        "provision_type": {
            "type": "string",
            "enum": [
                "ορισμός",
                "σκοπός",
                "αρμοδιότητες",
                "διαδικασία",
                "οργάνωση",
                "ρύθμιση",
                "διάρθρωση",
            ],
        },
        "core_provision_summary": {"type": "string", "maxLength": 550},
        "key_themes": {
            "type": "array",
            "items": {
                "type": "string",
                "pattern": r"[a-z0-9]+(_[a-z0-9]+)*",
            },
            "minItems": 1,
            "maxItems": 3,
        },
    },
    "required": [
        "article_title",
        "provision_type",
        "core_provision_summary",
        "key_themes",
    ],
}

# ---------------------------------------------------------------------------
# Stage-2 / Stage-3 summary schemas (single-field for now)
# ---------------------------------------------------------------------------
CHAPTER_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 2000},
    },
    "required": ["summary"],
}

PART_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 3000},
    },
    "required": ["summary"],
}

# ---------------------------------------------------------------------------
# New Stage-1 single-field article summary schema
# ---------------------------------------------------------------------------
ARTICLE_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 550},
    },
    "required": ["summary"],
}

# ---------------------------------------------------------------------------
# Polished summary schema (legacy)
# ---------------------------------------------------------------------------
POLISHED_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "polished_text": {"type": "string", "maxLength": 2800},
    },
    "required": ["polished_text"],
}

# ---------------------------------------------------------------------------
# New single-stage citizen polish schema
# ---------------------------------------------------------------------------
CITIZEN_POLISH_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string", "maxLength": 1200},
        "plan": {"type": "string", "maxLength": 1500},
        "summary_text": {"type": "string", "maxLength": 3000},
    },
    "required": ["explanation", "plan", "summary_text"],
}
# ---------------------------------------------------------------------------
# New Stage-3/4 Draft & Polishing Schemas
# ---------------------------------------------------------------------------
DRAFT_PARAGRAPHS_SCHEMA = {
    "type": "object",
    "properties": {
        "draft_paragraphs": {
            "type": "array",
            "maxItems": 25,
            "items": {
                "type": "object",
                "properties": {
                    "paragraph_index": {"type": "integer", "minimum": 0},
                    "text": {"type": "string", "maxLength": 700},
                },
                "required": ["paragraph_index", "text"],
            },
        }
    },
    "required": ["draft_paragraphs"],
}

STYLISTIC_CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "suggested_edits": {
            "type": "array",
            "maxItems": 15,
            "items": {
                "type": "object",
                "properties": {
                    "original_phrase": {"type": "string", "maxLength": 120},
                    "issue": {"type": "string", "maxLength": 60},
                    "suggestion": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 120},
                    },
                },
                "required": ["original_phrase", "issue", "suggestion"],
            },
        }
    },
    "required": ["suggested_edits"],
}
# ---------------------------------------------------------------------------
# Stage-3 Expanded: Narrative Planning Schemas
# ---------------------------------------------------------------------------
NARRATIVE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_narrative_arc": {"type": "string", "maxLength": 300},
        "protagonist": {"type": "string", "maxLength": 150},
        "problem": {"type": "string", "maxLength": 300},
        "narrative_sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_title": {"type": "string", "maxLength": 100},
                    "section_role": {"type": "string", "maxLength": 250},
                    "source_chapters": {
                        "type": "array",
                        "items": {"type": "string", "pattern": "kefalaio_[0-9]+"},
                        "minItems": 1,
                        "maxItems": 10,
                    },
                },
                "required": ["section_title", "section_role", "source_chapters"],
            },
            "minItems": 1,
            "maxItems": 8,
        },
    },
    "required": ["overall_narrative_arc", "protagonist", "problem", "narrative_sections"],
}

NARRATIVE_SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "current_section_text": {"type": "string", "maxLength": 800},
    },
    "required": ["current_section_text"],
}

__all__ = [
    "LAW_MOD_SCHEMA",
    "LAW_NEW_SCHEMA",
    "CHAPTER_SUMMARY_SCHEMA",
    "PART_SUMMARY_SCHEMA",
    "POLISHED_SUMMARY_SCHEMA",
    "NARRATIVE_PLAN_SCHEMA",
    "NARRATIVE_SECTION_SCHEMA",
    "DRAFT_PARAGRAPHS_SCHEMA",
    "STYLISTIC_CRITIQUE_SCHEMA",
] 