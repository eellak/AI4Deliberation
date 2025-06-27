# ---------------------------------------------------------------------------
# evaluate_topics_enhanced.py – Gemini-based in-depth title evaluator
# ---------------------------------------------------------------------------
# Compared to evaluate_topics.py this variant:
#   1. Feeds Gemini (or local Gemma) a MUCH larger context – as many comments
#      per topic as fit within a configurable token budget (default ≈12k).
#   2. Adds an OFFLINE mode (`--export_manual`) that simply dumps each prompt
#      (and the raw comments) under outputs/<ver>/<cid>/evaluation/manual_prompts/
#      so a human can copy-paste them into Gemini Chat / AI Studio.
#   3. Requires the standard topic-modeling outputs to exist (titles + reps).
#      If they are missing, the script exits with an instructive error.
# ---------------------------------------------------------------------------
# Usage examples
#   # Evaluate v1 outputs with Gemini API (large context)
#   python evaluate_topics_enhanced.py --consultation_id 320 --gemini
#
#   # Dump prompts only (no API key required)
#   python evaluate_topics_enhanced.py --consultation_id 320 \
#          --export_manual --version v21
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

# ---------------------------------------------------------------------------
# Environment tweaks BEFORE torch import (GPU fragmentation optimisation)
# ---------------------------------------------------------------------------
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:64")

import torch  # noqa: E402

# Optional providers ---------------------------------------------------------
try:
    import google.generativeai as genai  # type: ignore
except ImportError:
    genai = None  # type: ignore

try:
    from transformers import AutoProcessor, Gemma3ForConditionalGeneration  # type: ignore
except ImportError:
    AutoProcessor = Gemma3ForConditionalGeneration = None  # type: ignore

# ---------------------------------------------------------------------------
# CONSTANTS & DEFAULTS
# ---------------------------------------------------------------------------
DEFAULT_MODEL_ID = "models/gemini-2.5-flash"
DEFAULT_GEMMA_PATH = "/home/glossapi/.cache/huggingface/hub/models--google--gemma-3-4b-it"

# Allow Gemini content through (relaxed safety) but detect blocks
SAFE_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUAL", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS", "threshold": "BLOCK_NONE"},
]


# ---------------------------------------------------------------------------
# EXCEPTIONS
# ---------------------------------------------------------------------------
class GeminiSafetyError(RuntimeError):
    """Raised when Gemini blocks a response for safety reasons."""


# ---------------------------------------------------------------------------
# INITIALISERS
# ---------------------------------------------------------------------------

def init_gemini(api_key: str, model_name: str, temperature: float) -> Callable[[str], str]:
    if genai is None:
        raise ImportError("google-generativeai package is required for Gemini backend.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, safety_settings=SAFE_SETTINGS)
    cfg = {
        "temperature": temperature,
        "top_p": 0.9,
        "top_k": 40,
        "max_output_tokens": 1024,
    }

    def _generate(prompt: str) -> str:
        resp = model.generate_content(prompt, generation_config=cfg)
        # prompt feedback is useful when blocked
        try:
            if hasattr(resp, "prompt_feedback") and resp.prompt_feedback:
                print(f"[gemini] prompt_feedback: {resp.prompt_feedback}", file=sys.stderr)
        except Exception:
            pass

        if resp.candidates:
            cand = resp.candidates[0]
            # Log safety ratings for debugging
            try:
                print(f"[gemini] safety_ratings: {cand.safety_ratings}", file=sys.stderr)
            except Exception:
                pass
            if cand.finish_reason not in (0, "STOP", "stop"):
                raise GeminiSafetyError(
                    f"Gemini blocked content (finish_reason={cand.finish_reason}, safety_ratings={cand.safety_ratings})"
                )
            if cand.content.parts:
                return cand.content.parts[0].text  # type: ignore
        # fallback
        try:
            return resp.text  # type: ignore
        except Exception as e:
            raise GeminiSafetyError(f"Gemini blocked content (exception={e})")

    return _generate


def init_local_gemma(model_root: str, device: str = "auto", temperature: float = 0.2) -> Callable[[str], str]:
    if Gemma3ForConditionalGeneration is None or AutoProcessor is None:
        raise ImportError("transformers >=4.41 with Gemma support is required for local Gemma usage.")

    root_path = Path(model_root)
    snaps = root_path / "snapshots"
    if snaps.is_dir():
        subdirs = sorted([d for d in snaps.iterdir() if d.is_dir()])
        if subdirs:
            model_root = str(subdirs[0])

    model = Gemma3ForConditionalGeneration.from_pretrained(
        model_root, device_map=device, torch_dtype="auto"
    ).eval()
    tokenizer = AutoProcessor.from_pretrained(model_root)

    def _generate(prompt: str) -> str:
        max_new = 256
        attempt = 0
        max_attempts = 4  # 256,128,64,32
        generated_text = ""
        while True:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            enc = tokenizer(text=prompt, return_tensors="pt")
            input_len = enc["input_ids"].shape[1]
            inputs = enc.to(model.device)
            try:
                with torch.no_grad():  # type: ignore
                    out = model.generate(
                        **inputs,
                        max_new_tokens=max_new,
                        temperature=temperature,
                    )
                generated_text = tokenizer.decode(out[0][input_len:], skip_special_tokens=True)
                del inputs, out, enc
                break
            except RuntimeError as err:
                del inputs, enc
                if "CUDA out of memory" in str(err) and attempt < max_attempts:
                    attempt += 1
                    max_new = max(16, max_new // 2)
                    continue
                raise
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        return generated_text

    return _generate


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Very rough token estimate ~1.1*words (works OK for Greek)."""
    return int(len(text.split()) * 1.1) + 1


def select_comments(group: pd.DataFrame, max_tokens: int, min_comments: int) -> List[str]:
    """Return a list of comments for the prompt subject to token budget."""
    selected: List[str] = []
    token_budget = max_tokens
    ordered = (
        group.sort_values("Probability", ascending=False)
        if "Probability" in group.columns
        else group
    )
    for _, row in ordered.iterrows():
        txt = str(row["content"] if "content" in row else row["comment_text"])
        tks = estimate_tokens(txt)
        if len(selected) < min_comments or (token_budget - tks) > 0:
            selected.append(txt)
            token_budget -= tks
        else:
            break
    return selected


DEFAULT_PROMPT_HEADER = (
    "Είσαι ένας αξιολογητής ποιότητας για τη θεματική κατηγοριοποίηση σχολίων δημόσιας διαβούλευσης."
    " Σου δίνεται ένας τίτλος θεματικής ενότητας και (προαιρετικά) η αιτιολόγηση της επιλογής του,"
    " όπως αυτά έχουν παραχθεί από ένα προηγούμενο σύστημα."
    " Επίσης, σου δίνεται ένα μεγάλο σύνολο αντιπροσωπευτικών σχολίων και οι λέξεις-κλειδιά που τα συνοψίζουν.\n"
    "Οδηγίες:\n"
    "Αξιολόγησε τον Τίτλο:\n"
    "   • Είναι ο τίτλος σύντομος, αντιπροσωπευτικός και περιγραφικός του συνολικού περιεχομένου των σχολίων;\n"
    "   • Αποδίδει με ακρίβεια το βασικό θέμα ή τη θεματική ενότητα στην οποία εντάσσονται τα σχόλια;\n"
    "   • Είναι κατανοητός και ξεκάθαρος;\n"
    "   • Αποφεύγει ασάφειες ή παρερμηνείες;\n"
    "   • Πόσο καλά συνδέονται ο τίτλος και η αιτιολόγηση με το πραγματικό περιεχόμενο των σχολίων και των λέξεων-κλειδιών;\n"
    "Παρουσίασε ως έξοδο:\n"
    "• Μια συνολική βαθμολογία για την ποιότητα του τίτλου (1–5, όπου 5 είναι άριστο).\n"
    "• Λεπτομερή σχόλια που να εξηγούν τη βαθμολογία, επισημαίνοντας δυνατά σημεία και σημεία προς βελτίωση.\n"
)


def build_prompt(title: str, explanation: str, comments: List[str], keywords: List[str]) -> str:
    joined_comments = "\n".join([f"{i+1}. \"{c}\"" for i, c in enumerate(comments)])
    joined_keywords = ", ".join(keywords)
    return (
        f"{DEFAULT_PROMPT_HEADER}\n\n"
        "===== ΥΠΟ ΑΞΙΟΛΟΓΗΣΗ ΚΕΙΜΕΝΟ =====\n"
        f"Τίτλος:\n{title}\n\n"
        f"Εξήγηση:\n{explanation}\n\n"
        f"Σχόλια χρηστών (σύνολο: {len(comments)}):\n" + joined_comments + "\n\n"
        f"Λέξεις-κλειδιά: {joined_keywords}\n\n"
        "===== ΤΕΛΟΣ ΚΕΙΜΕΝΟΥ ====="
    )


def parse_keywords(rep: str) -> List[str]:
    try:
        lst = json.loads(rep) if rep.startswith("[") else None
        if isinstance(lst, list):
            return [str(x) for x in lst]
    except Exception:
        pass
    return re.split(r"[,\s]+", rep)[:15]


def _load_titles_map(titles_path: Path) -> Dict[int, str]:
    if not titles_path.exists():
        return {}
    if titles_path.suffix == ".jsonl":
        mapping: Dict[int, str] = {}
        with titles_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    tid = int(obj.get("Topic", obj.get("topic", -1)))
                    ttl = str(obj.get("Title", obj.get("title", ""))).strip()
                    if tid != -1 and ttl:
                        mapping[tid] = ttl
                except Exception:
                    continue
        return mapping
    df = pd.read_csv(titles_path)
    if "Title" in df.columns:
        return {int(r.Topic): str(r.Title).strip() for _, r in df.iterrows() if r.Topic != -1}
    if "Name" in df.columns:
        return {int(r.Topic): str(r.Name).strip() for _, r in df.iterrows() if r.Topic != -1}
    return {}


def parse_score(text: str) -> float | None:
    patterns = [
        r"(?:Βαθμολογία|Συνολική\s+Βαθμολογία|Overall\s+Score)\s*[:\-]?\s*([0-5](?:[.,]\d+)?)\s*(?:/\s*5)?",
        r"\b([0-5](?:[.,]\d+)?)\s*/\s*5\b",
        r"Βαθμολογία\s*[:\-]?\s*([0-5](?:[.,]\d+)?)\b",
    ]
    for patt in patterns:
        m = re.search(patt, text, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(',', '.'))
            except ValueError:
                continue
    return None


def export_manual(topic_id: int, prompt: str, comments: List[str], meta: Dict[str, Any], base_dir: Path):
    topic_dir = base_dir / f"topic_{topic_id}"
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (topic_dir / "comments.txt").write_text("\n".join(comments), encoding="utf-8")
    (topic_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate topic titles with Gemini using extended context.")
    parser.add_argument("--outputs_root", type=Path, default=Path(__file__).resolve().parent.parent / "outputs")
    parser.add_argument("--version", choices=["v1", "v2", "v3"], help="Pipeline version to evaluate (default: auto-detect)")
    parser.add_argument("--consultation_id", type=int, required=True)

    backend = parser.add_mutually_exclusive_group()
    backend.add_argument("--gemini", action="store_true", help="Use Gemini API (default)")
    backend.add_argument("--local", action="store_true", help="Use local Gemma backend")

    parser.add_argument("--api_key", default=os.getenv("GEMINI_API_KEY"))
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--gemma_path", default=DEFAULT_GEMMA_PATH)
    parser.add_argument("--temperature", type=float, default=0.2)

    parser.add_argument("--max_prompt_tokens", type=int, default=12000)
    parser.add_argument("--min_comments_per_topic", type=int, default=20)

    parser.add_argument("--export_manual", action="store_true", help="Only dump prompts for manual copy-paste (offline mode)")
    parser.add_argument("--dump_prompts", action="store_true", help="Save each prompt.txt even when calling LLM")

    args = parser.parse_args()

    # Auto provider selection: default -> gemini unless local specified
    if not args.export_manual and not args.gemini and not args.local:
        args.gemini = True

    # ------------------------------------------------------------------
    # Resolve outputs dir and check prerequisites
    # ------------------------------------------------------------------
    if args.version is None:
        for v in ("v3", "v2", "v1"):
            if (args.outputs_root / v / str(args.consultation_id)).exists():
                args.version = v
                break
    if args.version is None:
        raise SystemExit("Could not detect outputs – specify --version and ensure topic modelling has run.")

    base_dir = args.outputs_root / args.version / str(args.consultation_id)
    if not base_dir.exists():
        raise SystemExit(f"Outputs directory {base_dir} does not exist – run the topic modelling pipeline first.")

    # ------------------------------------------------------
    # Load comments – FULL clustering output for rich context
    # ------------------------------------------------------
    topics_csv_path = base_dir / "clustering" / "topics.csv"
    if not topics_csv_path.exists():
        raise SystemExit("clustering/topics.csv not found – run the topic modelling pipeline first.")

    # Representative comments (optional; used only for keywords)
    rep_path = base_dir / "reps" / "representative_comments.csv"

    titles_path = None
    if args.version == "v1":
        titles_path = base_dir / "titles" / "topics_llm_v1.jsonl"
    elif args.version == "v2":
        titles_path = base_dir / "titles" / "topics_llm_v2.jsonl"
    elif args.version == "v3":
        titles_path = base_dir / "titles" / "topics_llm_v3.jsonl"
    if not titles_path.exists():
        titles_path = base_dir / "titles" / "topics_llm.csv"
    if not titles_path.exists():
        raise SystemExit("Titles file not found – run the topic modelling pipeline first.")

    # ------------------------------------------------------------------
    # Initialise generator if needed
    # ------------------------------------------------------------------
    generate_fn = None
    if not args.export_manual:
        if args.local:
            generate_fn = init_local_gemma(args.gemma_path, temperature=args.temperature)
        else:
            if not args.api_key:
                raise SystemExit("Provide --api_key or set GEMINI_API_KEY when using Gemini backend.")
            generate_fn = init_gemini(args.api_key, args.model, args.temperature)

    # ------------------------------------------------------------------
    # Load dataframes
    # ------------------------------------------------------------------
    topics_df = pd.read_csv(topics_csv_path)
    rep_df = pd.read_csv(rep_path) if rep_path.exists() else pd.DataFrame()
    title_map = _load_titles_map(titles_path)

    results: List[Dict[str, Any]] = []

    # manual export base dir
    manual_dir: Path | None = None
    if args.export_manual:
        manual_dir = base_dir / "evaluation" / "manual_prompts"
        manual_dir.mkdir(parents=True, exist_ok=True)
        # write helper README once
        readme_path = manual_dir / "README_how_to_use.txt"
        if not readme_path.exists():
            manual_readme = (
                "Πώς να χρησιμοποιήσετε τα prompts μη αυτόματα\n\n"
                "1. Ανοίξτε το φάκελο και επιλέξτε ένα subfolder π.χ. topic_0.\n"
                "2. Αντιγράψτε το περιεχόμενο του prompt.txt και επικολλήστε το στο Gemini Chat / AI Studio.\n"
                "3. (Προαιρετικά) επισυνάψτε το αρχείο comments.txt για επιπλέον συμφραζόμενα.\n"
                "4. Ζητήστε από το Gemini να απαντήσει.\n"
                "5. Αποθηκεύστε την απάντηση για μελλοντική αξιολόγηση.\n"
            )
            readme_path.write_text(manual_readme, encoding="utf-8")

    # combined prompts file if dumping
    combined_writer = None
    if args.export_manual:
        combined_writer = (manual_dir / "all_prompts_combined.txt").open("w", encoding="utf-8")

    # evaluation dir ensure
    eval_dir = base_dir / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)

    prompts_dump_dir: Path | None = None
    if args.dump_prompts and not args.export_manual:
        prompts_dump_dir = eval_dir / "prompts"
        prompts_dump_dir.mkdir(parents=True, exist_ok=True)

    for topic_id, group in topics_df.groupby("Topic"):
        if topic_id == -1:
            continue
        comments = select_comments(
            group,
            max_tokens=args.max_prompt_tokens,
            min_comments=args.min_comments_per_topic,
        )
        # Get keywords from representative comments file if available
        if not rep_df.empty and "Representation" in rep_df.columns:
            kw_row = rep_df[rep_df["Topic"] == topic_id]
            if not kw_row.empty:
                keywords = parse_keywords(str(kw_row.iloc[0]["Representation"]))
            else:
                keywords = []
        elif not rep_df.empty and "key_phrase" in rep_df.columns:
            keywords = list(rep_df[rep_df["Topic"] == topic_id]["key_phrase"].unique())[:15]
        else:
            keywords = []
        title = title_map.get(topic_id, f"Θέμα {topic_id}")
        explanation = ""  # explanation not used in evaluation ≥v2 but keep placeholder

        prompt = build_prompt(title, explanation, comments, keywords)

        if args.export_manual and manual_dir is not None:
            meta = {
                "topic": topic_id,
                "title": title,
                "n_comments": len(comments),
                "est_tokens": sum(estimate_tokens(c) for c in comments),
            }
            export_manual(topic_id, prompt, comments, meta, manual_dir)
            combined_writer.write("\n\n===== TOPIC " + str(topic_id) + " =====\n" + prompt + "\n")
            results.append({
                "topic": topic_id,
                "title": title,
                "score": None,
                "raw_response": "(manual export mode)",
            })
            continue  # skip model call

        # --- save prompt if requested ---
        if prompts_dump_dir is not None:
            (prompts_dump_dir / f"prompt_topic_{topic_id}.txt").write_text(prompt, encoding="utf-8")

        # --- call generator ---
        assert generate_fn is not None  # for type checker
        try:
            evaluation_text = generate_fn(prompt)
        except GeminiSafetyError as e:
            print(f"[safety] Aborting evaluation: {e}")
            sys.exit(1)
        except Exception as e:
            evaluation_text = f"ERROR: {e}"

        score_val = parse_score(evaluation_text)

        results.append({
            "topic": topic_id,
            "title": title,
            "score": score_val,
            "raw_response": evaluation_text,
        })

    if combined_writer:
        combined_writer.close()

    # save CSV even in manual mode (scores may be None)
    out_csv = eval_dir / f"evaluation_enhanced_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    pd.DataFrame(results).to_csv(out_csv, index=False)
    print(f"Saved evaluation results to {out_csv}")

    if args.export_manual:
        print(f"All prompts written to {manual_dir}")


if __name__ == "__main__":
    main() 