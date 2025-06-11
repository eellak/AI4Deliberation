#!/usr/bin/env python3
"""
Section Parser: Extract hierarchical ΜΕΡΟΣ and ΚΕΦΑΛΑΙΟ from article titles.
"""
import sqlite3
import re
import csv
import json
import argparse
import sys
import unicodedata
import importlib.util

# Greek numeral utilities -------------------------------------------------
# Mapping of basic Greek numerals (units and tens) based on the Milesian
# (Greek) numeral system. We explicitly spell out 6 as "ΣΤ" instead of the
# archaic digamma symbol to match how it typically appears in article
# headings.
UNITS_MAP = {
    '': 0,
    'Α': 1, 'Β': 2, 'Γ': 3, 'Δ': 4, 'Ε': 5,
    'ΣΤ': 6,  # 6
    'Ζ': 7, 'Η': 8, 'Θ': 9,
}

TENS_MAP = {
    '': 0,
    'Ι': 10,   # 10-19 will be Ι + <unit>
    'Κ': 20,   # 20-29 → Κ + <unit>
    'Λ': 30,   # etc.
    'Μ': 40,
    'Ν': 50,
    'Ξ': 60,
    'Ο': 70,
    'Π': 80,
    'Ρ': 90,   # rarely used in headings but included for completeness
}

HUNDREDS_MAP = {
    '': 0,
    'Ρ': 100,  # 100
    'Σ': 200,
    'Τ': 300,
    'Υ': 400,
    'Φ': 500,
    'Χ': 600,
    'Ψ': 700,
    'Ω': 800,
}


def int_to_greek(num: int) -> str:
    """Convert an integer (1-999) to a Greek numeral string."""
    if not (1 <= num <= 999):
        raise ValueError("Only numbers 1-999 are supported")

    hundreds = num // 100
    tens_units = num % 100
    tens = tens_units // 10
    units = tens_units % 10

    # build parts
    parts = []
    # hundreds
    for k, v in HUNDREDS_MAP.items():
        if v == hundreds * 100 and k:
            parts.append(k)
            break
    # tens
    for k, v in TENS_MAP.items():
        if v == tens * 10 and k:
            parts.append(k)
            break
    # units – handle 6 (ΣΤ) specially
    for k, v in UNITS_MAP.items():
        if v == units and k:
            parts.append(k)
            break

    return ''.join(parts)


def build_greek_order(max_n: int = 200):
    """Generate an ordered list of Greek numerals up to *max_n*."""
    return [int_to_greek(i) for i in range(1, max_n + 1)]


# Precompute order & lookup for fast index retrieval
GREEK_ORDER = build_greek_order(300)  # supports very large documents
GREEK_TO_INT = {s: i for i, s in enumerate(GREEK_ORDER, start=1)}

# mapping from visually identical ASCII letters to Greek capital equivalents
ASCII_TO_GREEK = str.maketrans({
    'A': 'Α', 'B': 'Β', 'E': 'Ε', 'Z': 'Ζ', 'H': 'Η', 'I': 'Ι', 'K': 'Κ',
    'M': 'Μ', 'N': 'Ν', 'O': 'Ο', 'P': 'Ρ', 'T': 'Τ', 'Y': 'Υ', 'X': 'Χ',
})

# helper to strip accents from Greek text
def strip_accents(text: str) -> str:
    """Return uppercase version of *text* without diacritics (tonos, dialytika)."""
    normalized = unicodedata.normalize('NFD', text)
    without = ''.join(ch for ch in normalized if unicodedata.category(ch) != 'Mn')
    return without.upper()

# quick Levenshtein distance ≤1 checker -------------------------------------------------
def _levenshtein_le1(a: str, b: str) -> bool:
    """Return True if *a* and *b* differ by at most one edit (insert/delete/substitute)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    # ensure a is the shorter
    if len(a) > len(b):
        a, b = b, a
    # check for one substitution
    if len(a) == len(b):
        diff = sum(ch1 != ch2 for ch1, ch2 in zip(a, b))
        return diff == 1
    # check one insert/delete
    for i in range(len(b)):
        if b[:i] + b[i+1:] == a:
            return True
    return False

# ----------------------------------------------------------------------
# Load word-based Greek ordinal mapping (πρώτο, δεύτερο, …) from
# article_parser_utils so we don't duplicate the huge dictionary here.
try:
    _utils_spec = importlib.util.spec_from_file_location(
        "article_parser_utils",
        "/mnt/data/AI4Deliberation/article_extraction_analysis/article_parser_utils.py",
    )
    _utils_mod = importlib.util.module_from_spec(_utils_spec)  # type: ignore
    _utils_spec.loader.exec_module(_utils_mod)  # type: ignore
    WORD_ORDINALS = {strip_accents(k): v for k, v in getattr(_utils_mod, "GREEK_NUMERALS_ORDINAL").items()}
except Exception:
    WORD_ORDINALS = {}
    print("Warning: could not import article_parser_utils -> word ordinals not loaded", file=sys.stderr)

_word_pattern = "|".join(re.escape(k) for k in sorted(WORD_ORDINALS.keys(), key=len, reverse=True)) if WORD_ORDINALS else ""
# Build a single body pattern that matches EITHER a Greek numeral letter (1–3 chars)
# OR any full-word ordinal (πΡΩΤΟ, ΔΕΥΤΕΡΟ, κ.λπ.). This lets one regex handle both forms.
if _word_pattern:
    _BODY_PATTERN_CAP = rf"(([Α-Ω]{{1,3}})|({_word_pattern}))"
else:
    _BODY_PATTERN_CAP = r"([Α-Ω]{1,3})"

# Accept various apostrophe / prime marks that follow Greek numerals (e.g. Α΄, Β')
_PRIME_CHARS = "['’‘΄ʹ]"  # straight apostrophe, smart quotes, Greek tonos \u0384, numeral sign \u0374

# Regex boundary: whitespace, punctuation (: . ; , – · -) or end of string
_AFTER_BOUND = r"\s|[:.;,·\-]|$"

# Regex to match ΜΕΡΟΣ and ΚΕΦΑΛΑΙΟ with optional prime char(s) and boundary
RE_PART = re.compile(rf"(?<![Α-Ω])ΜΕΡΟΣ\s+{_BODY_PATTERN_CAP}(?:\s*{_PRIME_CHARS})?(?={_AFTER_BOUND})", re.IGNORECASE)
RE_CHAPTER = re.compile(rf"(?<![Α-Ω])ΚΕΦΑΛΑΙΟ\s+{_BODY_PATTERN_CAP}(?:\s*{_PRIME_CHARS})?(?={_AFTER_BOUND})", re.IGNORECASE)

# ----------------------------------------------------------------------
# helper: check if a header token (ΜΕΡΟΣ/ΚΕΦΑΛΑΙΟ) appears in an allowed
# leading position. Accept when the token is the very first, **or** the
# second token and the first token is "ΑΡΘΡΟ", **or** the third token and
# the pattern is "ΑΡΘΡΟ <number>".  This covers titles such as
# "Άρθρο ΜΕΡΟΣ Α΄ …" and "Άρθρο 11 ΚΕΦΑΛΑΙΟ ΣΤ΄ …" while still rejecting
# matches appearing later in the sentence (e.g. «στο Μέρος Β΄ του ν. …»).
def _is_header_leading(idx: int, tokens) -> bool:  # tokens already accent-stripped & uppercase
    if idx == 0:
        return True
    if idx == 1 and tokens[0] == "ΑΡΘΡΟ":
        return True
    if idx == 2 and tokens[0] == "ΑΡΘΡΟ" and tokens[1].isdigit():
        return True
    return False

def parse_titles(db_path, consultation_id=None):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    if consultation_id:
        cursor.execute("SELECT id, title, consultation_id FROM articles WHERE consultation_id = ? ORDER BY id", (consultation_id,))
    else:
        cursor.execute("SELECT id, title, consultation_id FROM articles ORDER BY consultation_id, id")
    rows = cursor.fetchall()
    conn.close()

    results = []
    current_part = None
    current_chapter = None
    last_part_idx = None
    last_chap_idx = None
    prev_cid = None

    for article_id, title, c_id in rows:
        # reset tracking when moving to a new consultation -----------------------
        if c_id != prev_cid:
            current_part = None
            current_chapter = None
            last_part_idx = None
            last_chap_idx = None
            prev_cid = c_id

        # normalize apostrophes/tonos to ASCII and collapse whitespace
        title_norm = re.sub(r"[’‘'΄΅]", "'", title)
        title_norm = re.sub(r"\s+", " ", title_norm).strip()
        # replace ASCII look-alike capitals with proper Greek ones for reliable matching
        title_norm = title_norm.translate(ASCII_TO_GREEK)
        title_noacc = strip_accents(title_norm)

        # detect part (Greek numeral or word)
        m_part = RE_PART.match(title_noacc)
        part_letter = None
        if m_part:
            token = strip_accents(m_part.group(1)).upper()
            # token may be Greek numeral letters (Α, Β, …) or word ordinal.
            if token in GREEK_TO_INT:
                part_letter = token
            else:
                idx = WORD_ORDINALS.get(token)
                if idx:
                    part_letter = int_to_greek(idx)
        # fallback to fuzzy detection
        if part_letter is None:
            raw_tokens = [t for t in re.split(r"\W+", title_norm) if t]
            tokens = [strip_accents(t) for t in raw_tokens]
            # attempt quick regex on whole string (strictly at start, allows one missing char after Μ)
            m_after = re.match(r"^\s*Μ.?ΕΡΟΣ\s+([Α-Ω]{1,3})(?=\s|[:.;,·\-]|$)", strip_accents(title_norm))
            if m_after:
                part_letter = m_after.group(1)
            else:
                # scan tokens allowing at most one edit distance from keyword
                for idx, (raw_tok, tok) in enumerate(zip(raw_tokens, tokens)):
                    if _is_header_leading(idx, tokens) and raw_tok == raw_tok.upper() and _levenshtein_le1(tok, "ΜΕΡΟΣ") and idx + 1 < len(tokens):
                        nxt = tokens[idx + 1]
                        if re.fullmatch(r"[Α-Ω]{1,3}", nxt):
                            part_letter = nxt
                            break
        if part_letter:
            if part_letter in GREEK_TO_INT:
                idx = GREEK_TO_INT[part_letter]
                if last_part_idx is not None and idx not in (last_part_idx, last_part_idx + 1):
                    print(f"Warning: non-continuous part sequence: {int_to_greek(last_part_idx)}' -> {part_letter}'", file=sys.stderr)
                last_part_idx = idx
                current_part = part_letter + "'"
                last_chap_idx = None
                current_chapter = None
            else:
                print(f"Unknown part letter: {part_letter}", file=sys.stderr)

        # detect chapter (Greek numeral or word)
        m_ch = RE_CHAPTER.match(title_noacc)
        chap_letter = None
        if m_ch:
            token = strip_accents(m_ch.group(1)).upper()
            if token in GREEK_TO_INT:
                chap_letter = token
            else:
                idx = WORD_ORDINALS.get(token)
                if idx:
                    chap_letter = int_to_greek(idx)
        else:
            # case: chapter appears after a part header in same title (inline)
            if chap_letter is None:
                title_sa = strip_accents(title_norm)
                idx_article = title_sa.find("ΑΡΘΡΟ")
                search_seg = title_sa if idx_article == -1 else title_sa[:idx_article]
                m_ch_inline = re.search(rf"(?<![Α-Ω])ΚΕΦΑΛΑΙΟ\s+{_BODY_PATTERN_CAP}(?={_AFTER_BOUND}|{_PRIME_CHARS})", search_seg, re.IGNORECASE)
                if m_ch_inline:
                    token = strip_accents(m_ch_inline.group(1)).upper()
                    if token in GREEK_TO_INT:
                        chap_letter = token
                    else:
                        idx = WORD_ORDINALS.get(token)
                        if idx:
                            chap_letter = int_to_greek(idx)
        if chap_letter:
            if chap_letter in GREEK_TO_INT:
                idx = GREEK_TO_INT[chap_letter]
                if last_chap_idx is not None and idx not in (last_chap_idx, last_chap_idx + 1):
                    print(f"Warning: non-continuous chapter sequence in part {current_part}: {int_to_greek(last_chap_idx)}' -> {chap_letter}'", file=sys.stderr)
                last_chap_idx = idx
                current_chapter = chap_letter + "'"
            else:
                print(f"Unknown chapter letter: {chap_letter}", file=sys.stderr)

        # assign
        results.append({
            'id': article_id,
            'consultation_id': c_id,
            'title': title,
            'part': current_part,
            'chapter': current_chapter
        })
    return results


def build_summary(results):
    """Group *results* by consultation and run continuity verification for each."""
    from itertools import groupby
    summary = []
    results_sorted = sorted(results, key=lambda r: r['consultation_id'])
    for cid, group_iter in groupby(results_sorted, key=lambda r: r['consultation_id']):
        group_list = list(group_iter)
        problems = verify_continuity(group_list)
        summary.append({
            'consultation_id': cid,
            'status': 'issues' if problems else 'ok',
            'problems': problems,
            'articles': len(group_list)
        })
    return summary


def save_output(results, out_csv, out_json):
    # CSV
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['consultation_id', 'id', 'title', 'part', 'chapter'])
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    # JSON
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def verify_continuity(results):
    """Verify that MERH (parts) and KEFALAIA (chapters) sequences are
    continuous & ascending. Returns list of textual problems found."""
    problems = []

    last_part_idx = 0  # treat None as 0 → previous to Α
    last_chap_idx = 0
    current_part_idx = None

    for row in results:
        part = row['part'][:-1] if row['part'] else None  # strip trailing '
        chapter = row['chapter'][:-1] if row['chapter'] else None

        # handle part change
        if part and (current_part_idx is None or part != int_to_greek(current_part_idx)):
            part_idx = GREEK_TO_INT.get(part)
            if part_idx is None:
                problems.append(f"Unknown part numeral {part} in article id {row['id']}")
                continue
            # first encountered part must be Α (1)
            if last_part_idx == 0 and part_idx != 1:
                problems.append(f"Parts must start from Α but first was {part}")
            # subsequent parts must be +1
            if last_part_idx and part_idx != last_part_idx + 1:
                problems.append(f"Part sequence jump: {int_to_greek(last_part_idx)} -> {part}")
            # reset chapter sequence
            last_chap_idx = 0
            current_part_idx = part_idx
            last_part_idx = part_idx

        # chapter logic (only when chapter present)
        if chapter:
            chap_idx = GREEK_TO_INT.get(chapter)
            if chap_idx is None:
                problems.append(f"Unknown chapter numeral {chapter} in article id {row['id']}")
                continue
            # first chapter within a part must be Α (1)
            if last_chap_idx == 0 and chap_idx != 1:
                problems.append(
                    f"Chapters in part {part or (int_to_greek(current_part_idx) if current_part_idx else 'None')} must start from Α but first was {chapter}")
            # subsequent chapters must be +1 (duplicates allowed when same chapter repeated in consecutive articles)
            if last_chap_idx and chap_idx not in (last_chap_idx, last_chap_idx + 1):
                problems.append(
                    f"Chapter sequence jump in part {part or (int_to_greek(current_part_idx) if current_part_idx else 'None')}: {(int_to_greek(last_chap_idx) if last_chap_idx else 'None')} -> {chapter}")
            last_chap_idx = chap_idx

    return problems


def main():
    parser = argparse.ArgumentParser(description='Parse sections from article titles')
    parser.add_argument('--db', default='/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db', help='Path to SQLite DB')
    parser.add_argument('--consultation', type=int, help='Consultation ID to filter')
    parser.add_argument('--out-csv', default='section_output.csv', help='Output CSV file')
    parser.add_argument('--out-json', default='section_output.json', help='Output JSON file')
    args = parser.parse_args()

    results = parse_titles(args.db, args.consultation)

    # perform continuity verification
    issues = verify_continuity(results)
    if issues:
        print("\nCONTINUITY CHECK FAILED – found the following problems:", file=sys.stderr)
        for p in issues:
            print(f" • {p}", file=sys.stderr)
    else:
        print("Continuity check passed ✓")

    save_output(results, args.out_csv, args.out_json)
    print(f"Saved {len(results)} records to {args.out_csv} and {args.out_json}")

    # when run across all consultations produce consultation-level summary
    if args.consultation is None:
        summary = build_summary(results)
        with open('continuity_report.json', 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        num_issues = sum(1 for s in summary if s['status'] == 'issues')
        print(f"Wrote continuity_report.json  –  {num_issues} consultations with issues")


if __name__ == '__main__':
    main()
