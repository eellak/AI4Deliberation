# consultation_topic_modeling_v2.py
# Improved consultation topic modeling pipeline with LLM-powered titling & evaluation
# -------------------------------------------------------------
# This version introduces:
#   • Automatic stop-word generation from corpus statistics
#   • Pluggable embedding back-ends (Greek SBERT, GTE-large)
#   • Explicit UMAP+HDBSCAN clustering fed to BERTopic
#   • Quantile-based representative comment selection
#   • Strict-JSON LLM prompt for topic titles (Gemma)
#   • Optional automatic LLM evaluation of titles
# -------------------------------------------------------------
# Quick usage:
#   python consultation_topic_modeling_v2.py \
#          --consultation_id 320 \
#          --db_url postgresql://user:pass@host/dbname \
#          --embedding_backend sbert \
#          --gemma_path /path/to/gemma-3-4b-it
# Run with --help to view all optional arguments.
# -------------------------------------------------------------

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any, Set

import pandas as pd
import sqlalchemy
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Third-party ML libs – all optional; import errors are handled per usage
# ---------------------------------------------------------------------------
try:
    import spacy
except ImportError:  # pragma: no cover
    spacy = None  # type: ignore

try:
    import snowballstemmer
except ImportError:  # pragma: no cover
    snowballstemmer = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except ImportError:  # pragma: no cover
    SentenceTransformer = None  # type: ignore

try:
    import umap  # type: ignore
except ImportError:  # pragma: no cover
    umap = None  # type: ignore

try:
    from hdbscan import HDBSCAN  # type: ignore
except ImportError:  # pragma: no cover
    HDBSCAN = None  # type: ignore

try:
    from bertopic import BERTopic  # type: ignore
    from bertopic.backend._utils import select_backend  # type: ignore
    from bertopic.vectorizers import ClassTfidfTransformer  # type: ignore
except ImportError:  # pragma: no cover
    BERTopic = None  # type: ignore

# OpenAI functionality has been removed in this version
openai = None  # type: ignore

try:
    from transformers import (
        AutoProcessor,
        Gemma3ForConditionalGeneration,
        BitsAndBytesConfig,
        LogitsProcessorList,
        LogitsProcessor,
    )  # type: ignore
except ImportError:  # pragma: no cover
    AutoProcessor = Gemma3ForConditionalGeneration = BitsAndBytesConfig = None  # type: ignore

try:
    import torch  # type: ignore
except ImportError:  # pragma: no cover
    torch = None  # type: ignore

# Optional grammar checker ---------------------------------------------------
try:
    import language_tool_python  # type: ignore
except ImportError:  # pragma: no cover
    language_tool_python = None  # type: ignore

# ---------------------------------------------------------------------------
# CONSTANTS & DEFAULTS
# ---------------------------------------------------------------------------
OUTPUT_ROOT = (Path(__file__).resolve().parent.parent / "outputs").resolve()
VERSION_TAG = "v2"
DEFAULT_DB_SQLITE = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"
DEFAULT_GEMMA_PATH = os.environ.get(
    "GEMMA_PATH", "/home/glossapi/.cache/huggingface/hub/models--google--gemma-3-4b-it"
)
EMBEDDING_MODELS = {
    "sbert": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "gte_large": "thenlper/gte-large",
}

# ---------------------------------------------------------------------------
# TEXT UTILITIES
# ---------------------------------------------------------------------------

def _require(name: str, mod):
    if mod is None:
        raise SystemExit(f"The optional dependency '{name}' is required for this feature – please install it.")


def strip_accents(text: str) -> str:
    """Remove Greek diacritics (tonos)."""
    import unicodedata as ud

    d = {ord("\N{COMBINING ACUTE ACCENT}"): None}
    return ud.normalize("NFD", text).translate(d)


def load_spacy_el() -> "spacy.Language":
    _require("spacy", spacy)
    for model_name in ("el_core_news_lg", "el_core_news_sm"):
        try:
            return spacy.load(model_name, disable=["parser", "senter", "attribute_ruler", "ner"])
        except OSError:
            continue
    raise SystemExit(
        "Neither 'el_core_news_lg' nor 'el_core_news_sm' SpaCy models are installed.\n"
        "Install one with: python -m spacy download el_core_news_sm"
    )


def clean_comment(txt: str, *, nlp, stopwords: Set[str]) -> str:
    """Lemmatise, lowercase, strip accents & digits, drop stop-words."""
    tokens = [tok.lemma_ for tok in nlp(txt)]
    joined = " ".join(tokens)
    joined = re.sub(r"\d+", "", joined)
    joined = strip_accents(joined.lower())
    return " ".join(w for w in joined.split() if w not in stopwords)


# ---------------------------------------------------------------------------
# DATA ACCESS
# ---------------------------------------------------------------------------

def get_engine(db_url: Optional[str]) -> sqlalchemy.engine.Engine:
    if not db_url:
        if os.path.exists(DEFAULT_DB_SQLITE):
            db_url = f"sqlite:///{DEFAULT_DB_SQLITE}"
            print(f"[info] Using fallback SQLite database at {DEFAULT_DB_SQLITE}")
        else:
            raise SystemExit(
                "Database URL was not provided. Pass --db_url or set DB_URL env var."
            )
    try:
        engine = create_engine(db_url)
        engine.connect()
        return engine
    except sqlalchemy.exc.SQLAlchemyError as exc:
        raise SystemExit(f"Failed to connect to database: {exc}")


def fetch_comments(engine, consultation_id: int) -> pd.DataFrame:
    sql = """
        SELECT comments.content
        FROM comments
        JOIN articles       ON comments.article_id      = articles.id
        JOIN consultations  ON articles.consultation_id = consultations.id
        WHERE consultations.id = :cid
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"cid": consultation_id})


def fetch_articles(engine, consultation_id: int) -> pd.DataFrame:
    sql = """
        SELECT content
        FROM articles
        WHERE consultation_id = :cid
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"cid": consultation_id})


# ---------------------------------------------------------------------------
# EMBEDDING GENERATION
# ---------------------------------------------------------------------------

def embed_texts(texts: List[str], *, backend: str):
    """Return embeddings using the selected Sentence-Transformers backend (OpenAI support removed)."""
    backend = backend.lower()

    # Sentence-Transformers back-ends only --------------------------
    _require("sentence_transformers", SentenceTransformer)
    model_name = EMBEDDING_MODELS.get(backend)
    if model_name is None:
        raise SystemExit(f"Unknown embedding backend '{backend}'. Choose from {list(EMBEDDING_MODELS)}.")
    model = SentenceTransformer(model_name, device="cuda" if torch.cuda.is_available() else "cpu")  # type: ignore
    return model.encode(texts, show_progress_bar=True, batch_size=64)


# ---------------------------------------------------------------------------
# TOPIC MODELING
# ---------------------------------------------------------------------------

def train_topic_model(
    corpus_clean: List[str],
    embeddings,
    *,
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    hdb_min_cluster_size: int = 10,
    hdb_min_samples: int = 5,
    random_state: int | None = None,
):
    _require("bertopic", BERTopic)
    # Configure custom UMAP + HDBSCAN
    _require("umap", umap)
    _require("hdbscan", HDBSCAN)

    umap_model = umap.UMAP(
        n_neighbors=umap_n_neighbors,
        min_dist=umap_min_dist,
        metric="cosine",
        random_state=random_state,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=hdb_min_cluster_size,
        min_samples=hdb_min_samples,
        metric="euclidean",
        prediction_data=True,
        gen_min_span_tree=True,
    )

    ctfidf_model = ClassTfidfTransformer(reduce_frequent_words=True)

    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        language="multilingual",
        calculate_probabilities=True,
        ctfidf_model=ctfidf_model,
    )
    topics, probs = topic_model.fit_transform(corpus_clean, embeddings)
    return topic_model, topics, probs


# ---------------------------------------------------------------------------
# LLM FOR TITLES
# ---------------------------------------------------------------------------

_JSON_PROMPT_TEMPLATE = (
    "Είσαι αξιολογητής θεματικών σε δημόσιες διαβουλεύσεις.\n"
    "Διάβασε προσεκτικά τα σχόλια και τις λέξεις-κλειδιά.\n"
    "Παρήγαγε ΜΟΝΟ ΚΑΘΑΡΟ JSON (χωρίς ```json``` ή άλλο κείμενο).\n"
    "Σχήμα: {{\"title\": \"<έως 12 λέξεις>\", \"explanation\": \"<1-2 προτάσεις>\"}}.\n"
    "Παράδειγμα:\n"
    "{{\"title\": \"Ενίσχυση εθελοντών πυροσβεστών\", \"explanation\": \"Τα σχόλια επισημαίνουν ανάγκη για εκπαίδευση και θεσμικό πλαίσιο\"}}\n"
    "===== ΣΧΟΛΙΑ =====\n{comments}\n\nΛέξεις-κλειδιά: {keywords}\n===== ΤΕΛΟΣ ====="
)


def _prompt_title_json(comments: List[str], keywords: str) -> str:
    comments_block = "\n".join([f"{i+1}. \"{c}\"" for i, c in enumerate(comments)])
    return _JSON_PROMPT_TEMPLATE.format(comments=comments_block, keywords=keywords)


# Initialise LanguageTool Greek once (if available)
LT_TOOL = None
if language_tool_python is not None:
    try:
        LT_TOOL = language_tool_python.LanguageTool("el")
    except Exception:
        LT_TOOL = None


def _spell_correct(text: str) -> str:
    if LT_TOOL is None:
        return text
    try:
        matches = LT_TOOL.check(text)
        return language_tool_python.utils.correct(text, matches)  # type: ignore
    except Exception:
        return text


def generate_titles_llm(
    rep_df: pd.DataFrame,
    titles_dir: Path,
    *,
    gemma_root: str,
    temperature: float = 0.2,
    enable_spellcheck: bool = True,
) -> pd.DataFrame:
    # Gemma-based generation -----------------------------------------
    _require("transformers", AutoProcessor)
    # Resolve snapshot dir automatically (same logic as v1)
    root_path = Path(gemma_root)
    snaps = root_path / "snapshots"
    if snaps.is_dir():
        subdirs = sorted([d for d in snaps.iterdir() if d.is_dir()])
        if subdirs:
            gemma_root = str(subdirs[0])
    _require("transformers", AutoProcessor)

    # Load Gemma in half-precision FP16/BF16 on GPU 0.  Fits ~24 GB cards and
    # preserves full language fidelity (quantisation sometimes corrupts Greek).
    model = (
        Gemma3ForConditionalGeneration.from_pretrained(
            gemma_root,
            device_map="auto",
            torch_dtype="auto",
        ).eval()
    )
    tokenizer = AutoProcessor.from_pretrained(gemma_root)

    def _generate(text: str) -> str:
        """Two-pass generation. 1) deterministic, 2) sampled fallback."""
        enc = tokenizer(
            text=text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        ).to(model.device)
        inp_len = enc["input_ids"].shape[1]

        class _Safe(LogitsProcessor):
            def __call__(self, _ids, scores):  # type: ignore[override]
                # replace NaN / Inf before softmax
                return torch.nan_to_num(scores, nan=-50.0, posinf=50.0, neginf=-50.0).clamp_(-50, 50)

        common_args = dict(
            **enc,
            max_new_tokens=120,
            logits_processor=LogitsProcessorList([_Safe()]),
        )

        # Try up to 3 sampled generations (temp 0.25) until something that looks like JSON
        for attempt in range(3):
            ids = model.generate(
                do_sample=True,
                temperature=max(0.15, temperature),
                **common_args,
            )
            txt = tokenizer.decode(ids[0][inp_len:], skip_special_tokens=True).strip()
            if "{" in txt and "}" in txt:
                return txt
        # Last fallback – return whatever greedy produced (may be empty)
        ids = model.generate(do_sample=False, **common_args)
        return tokenizer.decode(ids[0][inp_len:], skip_special_tokens=True).strip()

    outputs: List[Dict[str, Any]] = []

    for topic_id, group in rep_df.groupby("Topic"):
        if topic_id == -1:
            continue
        comments = group["content"].tolist()[:10]
        keywords = group["Representation"].iloc[0] if "Representation" in group.columns else ""
        prompt = _prompt_title_json(comments, keywords)
        # cache by prompt sha256
        h = hashlib.sha256(prompt.encode()).hexdigest()
        cache_dir = titles_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{h}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
        else:
            raw = _generate(prompt)
            try:
                # Some models wrap JSON inside markdown ```json blocks; strip if present
                cleaned_raw = raw.strip()
                fence_pat = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
                m = fence_pat.search(cleaned_raw)
                if m:
                    cleaned_raw = m.group(1)
                # Attempt to load cleaned JSON
                data = json.loads(cleaned_raw)
            except json.JSONDecodeError:
                # Attempt regex extraction for title/explanation even if JSON invalid
                title_match = re.search(r"\"title\"\s*:\s*\"([^\"]+)\"", cleaned_raw)
                expl_match = re.search(r"\"explanation\"\s*:\s*\"([^\"]+)\"", cleaned_raw)
                title_fallback = title_match.group(1) if title_match else cleaned_raw[:120]
                expl_fallback = expl_match.group(1) if expl_match else ""
                data = {"title": title_fallback, "explanation": expl_fallback}

        # Remove any leftover markdown fences or line breaks from title
        tidy_title = re.sub(r"```.*?```", "", data.get("title", ""), flags=re.DOTALL).strip()
        tidy_expl = data.get("explanation", "").strip()

        if enable_spellcheck:
            tidy_title = _spell_correct(tidy_title)
            tidy_expl = _spell_correct(tidy_expl)

        outputs.append({"Topic": topic_id, "Title": tidy_title, "Explanation": tidy_expl})

    return pd.DataFrame(outputs)


# ---------------------------------------------------------------------------
# REPRESENTATIVE COMMENT SELECTION
# ---------------------------------------------------------------------------

def build_representative_comments(
    merged: pd.DataFrame,
    *,
    rep_quantile: float = 0.8,
    max_comments_per_topic: int = 10,
    exclude_topics: Optional[Set[int]] = None,
) -> pd.DataFrame:
    if exclude_topics is None:
        exclude_topics = set()
    # Compute threshold from global probability distribution
    thresh = merged["Probability"].quantile(rep_quantile)
    filtered = merged[merged["Probability"] >= thresh]
    if exclude_topics:
        filtered = filtered[~filtered["Topic"].isin(exclude_topics)]
    rep = (
        filtered.sort_values("Probability", ascending=False)
        .groupby("Topic")
        .head(max_comments_per_topic)
    )
    drop_cols = [c for c in ("Document", "content_clean", "Name", "Representative_document", "Representative_Docs") if c in rep.columns]
    return rep.drop(columns=drop_cols)


# ---------------------------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None):
    p = argparse.ArgumentParser(description="Consultation topic modeling with LLM improvements (v2)")

    # Core options -----------------------------------------------------
    p.add_argument("--consultation_id", type=int, required=True)
    p.add_argument("--db_url", default=os.getenv("DB_URL"))
    p.add_argument("--output_root", type=Path, default=OUTPUT_ROOT)

    # Text cleaning ----------------------------------------------------
    p.add_argument("--freq_stopword_pct", type=float, default=0.01, help="Top percentage of most frequent words to drop as stopwords")

    # Embeddings -------------------------------------------------------
    p.add_argument("--embedding_backend", choices=[*EMBEDDING_MODELS.keys()], default="sbert")

    # Clustering params -----------------------------------------------
    p.add_argument("--umap_n", type=int, default=15)
    p.add_argument("--umap_min_dist", type=float, default=0.1)
    p.add_argument("--hdb_min_cluster_size", type=int, default=10)
    p.add_argument("--hdb_min_samples", type=int, default=5)
    p.add_argument("--random_state", type=int, default=None, help="Random seed for UMAP/HDBSCAN reproducibility")

    # Representative selection ----------------------------------------
    p.add_argument("--rep_quantile", type=float, default=0.8)
    p.add_argument("--max_comments_per_topic", type=int, default=10)
    p.add_argument("--exclude_topics", default="1", help="Comma-separated list of topic IDs to skip")

    # Gemma model path (title generation is always on)
    p.add_argument("--gemma_path", default=DEFAULT_GEMMA_PATH, help="Path to local Gemma model cache")

    # Evaluation -------------------------------------------------------
    p.add_argument("--auto_evaluate", action="store_true", help="Run automatic LLM evaluation of titles after generation")

    # New parameters for LLM title generation
    p.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature for LLM title generation")
    p.add_argument("--no_spellcheck", action="store_true", help="Disable LanguageTool spell/grammar correction")

    args = p.parse_args(argv)

    # ------------------------------------------------------------------
    # Build structured output directories
    # ------------------------------------------------------------------
    out_dir: Path = args.output_root / VERSION_TAG / str(args.consultation_id)
    raw_dir = out_dir / "raw"
    cluster_dir = out_dir / "clustering"
    reps_dir = out_dir / "reps"
    titles_dir = out_dir / "titles"
    evaluation_dir = out_dir / "evaluation"

    for d in (raw_dir, cluster_dir, reps_dir, titles_dir, evaluation_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Fetch data
    # ------------------------------------------------------------------
    engine = get_engine(args.db_url)
    comments_df = fetch_comments(engine, args.consultation_id)
    if comments_df.empty:
        raise SystemExit("No comments fetched – check consultation ID or DB permissions.")
    articles_df = fetch_articles(engine, args.consultation_id)

    # ------------------------------------------------------------------
    # 2. Build stopwords
    # ------------------------------------------------------------------
    stemmer = snowballstemmer.stemmer("greek") if snowballstemmer else None  # type: ignore
    nlp = load_spacy_el()

    # Frequency-based stopwords over articles+comments
    all_tokens = []
    for doc in pd.concat([articles_df["content"], comments_df["content"]]):
        cleaned = strip_accents(doc.lower())
        all_tokens.extend(re.split(r"\W+", cleaned))
    word_counter = Counter(all_tokens)
    most_common_cutoff = int(len(word_counter) * args.freq_stopword_pct)
    freq_stop = {w for w, _ in word_counter.most_common(most_common_cutoff)}

    # ------------------------------------------------------------
    # Load extra stop-words from external file (one token per line)
    # ------------------------------------------------------------
    STOPWORD_FILE = Path(__file__).resolve().parent.parent / "stopwords_el.txt"
    extra_stop: set[str] = set()
    if STOPWORD_FILE.exists():
        extra_stop = {w.strip() for w in STOPWORD_FILE.read_text(encoding="utf-8").splitlines() if w.strip()}

    stopwords = freq_stop | extra_stop

    # ------------------------------------------------------------------
    # 3. Clean comments + dedup
    # ------------------------------------------------------------------
    comments_df.drop_duplicates(subset=["content"], inplace=True)
    comments_df["content_clean"] = comments_df["content"].apply(lambda t: clean_comment(t, nlp=nlp, stopwords=stopwords))
    comments_df.drop_duplicates(subset=["content_clean"], inplace=True)

    cleaned_csv = raw_dir / "cleaned_v2.csv"
    comments_df.to_csv(cleaned_csv, index=False)

    # ------------------------------------------------------------------
    # 4. Embeddings
    # ------------------------------------------------------------------
    embeddings = embed_texts(
        comments_df["content_clean"].tolist(),
        backend=args.embedding_backend,
    )

    # ------------------------------------------------------------------
    # 5. Topic modeling
    # ------------------------------------------------------------------
    topic_model, topics, probs = train_topic_model(
        comments_df["content_clean"].tolist(),
        embeddings,
        umap_n_neighbors=args.umap_n,
        umap_min_dist=args.umap_min_dist,
        hdb_min_cluster_size=args.hdb_min_cluster_size,
        hdb_min_samples=args.hdb_min_samples,
        random_state=args.random_state,
    )

    doc_info = topic_model.get_document_info(comments_df["content_clean"])
    doc_info["content_clean"] = doc_info["Document"]
    merged = pd.merge(comments_df, doc_info, on="content_clean")

    topics_csv = cluster_dir / "topics_v2.csv"
    merged.to_csv(topics_csv, index=False)

    # ------------------------------------------------------------------
    # 6. Representative comments
    # ------------------------------------------------------------------
    try:
        exclude_set = {int(t.strip()) for t in args.exclude_topics.split(",") if t.strip()}
    except ValueError:
        exclude_set = set()

    rep_comments = build_representative_comments(
        merged,
        rep_quantile=args.rep_quantile,
        max_comments_per_topic=args.max_comments_per_topic,
        exclude_topics=exclude_set,
    )

    rep_csv = reps_dir / "representative_comments_v2.csv"
    rep_comments.to_csv(rep_csv, index=False)

    # ------------------------------------------------------------------
    # 7. LLM titles (Gemma – mandatory)
    # ------------------------------------------------------------------
    titles_df = generate_titles_llm(
        rep_comments,
        titles_dir,
        gemma_root=args.gemma_path,
        temperature=args.temperature,
        enable_spellcheck=not args.no_spellcheck,
    )
    titles_jsonl = titles_dir / "topics_llm_v2.jsonl"
    with titles_jsonl.open("w", encoding="utf-8") as fh:
        for _, row in titles_df.iterrows():
            fh.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
    print(f"[done] Saved LLM titles to {titles_jsonl}")

    print(f"[success] Pipeline completed. Outputs at {out_dir}")


if __name__ == "__main__":
    # TorchDynamo JIT can break Gemma ↔ HF; disable defensively
    os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
    try:
        import torch  # type: ignore
    except ImportError:
        torch = None  # type: ignore
    main()
