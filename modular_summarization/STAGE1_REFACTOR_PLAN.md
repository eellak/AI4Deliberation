# Stage-1 Refactor — Detailed Technical Plan

> Goal: Simplify Stage-1 so that every article chunk is sent to the LLM only for **one task** – generating a concise JSON summary (`{"summary": "…"}`).  All previous multi-field extraction is dropped.

---
## 1. Prompt Layer  
**Registry note:** Add `LAW_MOD_JSON_PROMPT` and `LAW_NEW_JSON_PROMPT` to the `PROMPT_REGISTRY` dictionary (used by `get_prompt`) so existing lookup helpers continue to work.

| Constant in `prompts.py` | Purpose | Placeholders |
|--------------------------|---------|--------------|
| `LAW_MOD_JSON_PROMPT` | Summarise a *law modification* quotation | `{law_name}`, `{quoted_change}` |
| `LAW_NEW_JSON_PROMPT` | Summarise an article that introduces *new provisions* | – |

Below are the **exact** prompt strings that must be copy-pasted verbatim into `prompts.py`.

```python
# ──────────────────────────────────────────────────────────────
#  LAW_MOD_JSON_PROMPT
# ──────────────────────────────────────────────────────────────
LAW_MOD_JSON_PROMPT = (
    """[SCHEMA:ARTICLE_SUMMARY]
Το παρακάτω κείμενο περιγράφει αλλαγή στον νόμο {law_name}. Δίνεται σε εισαγωγικά η αλλαγή που θα εφαρμοστεί: \"{quoted_change}\". 
Επιστρέφεις **μόνο** έγκυρο JSON με περίληψη της αλλαγής, κανέναν άλλον χαρακτήρα πριν ή μετά:
{
  \"summary\": \"<περίληψη έως 40 λέξεις>\"
}

ΟΔΗΓΙΕΣ ΓΙΑ summary:
- Η πρώτη πρόταση πρέπει να αναφέρει ρητά τον νόμο που τροποποιείται και την αλλαγή που εισάγεται
- Περιέγραψε την ουσία και τον στόχο της αλλαγής (πολιτική, δικαιούχοι, διαδικασία)
- Εξήγησε ΤΙ αλλάζει και ΓΙΑΤΙ είναι σημαντικό
- Μην αναφέρεις κωδικούς ΦΕΚ ή αρίθμηση άρθρων
- Πρέπει να είναι 2-3 προτάσεις σε μήκος

ΠΑΡΑΔΕΙΓΜΑ:
{
  \"summary\": \"Ο νόμος 1234/2023 τροποποιείται ώστε η στήριξη να μετατοπιστεί από αποκλειστικά νεοφυείς επιχειρήσεις σε ευρύτερο καθεστώς ψηφιακού μετασχηματισμού. Η αλλαγή διευρύνει σημαντικά τους δυνητικούς δικαιούχους και επιτρέπει σε περισσότερες επιχειρήσεις να επωφεληθούν από τα μέτρα στήριξης.\"
}

ΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""
)

# ──────────────────────────────────────────────────────────────
#  LAW_NEW_JSON_PROMPT
# ──────────────────────────────────────────────────────────────
LAW_NEW_JSON_PROMPT = (
    """[SCHEMA:ARTICLE_SUMMARY]
Το παρακάτω άρθρο εισάγει νέες διατάξεις, ορισμούς ή ρυθμίσεις χωρίς να τροποποιεί προϋπάρχοντες νόμους.
Επιστρέφεις **μόνο** έγκυρο JSON με περίληψη του άρθρου, κανέναν άλλον χαρακτήρα πριν ή μετά:
{
  \"summary\": \"<περίληψη έως 40 λέξεις>\"
}

ΟΔΗΓΙΕΣ ΓΙΑ summary:
- Η πρώτη πρόταση πρέπει να αναφέρει ρητά το άρθρο και τι νέο θεσπίζει
- Περιέγραψε τι καθιερώνεται/ορίζεται και την πρακτική του σημασία
- Εξήγησε ΠΟΙΟΝ αφορά και ποιος είναι ο σκοπός
- Εστίασε στην ουσία, όχι σε διαδικαστικές λεπτομέρειες
- Πρέπει να είναι 2-3 προτάσεις σε μήκος

ΠΑΡΑΔΕΙΓΜΑ:
{
  \"summary\": \"Το άρθρο καθιερώνει επίσημο λογότυπο για την Ελληνική Αστυνομία με σκοπό την ενιαία ταυτότητα και αναγνωρισιμότητα του Σώματος. Το λογότυπο θα χρησιμοποιείται αποκλειστικά από τις υπηρεσίες της Αστυνομίας, ενισχύοντας την επίσημη εικόνα του οργανισμού.\"
}

ΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""
)
```

---
## 2. JSON Schema & Validation

### 2.1 New schema constant
```python
ARTICLE_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 550},
    },
    "required": ["summary"],
}
```
Set `maxLength` high enough to cover 40-word limit (~550 chars).

### 2.2 Validator helper (`schemas.py` or `validator.py`)  
If you prefer not to create a new file, simply place the helper inside `schemas.py` and re-export it so callers can `from modular_summarization.schemas import validate_article_summary_output`.
```python
def validate_article_summary_output(raw: str) -> list[str]:
    """Return list of schema errors (empty == valid)."""
    return _validate_json_against_schema(raw, ARTICLE_SUMMARY_SCHEMA)
```
Remove `validate_law_mod_output`, `validate_law_new_output`.

---
## 3. Binary Classifier & Prompt Filling

1. **Decide type** (`modifies` vs `new_provision`)
   * Re-use `article_modifies_law()`.

2. **If `modifies`:**
   * **law_name** – first regex match like `Ν.*? \d+/\d{4}` or `νόμος \d+/\d{4}`.
   * **quoted_change(s)** – every quotation of ≥ 10 words: regex `"[^"\n]{80,}"` (≈ 10 Greek words) across the chunk.
   * **Loop**: one LLM call per quotation using `LAW_MOD_JSON_PROMPT`; if none found, fall back to **whole chunk** (trim to 900 tokens before prompt).  
      * When fallback truncation occurs, set `truncated=True` and `orig_chars=<len(text)>` so the CSV records the fact explicitly.

3. **If `new_provision`:**
   * Single call using full article body and `LAW_NEW_JSON_PROMPT`.

4. Each LLM call returns a validated JSON summary string.

---
## 4. `workflow.py` Adjustments

* Delete ~200 lines related to old law_mod/new JSON extraction.
* New processing loop:
  ```python
  decision = "modifies" if article_modifies_law(text) else "new_provision"
  for q in quoted_changes:  # at least once
      key = "LAW_MOD_JSON_PROMPT" if decision == "modifies" else "LAW_NEW_JSON_PROMPT"
      prompt = get_prompt(key).format(law_name=law, quoted_change=q) if decision == "modifies" else get_prompt(key)
      out, retries = generate_json_with_validation(prompt, limit, gen, validate_article_summary_output)
      summary = json.loads(out)["summary"].strip()
      results.append({...})
  ```
* Return value
  ```python
  {
      "article_summaries": [
          {
              "article_id": int,
              "article_number": int | None,
              "classifier_decision": "modifies" | "new_provision",
              "summary_text": str,
              "llm_output": str,
              "prompt": str,
              "retries": int,
          },
          ...
      ]
  }
  ```
* Keep dry-run path intact (continuity checks, markdown dump).

---
## 5. Stage-1 CSV (csv_stage_1.py)

### 5.1 Header
```
consultation_id,article_id,part,chapter,article_number,classifier_decision,truncated,summary_text,raw_prompt,raw_output,retries
```

### 5.2 Writer logic
* `_write_row()` (~30 lines):
  * Writes the new header.
  * Calculates and writes `truncated` boolean (True if fallback chunk was clipped) and optionally `orig_chars` if you keep that extra column.
  * Always succeeds (no `status`, `json_valid`).
  * Keep header string as a constant to ensure consistency between write and append modes.

---
## 6. Stage-2 / Stage-3 Adjustments

* **`stage23_helpers_v2.build_bullet_line`** →
  ```python
  def build_bullet_line(row):
      s = (row.get("summary_text") or "").strip()
      return f"• {s}" if s else None
  ```
* Remove `_fmt_law_mod`, `_fmt_law_new`, `parse_law_*_json`.
* **`csv_stage_2_and3.py::_derive_structures`**: drop branches that examine `classifier_decision`; both types produce the same style bullet.

---
## 7. Code & File Deletions

| File / Symbol | Action |
|---------------|--------|
| `LAW_MOD_SCHEMA`, `LAW_NEW_SCHEMA` | delete |
| `parse_law_mod_json`, `parse_law_new_json` | delete |
| `validate_law_mod_output`, `validate_law_new_output` | delete |
| prompt keys related to old extraction | delete |

---
## 8. Testing & QA

1. **Unit tests**
   * New tests for `validate_article_summary_output` (valid & invalid).
   * Tests for quotation extraction (≥10 words) edge cases.

2. **E2E dry-run**
   * `python scripts/generate_stage1_csvs.py --ids 9 --debug` on stub generator.
   * Verify CSV has new columns and no null summaries.

3. **E2E real model smoke**
   * Run one consultation with real model, confirm JSON summary parsing.

4. **Performance check**
   * Compare token count vs previous pipeline to confirm latency reduction.

---
## 9. Documentation

* Update top-level README and `/docs/pipeline.md` to explain new Stage-1 contract.
* Add changelog entry describing breaking changes.

---
# TODO List (chronological)

> **Tip:** mark each item with `✅` in GitHub issues or a Kanban board as you complete it.

1. **📄 Create new prompt keys** in `prompts.py` with final Greek text.  
2. **📜 Add `ARTICLE_SUMMARY_SCHEMA`** to `schemas.py`; delete old LAW_* schemas.  
3. **🔧 Implement `validate_article_summary_output`** in `validator.py`.  
4. **🧹 Remove obsolete validators & schema imports** throughout codebase.  
5. **🏷️ Refactor `workflow.py`:**
   * a. Purge old law_mod/new branches.  
   * b. Implement quotation-extraction helper.  
   * c. Build new prompt & call validation.  
   * d. Return `article_summaries`.  
6. **🗃️ Rewrite `csv_stage_1.py`:**
   * a. Adjust header.  
   * b. Simplify `_write_row`.  
   * c. Remove `status`/`json_valid`.  
76. **🔨 Update Stage-23 helpers** (no changes needed for truncation flag)
   * a. Replace `build_bullet_line`.  
   * b. Delete unused formatters/parsers.  
8. **📑 Patch `csv_stage_2_and3.py`** to consume the new CSV.  
9. **🗑️ Delete dead functions**  
10. **🔧 Update prompt registry & imports**  
{{ ... }}
12. **🧪 Update unit tests & stub generator**  
    * Add tests to ensure truncation flag is set when long input is clipped.
13. **🚀 Run local dry-run** (`llm.py` stub).  
 on sample consultation; fix regressions.  
14. **🔍 Run real-model smoke test** on small consultation ID.  
15. **📝 Revise documentation & changelog**.  
16. **✅ Code review & merge**.

---
### Estimated Effort
* Core refactor & scripts: **~1.5 days**
* Tests & docs: **0.5 day**

---

*Prepared 30 Jun 2025 14:14 EEST*
