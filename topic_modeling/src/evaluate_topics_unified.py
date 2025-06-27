# ---------------------------------------------------------------------------
# evaluate_topics_unified.py – single-prompt evaluator (Gemini or local Gemma)
# ---------------------------------------------------------------------------
# Builds **one** prompt per consultation that contains:
#   • κάθε τίτλο, αιτιολόγηση και λέξεις-κλειδιά ανά topic
#   • ΠΟΛΛΑ σχόλια πολιτών ταξινομημένα ανά συνάφεια (BERTopic probability),
#     επιλεγμένα με round-robin across topics μέχρι να γεμίσει το context window.
# Gemini (ή τοπικό Gemma) δίνει πίσω λίστα JSON:
#   {"topic": <id>, "score": <1-5>, "feedback": "…"}
# Τα αποτελέσματα γράφονται σε evaluation_unified_<timestamp>.csv ή, σε
# offline mode (--export_manual), απλώς σώζεται το prompt για copy-paste.
#
# Usage examples
#   python evaluate_topics_unified.py --consultation_id 320 --version v2 --gemini \
#          --api_key $GEMINI_API_KEY --max_prompt_tokens 30000
#   python evaluate_topics_unified.py --consultation_id 320 --version v2 --export_manual
# ---------------------------------------------------------------------------

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

import pandas as pd

# Re-use helpers from evaluate_topics_enhanced.py (same directory)
from evaluate_topics_enhanced import (
    init_gemini,
    init_local_gemma,
    estimate_tokens,
    parse_keywords,
    _load_titles_map,
    GeminiSafetyError,
    SAFE_SETTINGS,  # noqa: F401 – re-exported constant
)

DEFAULT_MODEL_ID = "models/gemini-2.5-flash"
DEFAULT_GEMMA_PATH = "/home/glossapi/.cache/huggingface/hub/models--google--gemma-3-4b-it"

# ---------------------------------------------------------------------------
# PROMPT TEMPLATES
# ---------------------------------------------------------------------------
INSTR_BLOCK = (
    "Είσαι εξωτερικός αξιολογητής θεματικών ενότητων σχολίων δημόσιας διαβούλευσης.\n"
    "Σου δίνεται μία λίστα θεμάτων (τίτλος + αιτιολόγηση + λέξεις-κλειδιά) όπως προτάθηκαν από άλλο σύστημα, "
    "καθώς και ΠΟΛΛΑ αντιπροσωπευτικά σχόλια χρηστών ταξινομημένα κατά συνάφεια, "
    "για να κατανοήσεις το γενικότερο περιεχόμενο των σχολίων και να αξιολογήσεις καλύτερα τα αποτελέσματα του άλλου συστήματος.\n"
    "Για κάθε θεματική/topic σου ζητείται να αξιολογήσεις:\n"
    "1. Τον τίτλο\n"
        "- Είναι σύντομος, περιγραφικός, ξεκάθαρος;\n"
        "- Αντικατοπτρίζει με ακρίβεια το περιεχόμενο των σχολίων;\n"
        "- Αποφεύγει ασάφειες;\n"
    "2. Την αιτιολόγηση\n"
        "- Είναι λογική και πειστική;\n"
        "- Στηρίζεται σε συγκεκριμένα σχόλια/λέξεις‑κλειδιά;\n"
        "- Εξηγεί γιατί επιλέχθηκε αυτός ο τίτλος;\n"
    "Για ΚΑΘΕ θεματική/topic πρέπει να επιστρέψεις αντικείμενο JSON:\n"
    "  {\"topic\": <id>, \"score\": <1-5>, \"feedback\": \"…\"}\n"
    "• Το score 1–5 εκφράζει πόσο καλά ο τίτλος & η εξήγηση ταιριάζουν στο περιεχόμενο των σχολίων.\n"
    "• Το feedback να είναι 1-2 προτάσεις, στα Ελληνικά.\n"
    "Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ μια λίστα JSON χωρίς επιπλέον κείμενο."
)

# ---------------------------------------------------------------------------

def round_robin_comment_selection(
    per_topic_lists: Dict[int, List[str]],
    per_topic_tokens: Dict[int, List[int]],
    token_budget: int,
) -> List[tuple[int, str]]:
    """Return list of (topic_id, comment) tuples selected round-robin."""
    cursors = {tid: 0 for tid in per_topic_lists}
    topics_in_play = set(per_topic_lists)
    selected: List[tuple[int, str]] = []

    while topics_in_play and token_budget > 0:
        for tid in sorted(list(topics_in_play)):
            idx = cursors[tid]
            if idx >= len(per_topic_lists[tid]):
                topics_in_play.remove(tid)
                continue
            txt = per_topic_lists[tid][idx]
            tks = per_topic_tokens[tid][idx]
            if tks > token_budget:
                # bucket full – stop completely
                token_budget = 0
                break
            selected.append((tid, txt))
            token_budget -= tks
            cursors[tid] += 1
    return selected

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Single-prompt Gemini evaluator for all topics.")
    p.add_argument("--outputs_root", type=Path, default=Path(__file__).resolve().parent.parent / "outputs")
    p.add_argument("--version", choices=["v1", "v2", "v3"], help="Pipeline version to evaluate (default auto)")
    p.add_argument("--consultation_id", type=int, required=True)

    backend = p.add_mutually_exclusive_group()
    backend.add_argument("--gemini", action="store_true", help="Use Gemini API (default)")
    backend.add_argument("--local", action="store_true", help="Use local Gemma")

    p.add_argument("--api_key", default=os.getenv("GEMINI_API_KEY"))
    p.add_argument("--model", default=DEFAULT_MODEL_ID)
    p.add_argument("--gemma_path", default=DEFAULT_GEMMA_PATH)
    p.add_argument("--temperature", type=float, default=0.2)

    p.add_argument("--max_prompt_tokens", type=int, default=32000, help="Global token budget for comments block")
    p.add_argument("--export_manual", action="store_true")
    args = p.parse_args()

    if not args.export_manual and not args.gemini and not args.local:
        args.gemini = True

    # -------------------------------------------------- paths & prerequisites
    if args.version is None:
        for v in ("v3", "v2", "v1"):
            if (args.outputs_root / v / str(args.consultation_id)).exists():
                args.version = v
                break
    if args.version is None:
        raise SystemExit("Could not detect outputs – run topic modelling first.")

    base = args.outputs_root / args.version / str(args.consultation_id)
    topics_csv = base / "clustering" / "topics.csv"
    titles_file = base / "titles" / (
        f"topics_llm_{args.version}.jsonl" if (base / "titles" / f"topics_llm_{args.version}.jsonl").exists() else "topics_llm.csv"
    )

    for path in (topics_csv, titles_file):
        if not path.exists():
            raise SystemExit(f"Required file {path} missing – run the pipeline.")

    # -------------------------------------------------- load data
    topics_df = pd.read_csv(topics_csv)
    # load titles and explanations
    title_map: Dict[int, str] = {}
    expl_map: Dict[int, str] = {}
    if titles_file.suffix == ".jsonl":
        with titles_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    tid = int(obj.get("Topic", obj.get("topic", -1)))
                    title_map[tid] = obj.get("Title", obj.get("title", "")).strip()
                    expl_map[tid] = obj.get("Explanation", obj.get("explanation", "")).strip()
                except Exception:
                    continue
    else:
        df_titles = pd.read_csv(titles_file)
        if "Topic" in df_titles.columns:
            for _, row in df_titles.iterrows():
                tid = int(row["Topic"])
                title_map[tid] = str(row.get("Title", "")).strip()
                expl_map[tid] = str(row.get("Explanation", "")).strip()
        else:
            title_map = _load_titles_map(titles_file)
            expl_map = {k: "" for k in title_map}

    # Build per-topic sorted lists & token counts
    per_topic_all: Dict[int, List[str]] = {}
    per_topic_tokens: Dict[int, List[int]] = {}
    for tid, grp in topics_df.groupby("Topic"):
        if tid == -1:
            continue
        ordered = grp.sort_values("Probability", ascending=False)
        texts = ordered["Document"].tolist() if "Document" in ordered.columns else ordered["content_clean"].tolist()
        per_topic_all[tid] = texts
        per_topic_tokens[tid] = [estimate_tokens(t) for t in texts]

    # -------------------------------------------------- prep titles + keywords + rep comments block
    topics_header_parts: List[str] = []
    for tid in sorted(per_topic_all):
        ttl = title_map.get(tid, f"Θέμα {tid}")
        expl = expl_map.get(tid, "")
        # keywords from clustering
        kw_col = "Top_n_words" if "Top_n_words" in topics_df.columns else "Name"
        kw_row = topics_df[topics_df["Topic"] == tid].iloc[0]
        kw_line = str(kw_row.get(kw_col, ""))

        part = (
            f"Topic {tid}\nΤίτλος: {ttl}\nΑιτιολόγηση: {expl}\nΛέξεις-κλειδιά: {kw_line}\n"
        )
        topics_header_parts.append(part)
    topics_header_block = "\n".join(topics_header_parts)

    # -------------------------------------------------- round-robin comment fill
    token_budget = args.max_prompt_tokens
    selected_pairs = round_robin_comment_selection(per_topic_all, per_topic_tokens, token_budget)
    comments_block = "\n".join([f"{tid}:: \"{txt}\"" for tid, txt in selected_pairs])

    prompt = (
        "===== ΟΔΗΓΙΕΣ =====\n" + INSTR_BLOCK + "\n\n" +
        "===== ΘΕΜΑΤΑ =====\n" + topics_header_block + "\n\n" +
        "===== ΣΧΟΛΙΑ =====\n" + comments_block + "\n\n===== ΤΕΛΟΣ ====="
    )

    # -------------------------------------------------- manual export
    eval_dir = base / "evaluation"
    eval_dir.mkdir(exist_ok=True, parents=True)
    if args.export_manual:
        out_dir = eval_dir / "unified_prompt"
        out_dir.mkdir(exist_ok=True, parents=True)
        (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        print(f"Prompt written to {out_dir / 'prompt.txt'}")
        return

    # -------------------------------------------------- call LLM
    if args.local:
        gen_fn = init_local_gemma(args.gemma_path, temperature=args.temperature)
    else:
        if not args.api_key:
            raise SystemExit("Set GEMINI_API_KEY or pass --api_key.")
        gen_fn = init_gemini(args.api_key, args.model, args.temperature)

    try:
        response = gen_fn(prompt)
    except GeminiSafetyError as e:
        print(f"LLM blocked: {e}")
        sys.exit(1)

    # -------------------------------------------------- parse JSON list
    try:
        # strip markdown fences if any
        m = re.search(r"```json\s*(\[.*?\])\s*```", response, flags=re.DOTALL)
        if m:
            response = m.group(1)
        data = json.loads(response)
    except Exception as e:
        print("Failed to parse JSON from LLM response", e)
        data = []

    rows = []
    for item in data:
        try:
            rows.append({
                "topic": int(item.get("topic")),
                "title": title_map.get(int(item.get("topic")), ""),
                "score": float(item.get("score")),
                "raw_response": item.get("feedback", ""),
            })
        except Exception:
            continue

    out_csv = eval_dir / f"evaluation_unified_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"Saved evaluation to {out_csv}")


if __name__ == "__main__":
    main() 