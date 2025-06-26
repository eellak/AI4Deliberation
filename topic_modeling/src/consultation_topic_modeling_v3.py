from __future__ import annotations

# Disable TorchDynamo just-in-time compilation which breaks Gemma generation on some setups.
import os as _os
_os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

"""consultation_topic_modeling_v3.py – Hybrid key-phrase topic modeling inspired by QualIT.

Pipeline overview
-----------------
1. Clean comments (as in v2).
2. For each comment extract key-phrases with Gemma (KEY_PHRASE_EXTRACTION_PROMPT).
3. Filter hallucinated key-phrases via cosine-similarity with comment embedding (> hallucination_threshold).
4. Build BERTopic on key-phrase embeddings.
5. Map topics back to comments; save topics_v3.csv.
6. Generate titles + explanations per topic with Gemma (TOPIC_TITLING_PROMPT).
7. Store outputs under outputs/v3/{consultation_id}/

NOTE: This is a condensed implementation that reuses helper utilities from v2 and prioritises clarity over speed.

CLI usage (GPU recommended):
    python consultation_topic_modeling_v3.py \
           --consultation_id 320 \
           --db_url postgresql://user:pass@host/dbname \
           --embedding_backend sbert \
           --gemma_path /path/to/gemma-3-4b-it
Run with -h/--help for all options.
"""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import sqlalchemy
from sqlalchemy import create_engine, text

# ---- Third-party libs -------------------------------------------------------
try:
    import spacy
except ImportError:
    spacy = None  # type: ignore

try:
    import snowballstemmer
except ImportError:
    snowballstemmer = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except ImportError:
    SentenceTransformer = None  # type: ignore

try:
    from bertopic import BERTopic  # type: ignore
    from bertopic.vectorizers import ClassTfidfTransformer  # type: ignore
except ImportError:
    BERTopic = None  # type: ignore

try:
    import torch  # type: ignore
except ImportError:
    torch = None  # type: ignore

# optional grammar checker for titles
try:
    import language_tool_python  # type: ignore
except ImportError:
    language_tool_python = None  # type: ignore

import numpy as np  # dependency for caching only local embeddings

try:
    from transformers import AutoProcessor, Gemma3ForConditionalGeneration  # type: ignore
except ImportError:
    AutoProcessor = Gemma3ForConditionalGeneration = None  # type: ignore

# ---------------------------------------------------------------------------
# CONSTANTS & PROMPTS
# ---------------------------------------------------------------------------
OUTPUT_ROOT = (Path(__file__).resolve().parent.parent / "outputs").resolve()
VERSION_TAG = "v3"
DEFAULT_DB_SQLITE = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"
DEFAULT_GEMMA_PATH = os.environ.get(
    "GEMMA_PATH", "/home/glossapi/.cache/huggingface/hub/models--google--gemma-3-4b-it"
)

EMBEDDING_MODELS = {
    "sbert": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "gte_large": "thenlper/gte-large"
}

KEY_PHRASE_EXTRACTION_PROMPT = """
 Είσαι ένας εξειδικευμένος βοηθός Τεχνητής Νοημοσύνης. Ο ρόλος σου είναι να αναλύεις ένα σχόλιο χρήστη από μια δημόσια διαβούλευση και να εξάγεις μια λίστα από διακριτές, σύντομες φράσεις-κλειδιά που αντιπροσωπεύουν τα κύρια θέματα που συζητούνται. Ένα σχόλιο μπορεί να περιέχει πολλαπλά, ανεξάρτητα θέματα.

### ΚΑΝΟΝΕΣ
1.  **Μορφή Εξόδου:** Η απάντησή σου ΠΡΕΠΕΙ να είναι ΑΠΟΚΛΕΙΣΤΙΚΑ ένα έγκυρο αντικείμενο JSON.
2.  **Δομή JSON:** Το JSON πρέπει να ακολουθεί τη μορφή: `{{"key_phrases": ["φράση 1", "φράση 2", ...]}}`.
3.  **Περιεχόμενο:** Κάθε φράση-κλειδί πρέπει να είναι στα Ελληνικά και να αποτυπώνει μια αυτόνομη ιδέα.
4.  **Κενό Σχόλιο:** Αν το σχόλιο είναι κενό ή άσχετο, επέστρεψε ένα κενό JSON array: `{{"key_phrases": []}}`.

### ΕΡΓΑΣΙΑ
**Σχόλιο:**
{comment_text}

**Έξοδος JSON:**
```json
"""

TOPIC_TITLING_PROMPT = """
Είσαι ένας εξειδικευμένος αναλυτής που συνοψίζει σχόλια από δημόσιες διαβουλεύσεις. Ο ρόλος σου είναι να μελετήσεις μια ομάδα από φράσεις-κλειδιά και αντιπροσωπευτικά σχόλια που ανήκουν στο ίδιο θέμα, και να δημιουργήσεις έναν τίτλο και μια εξήγηση.

### ΚΑΝΟΝΕΣ
1.  **Μορφή Εξόδου:** Η απάντησή σου ΠΡΕΠΕΙ να είναι ΑΠΟΚΛΕΙΣΤΙΚΑ ένα έγκυρο αντικείμενο JSON. Μην προσθέτεις κανένα άλλο κείμενο πριν ή μετά το JSON.
2.  **Περιεχόμενο JSON:** Το JSON πρέπει να περιέχει ακριβώς δύο κλειδιά: `title` και `explanation`.
3.  **Τίτλος (`title`):** Πρέπει να είναι σύντομος, περιγραφικός και να αποτυπώνει την ουσία όλων των δεδομένων.
4.  **Εξήγηση (`explanation`):** Πρέπει να αιτιολογεί σύντομα γιατί επέλεξες αυτόν τον τίτλο, βασιζόμενος/η στα κοινά σημεία των φράσεων-κλειδιών και των σχολίων.
5.  **Γλώσσα:** Όλο το περιεχόμενο πρέπει να είναι στα Ελληνικά.

### ΕΡΓΑΣΙΑ
**Δεδομένα Εισόδου:**
**Φράσεις-Κλειδιά:** {key_phrases_list}
**Αντιπροσωπευτικά Σχόλια:** {representative_comments_list}

**Έξοδος JSON:**
```json
"""

# ---------------------------------------------------------------------------
# UTILS
# ---------------------------------------------------------------------------

def _require(name: str, mod):
    if mod is None:
        raise SystemExit(f"Optional dependency '{name}' is required – install it to continue.")


def strip_accents(text: str) -> str:
    import unicodedata as ud
    d = {ord("\N{COMBINING ACUTE ACCENT}"): None}
    return ud.normalize("NFD", text).translate(d)


def load_spacy_el():
    _require("spacy", spacy)
    for model_name in ("el_core_news_lg", "el_core_news_sm"):
        try:
            return spacy.load(model_name, disable=["parser", "senter", "attribute_ruler", "ner"])
        except OSError:
            continue
    raise SystemExit("Install a Greek SpaCy model: python -m spacy download el_core_news_sm")


# ---------------------------------------------------------------------------
# DATA ACCESS
# ---------------------------------------------------------------------------

def get_engine(db_url: Optional[str]):
    if not db_url:
        if os.path.exists(DEFAULT_DB_SQLITE):
            db_url = f"sqlite:///{DEFAULT_DB_SQLITE}"
            print(f"[info] Using fallback SQLite DB at {DEFAULT_DB_SQLITE}")
        else:
            raise SystemExit("Provide --db_url or set DB_URL env var.")
    try:
        engine = create_engine(db_url)
        engine.connect()
        return engine
    except sqlalchemy.exc.SQLAlchemyError as exc:
        raise SystemExit(f"DB connection failed: {exc}")


def fetch_comments(engine, consultation_id: int) -> pd.DataFrame:
    sql = """
        SELECT comments.id AS id, comments.content
        FROM comments
        JOIN articles ON comments.article_id = articles.id
        WHERE articles.consultation_id = :cid
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"cid": consultation_id})


def fetch_articles(engine, consultation_id: int) -> pd.DataFrame:
    sql = "SELECT content FROM articles WHERE consultation_id = :cid"
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"cid": consultation_id})


# ---------------------------------------------------------------------------
# EMBEDDINGS
# ---------------------------------------------------------------------------
CACHE_DIR = OUTPUT_ROOT / "embedding_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _hash_texts(texts: List[str]) -> str:
    hasher = hashlib.sha1()
    for t in texts:
        hasher.update(t.encode("utf-8", errors="ignore"))
        hasher.update(b"\0")  # separator to avoid accidental concatenation
    return hasher.hexdigest()[:16]


def embed_texts(texts: List[str], *, backend: str = "sbert"):
    """Return embeddings for *texts* using the selected backend.

    Results are cached to disk under outputs/embedding_cache/ to avoid recomputation.
    The cache key is SHA-1 over texts + backend model id.
    """
    backend = backend.lower()

    cache_key = f"{backend}_{_hash_texts(texts)}"
    cache_path = CACHE_DIR / f"{cache_key}.npy"
    if cache_path.exists():
        return np.load(cache_path)

    _require("sentence_transformers", SentenceTransformer)
    model_name = EMBEDDING_MODELS.get(backend)
    if model_name is None:
        raise SystemExit(f"Unknown embedding backend '{backend}'.")

    model = SentenceTransformer(
        model_name,
        device="cuda" if torch and torch.cuda.is_available() else "cpu",  # type: ignore
    )
    embs = model.encode(texts, show_progress_bar=False, batch_size=64)

    # Persist to cache for future use
    try:
        np.save(cache_path, embs)
    except Exception:
        pass  # non-fatal
    return embs


# ---------------------------------------------------------------------------
# KEY-PHRASE EXTRACTION + FILTERING
# ---------------------------------------------------------------------------

def _load_gemma(gemma_root: str):
    _require("transformers", AutoProcessor)
    root = Path(gemma_root)
    snaps = root / "snapshots"
    if snaps.is_dir():
        subs = sorted([d for d in snaps.iterdir() if d.is_dir()])
        if subs:
            gemma_root = str(subs[0])
    model = Gemma3ForConditionalGeneration.from_pretrained(gemma_root, device_map="auto", torch_dtype="auto").eval()
    tokenizer = AutoProcessor.from_pretrained(gemma_root)
    return model, tokenizer


def extract_and_filter_key_phrases(
    df: pd.DataFrame,
    *,
    gemma_root: str,
    hallucination_threshold: float,
    embedding_backend: str,
) -> pd.DataFrame:
    """Return DataFrame with columns: comment_id, key_phrase"""
    model, tok = _load_gemma(gemma_root)

    # Pre-embed all comment texts for later similarity calculation (vector cache)
    comment_embeddings = embed_texts(df["content_clean"].tolist(), backend=embedding_backend)

    rows: List[Dict[str, Any]] = []

    for idx, (comment_id, text, clean, comment_emb) in enumerate(
        zip(df["id"], df["content"], df["content_clean"], comment_embeddings)
    ):
        prompt = KEY_PHRASE_EXTRACTION_PROMPT.format(comment_text=text)
        enc = tok(text=prompt, return_tensors="pt").to(model.device)
        inp_len = enc["input_ids"].shape[1]
        out = model.generate(**enc, max_new_tokens=120, do_sample=False)
        out_text = tok.decode(out[0][inp_len:], skip_special_tokens=True).strip()
        # Strip possible fences
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", out_text, flags=re.DOTALL)
        if m:
            out_text = m.group(1)
        try:
            data = json.loads(out_text)
            phrases: List[str] = data.get("key_phrases", []) if isinstance(data, dict) else []
        except json.JSONDecodeError:
            phrases = []

        if not phrases:
            continue

        # Embed phrases in batch
        phrase_embs = embed_texts(phrases, backend=embedding_backend)
        for ph, ph_emb in zip(phrases, phrase_embs):
            # cosine similarity
            sim = float((ph_emb @ comment_emb) / ( (ph_emb**2).sum()**0.5 * (comment_emb**2).sum()**0.5 ))
            if sim >= hallucination_threshold:
                rows.append({"comment_id": comment_id, "key_phrase": ph, "similarity": sim})

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# TITLES WITH GEMMA (key-phrase aware)
# ---------------------------------------------------------------------------
LT_TOOL = None
if language_tool_python is not None:
    try:
        LT_TOOL = language_tool_python.LanguageTool("el")
    except Exception:
        LT_TOOL = None

def _spell_correct(txt: str) -> str:
    if LT_TOOL is None:
        return txt
    try:
        return language_tool_python.utils.correct(txt, LT_TOOL.check(txt))  # type: ignore
    except Exception:
        return txt


def generate_titles_with_gemma(
    topic_model: "BERTopic",
    kp_df: pd.DataFrame,
    titles_dir: Path,
    gemma_root: str,
    temperature: float = 0.3,
) -> pd.DataFrame:
    model, tok = _load_gemma(gemma_root)

    topic_to_phrases: Dict[int, List[str]] = defaultdict(list)
    topic_to_comments: Dict[int, List[str]] = defaultdict(list)

    for _, row in kp_df.iterrows():
        tid = row["Topic"]
        topic_to_phrases[tid].append(row["key_phrase"])
        topic_to_comments[tid].append(row["comment_text"])

    outputs = []
    for tid, phrases in topic_to_phrases.items():
        sample_phrases = phrases[:10]
        sample_comments = topic_to_comments[tid][:5]
        prompt = TOPIC_TITLING_PROMPT.format(
            key_phrases_list=json.dumps(sample_phrases, ensure_ascii=False),
            representative_comments_list=json.dumps(sample_comments, ensure_ascii=False),
        )
        enc = tok(text=prompt, return_tensors="pt").to(model.device)
        inp_len = enc["input_ids"].shape[1]
        gen_ids = model.generate(
            **enc, max_new_tokens=120, do_sample=True, temperature=max(0.1, temperature)
        )
        gen_text = tok.decode(gen_ids[0][inp_len:], skip_special_tokens=True).strip()
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", gen_text, flags=re.DOTALL)
        if m:
            gen_text = m.group(1)
        try:
            data = json.loads(gen_text)
        except json.JSONDecodeError:
            data = {"title": phrases[0][:60], "explanation": ""}
        outputs.append({"Topic": tid, "Title": _spell_correct(data.get("title", "")), "Explanation": _spell_correct(data.get("explanation", ""))})

    titles_jsonl = titles_dir / "topics_llm_v3.jsonl"
    with titles_jsonl.open("w", encoding="utf-8") as fh:
        for row in outputs:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return pd.DataFrame(outputs)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None):
    p = argparse.ArgumentParser(description="Consultation topic modeling – key-phrase hybrid (v3)")
    p.add_argument("--consultation_id", type=int, required=True)
    p.add_argument("--db_url")
    p.add_argument("--output_root", type=Path, default=OUTPUT_ROOT)

    # cleaning
    p.add_argument("--freq_stopword_pct", type=float, default=0.01)

    # embeddings
    p.add_argument("--embedding_backend", choices=list(EMBEDDING_MODELS.keys()), default="sbert")

    # clustering
    p.add_argument("--umap_n", type=int, default=15)
    p.add_argument("--umap_min_dist", type=float, default=0.1)
    p.add_argument("--hdb_min_cluster_size", type=int, default=10)
    p.add_argument("--hdb_min_samples", type=int, default=5)
    p.add_argument("--random_state", type=int)

    # hallucination
    p.add_argument("--hallucination_threshold", type=float, default=0.6)

    # titles
    p.add_argument("--gemma_path", default=DEFAULT_GEMMA_PATH)
    p.add_argument("--temperature", type=float, default=0.3)

    args = p.parse_args(argv)

    out_dir = args.output_root / VERSION_TAG / str(args.consultation_id)
    for sub in ("raw", "kp", "clustering", "reps", "titles", "hierarchy"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    engine = get_engine(args.db_url)
    comments_df = fetch_comments(engine, args.consultation_id)
    articles_df = fetch_articles(engine, args.consultation_id)
    if comments_df.empty:
        raise SystemExit("No comments fetched.")

    # Build stopwords --------------------------------------------------
    nlp = load_spacy_el()
    all_tokens = []
    for doc in pd.concat([articles_df["content"], comments_df["content"]]):
        cleaned = strip_accents(doc.lower())
        all_tokens.extend(re.split(r"\W+", cleaned))
    word_counter = Counter(all_tokens)
    top_n = int(len(word_counter) * args.freq_stopword_pct)
    freq_stop = {w for w, _ in word_counter.most_common(top_n)}

    stop_file = Path(__file__).resolve().parent.parent / "stopwords_el.txt"
    extra_stop = {w.strip() for w in stop_file.read_text(encoding="utf-8").splitlines()} if stop_file.exists() else set()
    stopwords = freq_stop | extra_stop

    # Clean comments
    comments_df["content_clean"] = comments_df["content"].apply(
        lambda t: " ".join([tok.lemma_ for tok in nlp(t)])
    )
    comments_df["content_clean"] = comments_df["content_clean"].str.lower().apply(strip_accents)

    (out_dir / "raw" / "cleaned_v3.csv").write_text(comments_df.to_csv(index=False), encoding="utf-8")

    # ------------------ Key-phrase extraction -------------------------
    kp_df = extract_and_filter_key_phrases(
        comments_df,
        gemma_root=args.gemma_path,
        hallucination_threshold=args.hallucination_threshold,
        embedding_backend=args.embedding_backend,
    )
    if kp_df.empty:
        raise SystemExit("No valid key-phrases extracted – aborting.")

    (out_dir / "kp" / "key_phrases.csv").write_text(kp_df.to_csv(index=False), encoding="utf-8")

    # Build simple representative comments set (top-N by probability later)
    kp_df_mrg = kp_df.merge(comments_df[["id", "content"]], left_on="comment_id", right_on="id", how="left").rename(columns={"content": "comment_text"})

    rep_comments_v3 = (
        kp_df_mrg.sort_values("similarity", ascending=False)
        .groupby("Topic")
        .head(10)
        .loc[:, ["Topic", "comment_text", "key_phrase", "similarity"]]
    )
    rep_comments_v3.to_csv(out_dir / "reps" / "representative_comments_v3.csv", index=False)

    # Embed key-phrases and cluster
    embs = embed_texts(kp_df["key_phrase"].tolist(), backend=args.embedding_backend)

    _require("bertopic", BERTopic)
    from hdbscan import HDBSCAN  # type: ignore
    import umap  # type: ignore

    umap_model = umap.UMAP(
        n_neighbors=args.umap_n,
        min_dist=args.umap_min_dist,
        metric="cosine",
        random_state=args.random_state,
    )
    hdb = HDBSCAN(
        min_cluster_size=args.hdb_min_cluster_size,
        min_samples=args.hdb_min_samples,
        metric="euclidean",
        prediction_data=True,
    )
    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdb,
        language="multilingual",
        ctfidf_model=ClassTfidfTransformer(reduce_frequent_words=True),
        calculate_probabilities=True,
    )
    topics, probs = topic_model.fit_transform(kp_df["key_phrase"].tolist(), embs)

    kp_df["Topic"] = topics
    kp_df["Probability"] = probs

    kp_df.to_csv(out_dir / "clustering" / "topics_kp_v3.csv", index=False)

    # Map back to comments summarising per comment
    agg = (
        kp_df.groupby("comment_id")
        .apply(lambda g: {int(t): float(max(g[g["Topic"] == t]["Probability"])) for t in g["Topic"].unique()})
        .reset_index()
        .rename(columns={0: "assigned_topics"})
    )
    merged = pd.merge(comments_df, agg, left_on="id", right_on="comment_id", how="left")
    merged.to_csv(out_dir / "clustering" / "topics_v3.csv", index=False)

    # ---------------- Titles -----------------------------------------
    titles_df = generate_titles_with_gemma(
        topic_model,
        kp_df_mrg,
        out_dir / "titles",
        gemma_root=args.gemma_path,
        temperature=args.temperature,
    )
    print("[done] Outputs saved to", out_dir)


if __name__ == "__main__":
    main() 