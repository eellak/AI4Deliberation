# TODO – Stage 3 Expansion: Multi-step Narrative Summarisation

*Last updated: 2025-06-18*

This document captures the implementation plan for replacing the current one-shot **Stage 3** part-level summarisation with a two-sub-stage workflow:

* **Sub-stage 3.1 – Narrative Planning**  ("Stage 1" in the pseudocode)
* **Sub-stage 3.2 – Chunk Synthesis**      ("Stage 2" in the pseudocode)

The new design produces a coherent, compressed narrative by first asking the LLM to return a *Narrative Plan* and then generating one paragraph per `αφηγηματική_ενότητα` defined in that plan.

---

## 1  Current implementation vs. new design

| Concern                              | Current code                                                        | New workflow                                                   |
|--------------------------------------|---------------------------------------------------------------------|----------------------------------------------------------------|
| Chapter input                        | `chapter_summaries: List[str]` from Stage-2 CSV                    | Same list, **indexed** so that story beats can reference chapters via `List[int]` in `πηγές_κεφαλαίων`. |
| Skopos / Antikeimeno                 | Passed as `intro_lines: List[str]` (0 = Skopos, 1 = Antikeimeno).  | Same texts, but **optional**; their presence selects Prompt A, absence selects Prompt B. |
| Prompt                               | Single template `stage3_part`                                      | Two planning templates (A/B) **plus** one synthesis template. |
| Output                               | One markdown paragraph                                             | Multi-paragraph final string assembled from JSON planning + synthesis loop. |
| Code surface                         | `build_part_prompt` creates LLM prompt                             | New helper(s): `plan_narrative()`, `synth_chunk()`, and `generate_part_summary()` orchestrator. |

---

## 2  Task breakdown

1. **Prompt definitions**  
   a. Add `STAGE3_PLAN_PROMPT_A`, `STAGE3_PLAN_PROMPT_B`, `STAGE3_SYNTH_PROMPT` constants to `prompts.py`.  
   b. Register in global `PROMPTS` dict.

2. **TypedDict schemas**  
   • Add `StoryBeat`, `NarrativePlan`, `GeneratedParagraph` to `law_types.py` (new or existing helpers).

3. **Input helpers**  
   • Implement `construct_stage3_plan_input()` and `construct_stage3_synth_input()` in `stage23_helpers.py`.

4. **Planning function**  
   • `plan_narrative(chapter_summaries, intro_lines, generator_fn)` – returns `NarrativePlan` from chosen prompt.

5. **Synthesis loop**  
   • `synthesise_paragraphs(plan, chapter_summaries, generator_fn)` – returns list[str].

6. **Orchestrator**  
   • Replace `build_part_prompt()` usage inside `generate_part_summary()` (new) that performs: plan → loop → join paragraphs.

7. **Pipeline integration**  
   • Update `generate_stage2_3_summaries.process_consultation()` so that Stage 3 per-part call uses the new orchestrator.

8. **Adjust token budgeting**  
   • Each LLM call must honour `target_words` logic currently used; re-use helper `summarization_budget()`.

9. **Tests**  
   • Unit tests for plan JSON validity (keys, types).  
   • Integration test on sample consultation to ensure output paragraphs ≈ Στοχευμένος αριθμός.

10. **Docs**  
    • Update README and developer guide.

---

## 3  JSON schemas

```python
from typing import List, TypedDict

class StoryBeat(TypedDict):
    τίτλος_ενότητας: str
    ρόλος_ενότητας: str
    πηγές_κεφαλαίων: List[int]

class NarrativePlan(TypedDict):
    συνολική_αφηγηματική_αψίδα: str
    πρωταγωνιστής: str
    πρόβλημα: str
    αφηγηματικές_ενότητες: List[StoryBeat]

class GeneratedParagraph(TypedDict):
    παράγραφος: str
```

---

## 4  Prompt A – with Σκοπός / Αντικείμενο

```
**Ρόλος (Persona):**
Είστε ένας διακεκριμένος δημοσιογράφος, με πολυετή εμπειρία στην κάλυψη νομοθετικού έργου για μεγάλα ειδησεογραφικά μέσα. Το πάθος σας είναι η προάσπιση της δημοκρατίας μέσω της έγκυρης ενημέρωσης. Στόχος σας είναι να "μεταφράζετε" πολύπλοκες νομοθετικές αλλαγές σε απλή, κατανοητή και συνεκτική γλώσσα για το ευρύ κοινό, ώστε κάθε πολίτης να κατανοεί τον αντίκτυπο των νόμων στη ζωή του.

**Οδηγίες:**
Σας παρέχονται τα επίσημα κείμενα «Σκοπός» ή/και «Αντικείμενο» για ένα Μέρος της νομοθεσίας, καθώς και οι περιλήψεις των κεφαλαίων που το απαρτίζουν. Η αποστολή σας είναι να δημιουργήσετε ένα δομημένο αφηγηματικό σχέδιο σε μορφή JSON.

1.  **Αναλύστε το Σύνολο:** Διαβάστε προσεκτικά όλα τα κείμενα. Χρησιμοποιήστε τα παρεχόμενα κείμενα «Σκοπός» ή/και «Αντικείμενο» ως τον κύριο οδηγό σας για να κατανοήσετε τη συνολική πρόθεση του νομοθέτη.
2.  **Δημιουργήστε το JSON:** Παράγετε **ΑΠΟΚΛΕΙΣΤΙΚΑ ΚΑΙ ΜΟΝΟ** ένα αντικείμενο JSON με την παρακάτω ακριβή δομή και κλειδιά στα ελληνικά.

**Δεδομένα Εισόδου:**
{input_data_json}

**Προσδοκώμενο JSON Output:**
<βλέπε παράδειγμα στο παρόν αρχείο>
```

---

## 5  Prompt B – χωρίς Σκοπός / Αντικείμενο

*(Ολόιδιο με Prompt A αλλά χωρίς το βήμα 1, αντίγραφο παραλείπεται εδώ για συντομία — πρέπει να προστεθεί πλήρες κείμενο κατά την υλοποίηση.)*

---

## 6  Prompt – Chunk Synthesis

```
**Ρόλος (Persona):**
Είστε ένας διακεκριμένος δημοσιογράφος … (όπως ανωτέρω).

**Οδηγίες:**
Σας παρέχω ολόκληρο το αφηγηματικό σχέδιο για ένα Μέρος της νομοθεσίας, τις αρχικές περιλήψεις των κεφαλαίων που σχετίζονται με **μία συγκεκριμένη ενότητα**, και τον τίτλο της ενότητας που πρέπει να συγγράψετε.

1.  **Κατανοήστε το Πλαίσιο:** …
2.  **Συγγράψτε την Ενότητα:** …
3.  **Συμπίεση & Ποιότητα:** …
4.  **Μορφή Εξόδου:** Επιστρέψτε **ΑΠΟΚΛΕΙΣΤΙΚΑ** ένα JSON με κλειδί `παράγραφος`.

**Δεδομένα Εισόδου:**
{input_data_json}
```

---

## 7  Helper pseudocode (to port)

```python
# construct_stage3_plan_input(), construct_stage3_synth_input() –
# see original pseudocode in user spec; adapt variable names to snake_case.
```

---

### 8  Open questions

* Token limits per sub-call? (Current Stage 3 uses 0.3 × words; we need similar budget strategy twice.)
* Parallelisation: can synthesis paragraphs be generated concurrently? (requires safeguarding against rate-limits.)
* Where to store intermediate Narrative Plan JSON (for traceability)? Suggest: write to Stage-3 CSV column `narrative_plan_json`.
