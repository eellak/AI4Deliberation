I. Overall Goal

Evolve the existing Rust text processing script into a performant, reusable Rust library with Python bindings. This library will analyze and clean text extracted from PDFs, identifying and optionally removing "bad" content (glyph artifacts, mojibake outside specified scripts) while preserving user-defined "good" scripts. A normalized "Badness" score will quantify the proportion of bad content relative to recognized good content. Comments (``) will be inserted where significant non-tag content is removed.

II. Core Architectural Changes

    Rust Library Crate: Refactor the current main.rs logic into a Rust library crate structure (src/lib.rs, etc.).
    Python Module Interface: Create Python bindings using PyO3, exposing the library's core functionality. The module might be named text_cleaner or similar.

III. Script/Character Management

    Rust Definition:
        Maintain the use of lazy_static for defining character sets.
        Define multiple HashSet<char> instances for various scripts, character types, and symbols. Examples:
            LATIN_BASIC: HashSet<char> (a-zA-Z)
            GREEK: HashSet<char> (Modern Greek, including accents)
            ANCIENT_GREEK: HashSet<char> (Polytonic Greek characters, if needed separately)
            FRENCH_ACCENTED: HashSet<char> (àâçéèêëîïôùûüÿæœ, etc.)
            COMMON_PUNCTUATION: HashSet<char> (.,;:!?()[]{}'"%...)
            DIGITS: HashSet<char> (0-9)
            UNUSUAL_CHARS: HashSet<char> (Characters likely resulting from encoding errors or OCR issues, carefully curated to exclude characters from the common "good" scripts defined above).
        Store these sets in a central lazy_static HashMap<String, HashSet<char>>. Keys will be three-letter lowercase strings (inspired by Tesseract/ISO 639-2 codes where applicable, but customizable):
            Example keys: "lat", "gre", "grc" (for ancient), "fra" (combining basic Latin + French accented?), "spa", "punct", "num". The exact keys and corresponding sets need careful definition based on expected document content.

    Python Selection:
        The Python functions (analyze, clean) will accept a scripts_to_keep: list[str] argument (e.g., ["gre", "lat", "num", "punct"]).

    Dynamic AllowedChars Set:
        In Rust, for each function call, iterate through the scripts_to_keep list provided by Python.
        Look up each script code in the central HashMap.
        Unite the corresponding HashSet<char>s into a single temporary AllowedChars: HashSet<char> for that operation. Handle potential errors if an unknown script code is passed from Python.

IV. Badness Metric Calculation (within analyze function)

    Formula: Badness = BadCount / (BadCount + GoodCount)
    Zero Denominator Handling: If (BadCount + GoodCount) == 0, return Badness = 0.0.
    Initialization: BadCount = 0, GoodCount = 0.
    Iteration: Process the input text character by character (or token by token where appropriate for glyph words).
    GoodCount Logic:
        If a character c is present in the AllowedChars set for the current call, increment GoodCount += 1.
    BadCount Logic:
        Glyph Words: Use GLYPH_WORD_REGEX.find_iter(): For each match m, increment BadCount += m.as_str().chars().count(). Ensure these characters are not double-counted by the unusual char logic below. Skip ahead in the main iteration past the glyph word.
        Unusual Characters: If a character c is NOT part of a glyph word match AND c is present in the UNUSUAL_CHARS set AND c is NOT present in the AllowedChars set, increment BadCount += 1.
    Exclusions from Counts:
        Tags: Matches of ANY_TAG_CLEANING_REGEX (excluding comments) are ignored entirely for BadCount and GoodCount. The iteration should skip over tag content when calculating these counts.
        Whitespace: Whitespace characters are ignored for both counts.
    Return Value: The analyze function returns a dictionary (or Python object) including {"badness": Badness, "bad_count": BadCount, "good_count": GoodCount, ... potentially other raw stats}.

V. Cleaning Logic (within clean function)

    Processing: Process the input text, likely line by line or segment by segment, to manage comment insertion state.
    Removal Actions:
        Glyph Words: Remove text matching GLYPH_WORD_REGEX. Keep track of the number of characters removed per line/segment for comment logic.
        Unusual Characters: Remove characters c where c is in UNUSUAL_CHARS AND c is NOT in AllowedChars. Keep track of the number of characters removed per line/segment.
        Tags: Remove text matching ANY_TAG_CLEANING_REGEX, unless it matches COMMENT_REGEX (preserve existing valid comments). Tag removal does not trigger the `` comment insertion logic.
    Comment Insertion Logic:
        Trigger: A comment `` should be considered for insertion on a line/segment if one or more characters were removed due to the Glyph Word or Unusual Character rules above during the processing of that line/segment.
        Condition: Insert the comment if:
            The trigger condition is met.
            A minimum number of characters (e.g., 5, configurable?) were removed from glyphs/unusuals on that line/segment.
            The line/segment is not completely empty after all removals (including tags).
            A `` comment wasn't already added immediately preceding this position or on the same line due to a prior removal in the same segment (avoid duplicate adjacent comments). Handle cases where the entire line becomes empty due to significant removal – insert the comment on its own line.
        Placement: Append the comment to the end of the modified line/segment, separated by a space, unless the line became empty (then place it alone).
    Return Value: The clean function returns the modified text string.

VI. What Stays Similar (Evolution, Not Revolution)

    Core Data Structures: HashSet<char> for character sets, Regex for pattern matching.
    Performance: lazy_static for regex/set initialization, rayon for parallel processing if handling batches of texts/files remains relevant in the library context.
    Regex Definitions: The fundamental patterns in GLYPH_WORD_REGEX, ANY_TAG_CLEANING_REGEX, COMMENT_REGEX etc., remain valid starting points.
    Modularity Concept: The original code already separates analysis and cleaning to some extent; this specification formalizes it into a library structure.
    Make sure to add a comment """<!-- text-missing -->""" whenever text is removed.