# Stage-1 JSON Reliability Enhancement Plan

_This plan addresses all failure modes observed in the validation report and incorporates your suggestions, improving them where possible._

---

## 1. Support Multiple Modifications per Article

### 1.1 Prompt Updates (Greek)
- Add an explicit note in the `LAW_MOD` *and* `LAW_NEW` classifier prompts:
  > «**Αν το άρθρο επιφέρει περισσότερες από μία μεταβολές, επέστρεψε μια **ΛΙΣΤΑ JSON** με αντικείμενα, ένα για κάθε μεταβολή.** Σε αντίθετη περίπτωση, επέστρεψε ένα **μοναδικό JSON αντικείμενο**.»
- Keep the `[SCHEMA:LAW_MOD]` / `[SCHEMA:LAW_NEW]` tag unchanged so LMFE still routes correctly.

### 1.2 Schema Changes
- Wrap existing object definition in a `definitions.mod` subsection.
- Define a *union* schema that accepts either **object** or **array of objects**:

```python
LAW_MOD_SCHEMA = {
    "oneOf": [
        {"$ref": "#/definitions/mod"},
        {"type": "array", "items": {"$ref": "#/definitions/mod"}}
    ],
    "definitions": {"mod": ORIGINAL_MOD_OBJECT_SCHEMA}
}
```
- Same pattern for `LAW_NEW_SCHEMA`.

### 1.3 Parsing Logic
```python
raw = strip_fence(out)
data = json.loads(raw)
items = data if isinstance(data, list) else [data]
```
Down-stream code can iterate over `items`.

*Benefit*: No information loss – every legislative change is captured.

---

## 2. Token-Budget Improvements

| Current | Issues | Proposal |
|---------|--------|----------|
| `CLASSIFIER_TOKEN_LIMIT = 512` | Truncates long Greek articles → incomplete JSON | (a) **Dynamic budget**: `limit = min(1024, len(article_tokens)*1.2 + 128)`.<br>(b) **Static bump**: 768 or 1024 – safe for Gemma-3 8k context. |

Additional safeguards:
1. Move raw article *after* instructions so truncation affects text, not JSON.
2. Use `model_kwargs={"max_new_tokens": 256}` in classifier path – ensures JSON itself has room.

---

## 3. Retry Strategy & Determinism

**Observation**: With `temperature=0` a second identical prompt usually yields identical output.

### 3.1 Improvements
1. **Fresh restart**: If validation fails, rerun **the same prompt from scratch**. This avoids propagating corruption when the original output never formed a JSON object.
2. **Slight stochasticity on retries**: Keep first pass deterministic (`temperature=0`). For subsequent attempts raise `temperature` to `0.15` and `top_p` to `0.9` so the model explores alternatives.
3. **Error-aware retry limit**: Up to 2 additional attempts; abort early if `jsonschema.validate()` succeeds.

### 3.2 Retry Helper (pseudo-code)
```python
def generate_json_with_retry(gen, prompt, tok_lim, schema, max_tries=3):
    for attempt in range(max_tries):
        temp = 0.0 if attempt == 0 else 0.2
        out = gen(prompt, tok_lim, temperature=temp, top_p=0.9)
        if validates(out, schema):
            return out, attempt
    return out, max_tries
```

---

## 4. Additional Enhancements & Metrics

1. **jsonschema** validation instead of bespoke key checks → rich error messages.
2. **Status column** in Stage-1 CSV (`ok`, `invalid`, `truncated`).
3. **Prometheus counters**: `stage1_schema_failures_total`, `stage1_truncations_total`.
4. **Trace sampling**: upload 1 % of raw prompt/outputs for manual audit.

---

## Critique of Original Proposals

| Original idea | Strength | Suggested refinement |
|---------------|----------|----------------------|
| (a) Prompt says list when multiple changes; parse lists | ✔ Matches real-world articles | Also update schema **and** downstream pipeline to handle N items. Use `oneOf` to stay strict. |
| (b) Higher token limit | ✔ Reduces truncation | Implement dynamic budgeting; keep safety cap at 1024 to avoid runaway cost. |
| (c) Concern about deterministic retries | ✔ Valid | Use **fresh-restart** retries with slight temperature increase so the LLM can diverge; no continuation prompts needed. |

---

### Implementation Order
1. Update schemas & prompt templates ➜ commit.
2. Refactor `parse_law_mod_json` / `parse_law_new_json` ➜ accept list.
3. Implement `generate_json_with_retry` and swap calls in `workflow.py`.
4. Raise / dynamic token limit constant.
5. Deploy and monitor new metrics.
