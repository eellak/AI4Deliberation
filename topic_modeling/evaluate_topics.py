"""
Usage cheatsheet
+----------------

Cloud backend (Gemini API)
    export GEMINI_API_KEY=…
    python evaluate_topics.py --gemini              # optional: --model models/gemini-pro

Local backend (Gemma checkpoint)
    python evaluate_topics.py --local               # optional: --gemma_path /path/to/gemma

Other useful flags
    --outputs_dir DIR       where the CSVs live (default topic_model_outputs/)
    --temperature 0.3       sampling temperature for either backend

"""

import argparse
import datetime as dt
from pathlib import Path
from typing import List, Dict, Any, Callable
import os
import re
import ast
import pandas as pd

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

DEFAULT_MODEL_ID = "models/gemini-2.5-flash"
DEFAULT_GEMMA_PATH = "/home/glossapi/.cache/huggingface/hub/models--google--gemma-3-4b-it"

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def init_gemini(api_key: str, model_name: str, temperature: float) -> Callable[[str], str]:
    if genai is None:
        raise ImportError("google-generativeai package is required for provider 'gemini_api'.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    cfg = {
        "temperature": temperature,
        "top_p": 0.9,
        "top_k": 40,
        "max_output_tokens": 1024,
    }

    def _generate(prompt: str) -> str:
        return model.generate_content(prompt, generation_config=cfg).text  # type: ignore

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
        inputs = tokenizer(text=prompt, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[1]
        out = model.generate(**inputs, max_new_tokens=1024, temperature=temperature)
        return tokenizer.decode(out[0][input_len:], skip_special_tokens=True)

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


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Evaluate topic titles with an LLM (cloud Gemini API or local Gemma)")
    p.add_argument("--outputs_dir", default=Path(__file__).parent / "topic_model_outputs", type=Path)

    use_grp = p.add_mutually_exclusive_group()
    use_grp.add_argument("--gemini", action="store_true", help="Use Gemini API backend (default)")
    use_grp.add_argument("--local", action="store_true", help="Use local Gemma backend")

    # Gemini API settings
    p.add_argument("--api_key", default=os.getenv("GEMINI_API_KEY"), help="API key for Google Gemini (needed when --gemini)")
    p.add_argument("--model", default=DEFAULT_MODEL_ID, help="Model ID for Gemini API backend")

    # Local Gemma settings
    p.add_argument("--gemma_path", default=DEFAULT_GEMMA_PATH, help="Path to local Gemma root (used when --local)")

    p.add_argument("--temperature", type=float, default=0.2)
    args = p.parse_args()

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

    rep_path = args.outputs_dir / "representative_comments.csv"
    topics_llm_path = args.outputs_dir / "topics_llm.csv"

    if not rep_path.exists():
        raise SystemExit(f"File {rep_path} not found. Run consultation_topic_modeling.py first.")

    rep_df = pd.read_csv(rep_path)

    # If titles generated by LLM exist, use them; else fabricate simple placeholder titles.
    if topics_llm_path.exists():
        topics_df = pd.read_csv(topics_llm_path)
        if "Name" in topics_df.columns:
            title_map = {row.Topic: parse_title(str(row.Name)) for _, row in topics_df.iterrows() if row.Topic != -1}
        elif "Title" in topics_df.columns:
            title_map = {row.Topic: str(row.Title).strip() for _, row in topics_df.iterrows() if row.Topic != -1}
        else:
            title_map = {}
    else:
        title_map = {}

    results: List[Dict[str, Any]] = []

    for topic_id, group in rep_df.groupby("Topic"):
        if topic_id == -1:
            continue  # skip noise topic
        comments = group["content"].tolist()[:10]
        keywords_str = group["Representation"].iloc[0] if "Representation" in group.columns else ""
        keywords = parse_keywords(keywords_str)  # list
        title = title_map.get(topic_id, f"Θέμα {topic_id}")
        explanation = "Σύνοψη βάσει λέξεων-κλειδιών."  # placeholder; could be improved

        user_prompt = build_prompt(title, explanation, comments, keywords)
        evaluation_text = ""
        try:
            evaluation_text = generate_fn(user_prompt)
        except Exception as e:
            evaluation_text = f"ERROR: {e}"

        # Parse numeric score quick-and-dirty
        m = re.search(r"([1-5])\s*(?:/|\s*από)?\s*5", evaluation_text)
        score = int(m.group(1)) if m else None

        results.append({
            "topic": topic_id,
            "title": title,
            "score": score,
            "raw_response": evaluation_text,
        })

    out_file = args.outputs_dir / f"evaluation_results_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    pd.DataFrame(results).to_csv(out_file, index=False)
    print(f"Saved evaluation of {len(results)} topics to {out_file}")


if __name__ == "__main__":
    main() 