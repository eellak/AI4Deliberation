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

__all__ = [
    "LAW_MOD_SCHEMA",
    "LAW_NEW_SCHEMA",
    "CHAPTER_SUMMARY_SCHEMA",
    "PART_SUMMARY_SCHEMA",
] 