# Single-Stage JSON Polishing – Implementation Plan

This document describes **how we will replace the current two-step polishing
(stylistic critique → revision)** with a _single call_ that produces a structured
JSON payload containing the final readable summary text.  Design principles:

* **Reuse** existing LM-Format-Enforcer (LMFE) plumbing, trace logging, and
  CSV/final-txt export code as much as possible.
* **Keep it small** – remove obsolete critique/revision helpers once the new
  flow is proven.
* **No token-budget micro-optimisation** for now – we allow generous limits.

---
## 1  Prompt & Schema

### 1.1 Prompt constant in `modular_summarization/prompts.py`

```python
CITIZEN_POLISH_PROMPT = """
[SCHEMA:CITIZEN_POLISH_SUMMARY]
Είσαι ένας έμπειρος συντάκτης που αναλαμβάνει να εξηγήσει ένα πολύπλοκο νομοσχέδιο στο ευρύ κοινό.

Η απάντησή σου πρέπει να είναι **ένα και μόνο ένα έγκυρο αντικείμενο JSON** και τίποτα άλλο.

Το αντικείμενο JSON πρέπει να έχει την εξής δομή:
{
  "explanation": "Μια σύντομη εξήγηση της στρατηγικής που θα ακολουθήσεις.",
  "plan": "Ένα σχέδιο σε βήματα για το πώς θα συνθέσεις το κείμενο.",
  "summary_text": "Το τελικό, ευανάγνωστο κείμενο της περίληψης."
}

Οδηγίες για το περιεχόμενο του κάθε πεδίου:
1.  **explanation**: Εξήγησε σύντομα τη στρατηγική σου. Τόνισε ότι ο στόχος είναι η σαφήνεια για το ευρύ κοινό και όχι η νομική ακρίβεια.
2.  **plan**: Περιέγραψε τα βήματα που θα ακολουθήσεις, όπως η ομαδοποίηση ανά θέμα, η αφαίρεση επαναλήψεων και η απλοποίηση της γλώσσας.
3.  **summary_text**: Γράψε το τελικό, ενιαίο κείμενο. Επικεντρώσου στο να είναι ευανάγνωστο, ομαδοποιώντας τις ιδέες λογικά και αποφεύγοντας τους αριθμούς άρθρων και την περιττή νομική ορολογία. Χρησιμοποίησε το «{part_name}» ως υποκείμενο.

Οι παράγραφοι προς επεξεργασία είναι οι εξής:"""
```

– We keep the prompt short; LMFE will append the schema automatically.

### 1.2 JSON schema in `modular_summarization/schemas.py`

```python
CITIZEN_POLISH_SUMMARY_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "summary_text": {"type": "string", "maxLength": 4000}
    },
    "required": ["summary_text"],
    "additionalProperties": false,
}
```

– Only the field we actually need – keeps generation, parsing & storage simple.

### 1.3 Register schema in `llm.get_generator`

Add mapping:
```python
SCHEMA_REGISTRY["CITIZEN_POLISH_SUMMARY"] = CITIZEN_POLISH_SUMMARY_SCHEMA
```

---
## 2 New polishing helper

Create `_single_stage_polish(text: str, part: str, gen_fn) -> tuple[str,str,str]`
inside `scripts/generate_stage2_3_summaries.py` (near previous helper):

1. `prompt = CITIZEN_POLISH_PROMPT.format(part_name=f"ΜΕΡΟΣ {part}") + text`
2. `raw = gen_fn(prompt, max_tokens)`
3. `summary = extract_json_from_text(raw).get("summary_text", "").strip()`
4. Fallback to `text` on failure.
5. Return `(summary, prompt, raw)` for logging.

No extra validator class is needed – reuse `extract_json_from_text` & LMFE.

---
## 3 Integrate into Stage-3 script

1. **Delete** old `_polish_summary` implementation and calls.
2. Add new column names:
   * `citizen_summary_text`  – cleaned string
   * `citizen_raw_json`      – raw model output (optional, helps debugging)
3. Replace logic inside Stage-3 loop:

```python
cit_text, p_prompt, p_raw = _single_stage_polish(summary, part, generator_fn)
_write_trace(polish_fp, f"POLISH {part}", p_prompt, p_raw)
```

4. Append `citizen_summary_text` to CSV; store `cit_text` in
   `final_lines` when `final_source == "polished"`.

5. Update `_export_final_from_stage3` default `source_column` to
   `citizen_summary_text`.

---
## 4 CLI & flags

* Remove `--polish` / `--polish-only` flags; introduce unified
  `--polish-json` (run polishing) and `--polish-json-only` (only polish).
* `--final-source` now accepts `raw` or `polished` (_which now maps to_
  `citizen_summary_text`).

---
## 5 Trace logging

`POLISH {part}` headers remain unchanged.  The body will contain the new prompt
+ raw JSON – so existing log-inspection tooling keeps working.

---
## 6 Clean-up

* Delete `STAGE3_CRITIQUE_PROMPT`, `JOURNALISTIC_POLISH_PROMPT`, related schema
  definitions, and old helper code once migration is complete.
* Remove `polished_text` column from CSV.

---
## 7 Testing checklist

| Test | Expected |
|------|----------|
| `--dry-run --polish-json` | CSV row has `citizen_summary_text`, file not empty |
| Malformed JSON on first try | retry via LMFE, succeed or fall back to original |
| `--export-final-only --final-source polished` | final txt uses new summaries |

---
## 8 Roll-out strategy

1. Implement behind new flags – keep legacy flags for one release as aliases.
2. Back-fill existing Stage-3 CSVs by running `--polish-json-only`.
3. When stable, delete legacy paths.
