# ---------------------------------------------------------------------------
# evaluate_topics.py – LLM-based quality scoring of topic titles
# ---------------------------------------------------------------------------
# Reads the outputs of any of the modeling pipelines (v1/v2/v3) and asks
# a Large Language Model to rate how well each automatically-generated
# topic *title* matches its representative comments.
#
# Back-ends supported
#   • Google Gemini API (default)        – add --gemini
#   • Local Gemma-3-4B-it via Transformers – add --local
#
# For every topic the script builds a Greek prompt including:
#   • the title (LLM-generated during modeling),
#   • an optional explanation or keywords,
#   • the 10 most representative comments.
# The LLM returns free-text feedback plus a score 1-5 which we parse.
# Results are stored in outputs/<ver>/<cid>/evaluation/evaluation_results_*.csv.
#
# Basic usage examples
#   # Evaluate latest pipeline version with Gemini free-tier (flash):
#   python evaluate_topics.py --consultation_id 320 --gemini
#
#   # Evaluate v2 outputs with local Gemma on GPU:
#   python evaluate_topics.py --consultation_id 320 --version v2 --local \
#          --gemma_path /path/to/gemma-3-4b-it
#
#   # Only dump the prompts (no token cost):
#   python evaluate_topics.py --consultation_id 320 --dump_prompts
# ---------------------------------------------------------------------------

import argparse
import datetime as dt
from pathlib import Path
from typing import List, Dict, Any, Callable
import os
import re
import ast
import pandas as pd
import gc  # For manual garbage-collection when running many generations
import json
import sys

# ---------------------------------------------------------------------------
# Environment variables **must** be set before torch is imported so that they
# influence the CUDA allocator behaviour.
# ---------------------------------------------------------------------------

# Disable TorchDynamo JIT, which currently breaks Gemma generation (see transformers docs)
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

# Reduce allocator fragmentation: allow CUDA allocator to return very large
# blocks to the driver so that subsequent allocations succeed instead of OOM.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:64")

# Now it is safe to import torch
import torch

# Optional cloud provider (Gemini) ---------------------------------------------------
try:
    import google.generativeai as genai  # type: ignore
except ImportError:
    genai = None  # will error only if user selects provider that needs it

# Optional local model (Gemma) -------------------------------------------------------
try:
    from transformers import AutoProcessor, Gemma3ForConditionalGeneration  # type: ignore
except ImportError:
    AutoProcessor = Gemma3ForConditionalGeneration = None  # type: ignore

# Attempt to load a .env file so users can store the API key there (recommended)
try:
    from dotenv import load_dotenv  # type: ignore

    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        load_dotenv()  # fallback to default discovery
except ImportError:
    pass  # optional dependency

DEFAULT_PROMPT = (
    "Είσαι ένας αξιολογητής ποιότητας για τη θεματική κατηγοριοποίηση σχολίων δημόσιας διαβούλευσης."  # noqa: E501
    " Σου δίνεται ένας τίτλος θεματικής ενότητας και (προαιρετικά) η αιτιολόγηση της επιλογής του,"  # noqa: E501
    " όπως αυτά έχουν παραχθεί από ένα προηγούμενο σύστημα."
    " Επίσης, σου δίνεται το αρχικό κείμενο των δέκα πιο αντιπροσωπευτικών σχολίων χρηστών και οι λέξεις-κλειδιά που τα συνοψίζουν.\n"  # noqa: E501
    "Οδηγίες:\n"
    "Αξιολόγησε τον Τίτλο:\n"
    "   • Είναι ο τίτλος σύντομος, αντιπροσωπευτικός και περιγραφικός του συνολικού περιεχομένου των σχολίων;\n"
    "   • Αποδίδει με ακρίβεια το βασικό θέμα ή τη θεματική ενότητα στην οποία εντάσσονται τα σχόλια;\n"
    "   • Είναι κατανοητός και ξεκάθαρος;\n"
    "   • Αποφεύγει ασάφειες ή παρερμηνείες;\n"
    "   • ΑΠόσο καλά συνδέονται ο τίτλος και η αιτιολόγηση με το πραγματικό περιεχόμενο των σχολίων και των λέξεων-κλειδιών;"
    "Παρουσίασε ως έξοδο:"
    "• Μια συνολική βαθμολογία για την ποιότητα του τίτλου και της αιτιολόγησης (π.χ., σε κλίμακα από 1 έως 5, όπου 5 είναι άριστο).\n"
    "• Λεπτομερή σχόλια που να εξηγούν τη βαθμολογία, επισημαίνοντας δυνατά σημεία και σημεία προς βελτίωση τόσο για τον τίτλο όσο και για την αιτιολόγηση. Χρησιμοποίησε συγκεκριμένα παραδείγματα από τα σχόλια ή τις λέξεις-κλειδιά για να υποστηρίξεις τις παρατηρήσεις σου.\n"
)

# Default to Flash because it has a free tier; Pro is paid-only.
DEFAULT_MODEL_ID = "models/gemini-2.5-flash"
DEFAULT_GEMMA_PATH = "/home/glossapi/.cache/huggingface/hub/models--google--gemma-3-4b-it"

# ---------------------------------------------------------------------------
# Gemini safety configuration (relax blocks but still filter extreme content)
# ---------------------------------------------------------------------------

# Allow all content through (Gemini will still redact disallowed content internally).
SAFE_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUAL", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS", "threshold": "BLOCK_NONE"},
]


class GeminiSafetyError(RuntimeError):
    """Raised when Gemini blocks a response for safety reasons."""


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def init_gemini(api_key: str, model_name: str, temperature: float) -> Callable[[str], str]:
    if genai is None:
        raise ImportError("google-generativeai package is required for provider 'gemini_api'.")
    genai.configure(api_key=api_key)
    # Pass custom safety settings when constructing the model (relaxed thresholds)
    model = genai.GenerativeModel(model_name, safety_settings=SAFE_SETTINGS)
    cfg = {
        "temperature": temperature,
        "top_p": 0.9,
        "top_k": 40,
        "max_output_tokens": 1024,
    }

    def _generate(prompt: str) -> str:
        resp = model.generate_content(prompt, generation_config=cfg)

        # Show prompt-level feedback irrespective of candidates, it often
        # contains the definitive block_reason when generation is refused
        try:
            if hasattr(resp, "prompt_feedback") and resp.prompt_feedback:
                print(f"[gemini] prompt_feedback: {resp.prompt_feedback}", file=sys.stderr)
        except Exception:
            pass  # SDK might change schema – ignore

        if resp.candidates:
            cand = resp.candidates[0]
            try:
                print(f"[gemini] safety_ratings: {cand.safety_ratings}", file=sys.stderr)
            except Exception:
                # Gracefully ignore if the SDK schema changes
                pass

            # Examine finish reason after we've logged the ratings
            if cand.finish_reason not in (0, "STOP", "stop"):
                # finish_reason can be numeric or string depending on SDK version
                raise GeminiSafetyError(
                    f"Gemini blocked content (finish_reason={cand.finish_reason}, safety_ratings={cand.safety_ratings})"
                )
            # Safe – return the generated text part
            if cand.content.parts:
                return cand.content.parts[0].text  # type: ignore

        # Fallback: attempt quick accessor; wrap in try to convert SDK errors into our own
        try:
            return resp.text  # type: ignore
        except Exception as e:
            raise GeminiSafetyError(f"Gemini blocked content (exception={e})")

    return _generate


def init_local_gemma(model_root: str, device: str = "auto", temperature: float = 0.2) -> Callable[[str], str]:
    if Gemma3ForConditionalGeneration is None or AutoProcessor is None:
        raise ImportError("transformers >=4.41 with Gemma support is required for local Gemma usage.")

    # Resolve snapshot dir automatically (same helper as modeling script)
    root_path = Path(model_root)
    snaps = root_path / "snapshots"
    if snaps.is_dir():
        subdirs = sorted([d for d in snaps.iterdir() if d.is_dir()])
        if subdirs:
            model_root = str(subdirs[0])

    model = Gemma3ForConditionalGeneration.from_pretrained(model_root, device_map=device, torch_dtype="auto").eval()
    tokenizer = AutoProcessor.from_pretrained(model_root)

    def _generate(prompt: str) -> str:
        """Generate text with Gemma (local). Uses a shorter max_new_tokens for speed."""
        max_new = 256
        attempt = 0
        max_attempts = 4  # 256,128,64,32 or 16
        generated_text = ""

        while True:
            # Free any cached blocks *before* allocating new tensors
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            # (Re-)encode the prompt – keep tensors on CPU until after retry decision
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
                # success -> break
                del inputs, out, enc
                break
            except RuntimeError as err:
                del inputs, enc
                if "CUDA out of memory" in str(err) and attempt < max_attempts:
                    attempt += 1
                    # halve the budget, floor to 16 tokens
                    max_new = max(16, max_new // 2)
                    continue  # retry with smaller budget
                raise

        # Explicitly release CUDA tensors to mitigate fragmentation
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

        # Run Python GC to free host memory that might be holding on to CUDA tensors
        gc.collect()

        return generated_text

    return _generate


def build_prompt(title: str, explanation: str, comments: List[str], keywords: List[str]) -> str:
    joined_comments = "\n".join([f"{i+1}. \"{c}\"" for i, c in enumerate(comments)])
    joined_keywords = ", ".join(keywords)
    return (
        f"{DEFAULT_PROMPT}\n\n"
        "===== ΥΠΟ ΑΞΙΟΛΟΓΗΣΗ ΚΕΙΜΕΝΟ =====\n"
        f"Τίτλος:\n{title}\n\n"
        f"Εξήγηση:\n{explanation}\n\n"
        "Σχόλια χρηστών:\n" + joined_comments + "\n\n"  # noqa: E501
        f"Λέξεις-κλειδιά: {joined_keywords}\n\n"
        "===== ΤΕΛΟΣ ΚΕΙΜΕΝΟΥ ====="
    )


def parse_keywords(rep: str) -> List[str]:
    """Representation strings are saved like "['keyword1', 'keyword2', ...]"."""
    try:
        lst = ast.literal_eval(rep)
        if isinstance(lst, list):
            return [str(x) for x in lst]
    except Exception:
        pass
    # fallback: split by non-word
    return re.split(r"[,\s]+", rep)[:15]


def parse_title(name_field: str) -> str:
    """Extract a human-readable title from topics_llm.csv 'Name' column."""
    # Common patterns: "0_**Title**", "3_Title", "7_**Title**\n___".
    # Drop leading numeric prefix and markdown.
    # 1) remove numeric and underscore prefix
    cleaned = re.sub(r"^\d+[_-]", "", name_field)
    # 2) remove markdown bold or italics markers
    cleaned = re.sub(r"[*_`#]", "", cleaned)
    # 3) take first line
    return cleaned.split("\n")[0].strip()


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
    # CSV fallback (existing behaviour)
    df = pd.read_csv(titles_path)
    if "Name" in df.columns:
        return {int(r.Topic): parse_title(str(r.Name)) for _, r in df.iterrows() if r.Topic != -1}
    if "Title" in df.columns:
        return {int(r.Topic): str(r.Title).strip() for _, r in df.iterrows() if r.Topic != -1}
    return {}


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Evaluate topic titles with an LLM (cloud Gemini API or local Gemma)")
    p.add_argument("--outputs_root", default=Path(__file__).resolve().parent.parent / "outputs", type=Path, help="Root outputs directory (default: topic_modeling/outputs)")
    p.add_argument("--version", choices=["v1", "v2", "v3"], help="Pipeline version to evaluate")
    p.add_argument("--consultation_id", type=int, required=True)

    use_grp = p.add_mutually_exclusive_group()
    use_grp.add_argument("--gemini", action="store_true", help="Use Gemini API backend (default)")
    use_grp.add_argument("--local", action="store_true", help="Use local Gemma backend")

    # Gemini API settings
    p.add_argument("--api_key", default=os.getenv("GEMINI_API_KEY"), help="API key for Google Gemini (needed when --gemini)")
    p.add_argument("--model", default=DEFAULT_MODEL_ID, help="Model ID for Gemini API backend")

    # Local Gemma settings
    p.add_argument("--gemma_path", default=DEFAULT_GEMMA_PATH, help="Path to local Gemma root (used when --local)")

    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--dump_prompts", action="store_true", help="Write the full prompts to disk instead of calling the LLM (useful for manual inspection)")
    args = p.parse_args()

    # ------------------------------------------------------------------
    # Resolve version directory
    # ------------------------------------------------------------------
    if args.version is None:
        # Auto-pick newest version directory that exists
        for v in ("v3", "v2", "v1"):
            tentative = args.outputs_root / v / str(args.consultation_id)
            if tentative.exists():
                args.version = v
                break
        if args.version is None:
            raise SystemExit("Could not auto-detect version outputs – specify --version.")

    out_dir = args.outputs_root / args.version / str(args.consultation_id)
    if not out_dir.exists():
        raise SystemExit(f"Outputs directory {out_dir} does not exist – run the pipeline first.")

    # Representative comments path varies per version
    rep_path = None
    if args.version == "v1":
        rep_path = out_dir / "reps" / "representative_comments_v1.csv"
    elif args.version == "v2":
        rep_path = out_dir / "reps" / "representative_comments_v2.csv"
    elif args.version == "v3":
        rep_path = out_dir / "reps" / "representative_comments_v3.csv"
    if not rep_path or not rep_path.exists():
        # fallback to generic filename
        rep_path = out_dir / "reps" / "representative_comments.csv"
    if not rep_path.exists():
        raise SystemExit(f"Representative comments file {rep_path} not found.")

    # Titles file
    titles_path = None
    if args.version == "v1":
        titles_path = out_dir / "titles" / "topics_llm_v1.jsonl"
    elif args.version == "v2":
        titles_path = out_dir / "titles" / "topics_llm_v2.jsonl"
    elif args.version == "v3":
        titles_path = out_dir / "titles" / "topics_llm_v3.jsonl"
    if not titles_path.exists():
        # fallback legacy name
        titles_path = out_dir / "titles" / "topics_llm.csv"

    # ------------------------------------------------------------------
    # Initialise generator depending on provider
    # ------------------------------------------------------------------

    provider = "local_gemma" if args.local else "gemini_api"

    if provider == "gemini_api":
        if not args.api_key:
            raise SystemExit("Provide --api_key or set GEMINI_API_KEY env var when using Gemini backend.")
        generate_fn = init_gemini(args.api_key, args.model, args.temperature)
    else:  # local
        generate_fn = init_local_gemma(args.gemma_path, temperature=args.temperature)

    rep_df = pd.read_csv(rep_path)

    # Load titles map smartly (jsonl or csv)
    title_map = _load_titles_map(titles_path)

    results: List[Dict[str, Any]] = []

    # If user only wants prompts, prepare directory early
    prompt_dump_dir: Path | None = None
    if args.dump_prompts:
        prompt_dump_dir = out_dir / "evaluation" / "prompts"
        prompt_dump_dir.mkdir(parents=True, exist_ok=True)

    for topic_id, group in rep_df.groupby("Topic"):
        if topic_id == -1:
            continue  # skip noise topic
        comments = group["content"].tolist()[:10] if "content" in group.columns else group["comment_text"].tolist()[:10]
        if "Representation" in group.columns:
            keywords = parse_keywords(group["Representation"].iloc[0])
        elif "key_phrase" in group.columns:
            keywords = list(group["key_phrase"].unique())[:15]
        else:
            keywords = []
        title = title_map.get(topic_id, f"Θέμα {topic_id}")
        explanation = "Σύνοψη βάσει λέξεων-κλειδιών."  # placeholder; could be improved

        user_prompt = build_prompt(title, explanation, comments, keywords)
        evaluation_text = ""
        # --------------------------------------------------
        # Either call the model or just dump the prompt
        # --------------------------------------------------
        if args.dump_prompts and prompt_dump_dir is not None:
            dump_path = prompt_dump_dir / f"prompt_topic_{topic_id}.txt"
            dump_path.write_text(user_prompt, encoding="utf-8")
            evaluation_text = "(prompt dumped, no call)"
        else:
            try:
                evaluation_text = generate_fn(user_prompt)
            except GeminiSafetyError as e:
                # Abort the entire run immediately to avoid burning tokens on subsequent calls
                print(f"[safety] Aborting evaluation: {e}")
                sys.exit(1)
            except Exception as e:
                evaluation_text = f"ERROR: {e}"

        # --------------------------------------------------
        # Extract numeric score (handles "4/5" or "3.5/5")
        # --------------------------------------------------
        score_val = None
        score_match = re.search(
            r"(?:Βαθμολογία|Συνολική\s+Βαθμολογία|Overall\s+Score)\s*[:\-]?\s*([0-5](?:[.,]\d+)?)\s*(?:/\s*5)?",
            evaluation_text,
            flags=re.IGNORECASE,
        )
        if not score_match:
            # fallback: any standalone `x/5` or plain number preceded by the keyword "Βαθμολογία"
            score_match = re.search(r"\b([0-5](?:[.,]\d+)?)\s*/\s*5\b", evaluation_text)
            if not score_match:
                score_match = re.search(r"Βαθμολογία\s*[:\-]?\s*([0-5](?:[.,]\d+)?)\b", evaluation_text)
        if score_match:
            try:
                score_val = float(score_match.group(1).replace(",", "."))
            except ValueError:
                pass

        results.append({
            "topic": topic_id,
            "title": title,
            "score": score_val,
            "raw_response": evaluation_text,
        })

    evaluation_dir = out_dir / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    out_file = evaluation_dir / f"evaluation_results_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    pd.DataFrame(results).to_csv(out_file, index=False)
    print(f"Saved evaluation of {len(results)} topics to {out_file}")

    if args.dump_prompts:
        print(f"All prompts written to {prompt_dump_dir}")


if __name__ == "__main__":
    main() 