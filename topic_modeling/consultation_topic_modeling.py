import argparse
import os
from pathlib import Path
from collections import Counter
import unicodedata as ud
import re

import pandas as pd
import sqlalchemy
from sqlalchemy import text, create_engine
from transformers import AutoProcessor, Gemma3ForConditionalGeneration
from transformers import pipeline as hf_pipeline

import snowballstemmer
import spacy
from bertopic import BERTopic
from bertopic.representation import KeyBERTInspired, MaximalMarginalRelevance
from bertopic.vectorizers import ClassTfidfTransformer

# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------

def strip_accents(text: str) -> str:
    """Remove Greek diacritics (tonos)."""
    d = {ord("\N{COMBINING ACUTE ACCENT}"): None}
    return ud.normalize("NFD", text).translate(d)


def load_spacy_el() -> "spacy.Language":
    """Load the large Greek SpaCy model if available, else fall back to *sm*."""
    for model_name in ("el_core_news_lg", "el_core_news_sm"):
        try:
            return spacy.load(model_name, disable=["parser", "senter", "attribute_ruler", "ner"])
        except OSError:
            continue
    raise SystemExit(
        "Neither 'el_core_news_lg' nor 'el_core_news_sm' SpaCy models are installed.\n"
        "Install one with: python -m spacy download el_core_news_sm"
    )


def clean_comment(
    text: str,
    nlp: "spacy.Language",
    stemmer: "snowballstemmer.stemmer",
    stopwords: list[str],
) -> str:
    # Stem and lemmatise
    # NB: order mirrors notebook but you can tweak for speed/quality
    tokens = [tok.lemma_ for tok in nlp(text)]
    joined = " ".join(tokens)
    # Remove digits, accents, lowercase
    joined = re.sub(r"\d+", "", joined)
    joined = strip_accents(joined.lower())
    # Remove stop-words
    cleaned = " ".join(w for w in joined.split() if w not in stopwords)
    return cleaned


def build_stopwords(common_words: list[str]) -> list[str]:
    base = [
        "η",
        "οποια",
        "τι",
        "του",
        "σε",
        "που",
        "οι",
        "με",
        "στα",
        "στο",
        "στην",
        "στιν",
        "μας",
        "να",
        "κυριε",
        "κύριε",
        "της",
        "για",
        "αυτο",
        "απο",
        "των",
        "αυτοι",
        "μεσω",
        "τις",
        "την",
        "τη",
        "το",
        "και",
        "πως",
        "αλλα",
        "ειναι",
        "δεν",
        "στη",
        "αν",
        "μονο",
        "μια",
        "ενα",
        "ενας",
        "οσο",
        "αλλος",
        "περιπτωση",
        "παραλληλα",
        "παραλληλου",
        "παραλληλος",
        "νομος",
        "ειμαι",
    ]
    # merge + deduplicate
    return list(set(base + common_words))


# ---------------------------------------------------------------------------
# DATA ACCESS
# ---------------------------------------------------------------------------

def get_engine(db_url: str | None):
    """Return a SQLAlchemy engine. If *db_url* is None try env var or db_secret module."""
    if not db_url:
        # Try default local SQLite snapshot used in project
        default_sqlite = "/mnt/data/AI4Deliberation/deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"
        if os.path.exists(default_sqlite):
            db_url = f"sqlite:///{default_sqlite}"
            print(f"Using fallback SQLite database at {default_sqlite}")
        else:
            raise SystemExit(
                "Database URL was not provided. Pass --db_url, set DB_URL env var, provide db_secret.py, or ensure default SQLite path exists."
            )

    try:
        engine = create_engine(db_url)
        engine.connect()
        return engine
    except sqlalchemy.exc.SQLAlchemyError as exc:
        raise SystemExit(f"Failed to connect to database: {exc}")


def _run_query(engine, sql: str, params: dict) -> pd.DataFrame:
    """Helper: run a parametrised query and return a DataFrame (SQLAlchemy ≥2.0 safe)."""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def fetch_comments(engine, consultation_id: int) -> pd.DataFrame:
    # Use unqualified table names so the query works for both SQLite (no schema) and Postgres.
    sql = """
        SELECT comments.content
        FROM comments
        JOIN articles       ON comments.article_id      = articles.id
        JOIN consultations  ON articles.consultation_id = consultations.id
        WHERE consultations.id = :cid
    """
    return _run_query(engine, sql, {"cid": consultation_id})


def fetch_articles(engine, consultation_id: int) -> pd.DataFrame:
    sql = """
        SELECT content
        FROM articles
        WHERE consultation_id = :cid
    """
    return _run_query(engine, sql, {"cid": consultation_id})


# ---------------------------------------------------------------------------
# TOPIC MODELING PIPELINE
# ---------------------------------------------------------------------------

def train_bertopic(df_clean: pd.Series, min_topic_size: int = 10):
    representation_model = [
        KeyBERTInspired(top_n_words=15),
        MaximalMarginalRelevance(diversity=0.3, top_n_words=15),
    ]
    ctfidf_model = ClassTfidfTransformer(reduce_frequent_words=True)
    topic_model = BERTopic(
        representation_model=representation_model,
        language="multilingual",
        min_topic_size=min_topic_size,
        top_n_words=15,
        ctfidf_model=ctfidf_model,
    )
    topics, probs = topic_model.fit_transform(df_clean)
    return topic_model, topics, probs


def generate_titles_with_gemma(rep_df: pd.DataFrame, gemma_root: str, device: str = "auto") -> pd.DataFrame:
    """Generate a concise title + short explanation for each topic using Gemma and the exact prompt from the notebook."""

    # Resolve snapshots subdir automatically
    root_path = Path(gemma_root)
    snaps = root_path / "snapshots"
    if snaps.is_dir():
        subdirs = sorted([d for d in snaps.iterdir() if d.is_dir()])
        if subdirs:
            gemma_root = str(subdirs[0])

    model = Gemma3ForConditionalGeneration.from_pretrained(
        gemma_root, device_map=device, torch_dtype="auto"
    ).eval()
    tokenizer = AutoProcessor.from_pretrained(gemma_root)

    PROMPT_TXT = (
        "Είσαι αξιολογητής θεματικής συνάφειας σε δημόσιες διαβουλεύσεις.\n"
        "Θα σου δίνονται τα δέκα πιο αντιπροσωπευτικά σχόλια χρηστών και λέξεις-κλειδιά που συνοψίζουν το περιεχόμενό του για μια συγκεκριμένη διαβούλευση. \n"
        "Οδηγίες:\n"
        "Να διαβάσεις προσεκτικά όλα τα σχόλια μαζί με τις αντίστοιχες λέξεις-κλειδιά.\n"
        "Να εντοπίσεις το βασικό θέμα ή θεματική ενότητα στην οποία εντάσσονται. τα σχόλια συνολικά.\n"
        "Να δώσεις έναν σύντομο, αντιπροσωπευτικό και περιγραφικό τίτλο για τη θεματική αυτή (π.χ. \"οργανωτικά και Υπηρεσιακά Θέματα Πυροσβεστικού Σώματος και Πολιτικής Προστασίας\").\n"
        "Παρουσίασε ως έξοδο μόνο:\n"
        "Τον τίτλο της θεματικής\n"
        "Μια σύντομη εξήγηση για την επιλογή του τίτλου"
    )

    outputs = []

    for topic_id, group in rep_df.groupby("Topic"):
        if topic_id == -1:
            continue

        comments_block = "\n".join([f"{i}. \"{c}\"" for i, c in enumerate(group["content"].tolist()[:10])])
        keywords = group["Representation"].iloc[0]

        user_prompt = f"{comments_block}\nΛέξεις-κλειδιά: {keywords}\n\n{PROMPT_TXT}"

        # Gemma3Processor expects the prompt under the 'text' keyword.
        inputs = tokenizer(text=user_prompt, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[1]
        out_ids = model.generate(**inputs, max_new_tokens=120, do_sample=False)
        gen_text = tokenizer.decode(out_ids[0][input_len:], skip_special_tokens=True)

        # ------------------------------
        # Robust post-processing
        # ------------------------------
        clean_text = gen_text.strip()

        # 1) Try to capture after the explicit label «Τίτλος:»
        title = ""
        explanation = ""

        title_match = re.search(r"Τίτλος\s*:\s*(.+)", clean_text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).split("\n")[0].strip(" .-*_")

        # 2) Fallback: first non-empty line that is not merely punctuation or a
        # placeholder like "(1-2 προτάσεις)"
        if not title:
            for line in clean_text.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                # ignore pure punctuation / dot lines or short parenthetical notes
                if re.fullmatch(r"[.()\-–\s]+", stripped):
                    continue
                if re.fullmatch(r"\(.*?προτάσεις.*?\)", stripped, flags=re.IGNORECASE):
                    continue
                title = stripped.strip(" .-*_")
                break

        if not title:
            title = clean_text[:60]

        # Extract explanation section if present
        expl_match = re.search(r"Εξήγηση\s*:\s*(.+)", clean_text, re.IGNORECASE | re.DOTALL)
        if expl_match:
            explanation = expl_match.group(1).strip()
        else:
            # Fallback: everything after first line used as title
            parts = [l.strip() for l in clean_text.split("\n") if l.strip()]
            explanation = " ".join(parts[1:]) if len(parts) > 1 else ""

        outputs.append({"Topic": topic_id, "Title": title, "Explanation": explanation, "Raw": gen_text})

    return pd.DataFrame(outputs)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run BERTopic on Greek consultation comments (with optional Gemma titles)."
    )
    parser.add_argument("--db_url", help="SQLAlchemy-style DB URL (else reads DB_URL env var or db_secret.db)")
    parser.add_argument("--consultation_id", type=int, default=320, help="Consultation ID to analyse")
    default_out = Path(__file__).parent / "topic_model_outputs"
    parser.add_argument("--out_dir", default=str(default_out), help="Where to store CSV files")
    parser.add_argument("--min_topic_size", type=int, default=10)
    parser.add_argument("--use_gemma", action="store_true", help="Generate topic titles with Gemma (GPU heavy)")
    parser.add_argument("--prob_threshold", type=float, default=0.8, help="Min. probability for representative comments")
    parser.add_argument("--max_comments_per_topic", type=int, default=10, help="Limit of comments kept per topic when building representative set")
    parser.add_argument("--exclude_topics", default="1", help="Comma-separated list of topic IDs to skip when building representative comments")
    GEMMA_PATH = "/home/glossapi/.cache/huggingface/hub/models--google--gemma-3-4b-it"
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. DB ------------------------------------------------------------
    engine = get_engine(args.db_url)
    comments_df = fetch_comments(engine, args.consultation_id)
    articles_df = fetch_articles(engine, args.consultation_id)

    if comments_df.empty:
        raise SystemExit("No comments fetched – check consultation ID or DB permissions.")

    # 2. Build stop-words ---------------------------------------------
    stemmer = snowballstemmer.stemmer("greek")
    nlp = load_spacy_el()

    word_freq: list[str] = []
    for art in articles_df["content"]:
        # quick same cleaning as notebook (only lower+accents strip) to count frequencies
        cleaned = strip_accents(art.lower())
        word_freq.extend(cleaned.split())
    common_words = [w for w, c in Counter(word_freq).items() if c > 10]
    stopwords = build_stopwords(common_words)

    # 3. Clean comments ------------------------------------------------
    comments_df.drop_duplicates(subset=["content"], inplace=True)
    comments_df["content_clean"] = comments_df["content"].apply(
        lambda txt: clean_comment(txt, nlp, stemmer, stopwords)
    )
    comments_df.drop_duplicates(subset=["content_clean"], inplace=True)

    # Save cleaned data
    cleaned_csv = out / "cleaned.csv"
    comments_df.to_csv(cleaned_csv, index=False)
    print(f"Saved cleaned comments to {cleaned_csv}")

    # 4. BERTopic ------------------------------------------------------
    topic_model, topics, _ = train_bertopic(
        comments_df["content_clean"], min_topic_size=args.min_topic_size
    )

    # Merge topic info with raw comment for inspection
    doc_info = topic_model.get_document_info(comments_df["content_clean"])
    doc_info["content_clean"] = doc_info["Document"]
    merged = pd.merge(comments_df, doc_info, on="content_clean")

    topics_csv = out / "topics.csv"
    merged.to_csv(topics_csv, index=False)
    print(f"First stage topics saved to {topics_csv}")

    # 4.b Build representative comments file --------------------------------
    try:
        exclude_set = {int(t.strip()) for t in args.exclude_topics.split(",") if t.strip()}
    except ValueError:
        exclude_set = set()

    filtered = merged[merged["Probability"] > args.prob_threshold]
    if exclude_set:
        filtered = filtered[~filtered["Topic"].isin(exclude_set)]

    rep_comments = (
        filtered.sort_values("Probability", ascending=False)
        .groupby("Topic")
        .head(args.max_comments_per_topic)
    )

    # drop verbose columns similar to notebook
    cols_to_drop = [
        "Document",
        "content_clean",
        "Name",
        "Representative_document",
        "Representative_Docs",
    ]
    rep_comments = rep_comments.drop(columns=[c for c in cols_to_drop if c in rep_comments.columns])

    rep_csv = out / "representative_comments.csv"
    rep_comments.to_csv(rep_csv, index=False)
    print(f"Representative comments saved to {rep_csv}")

    # 5. Optionally generate Gemma titles ---------------------------------
    if args.use_gemma:
        print("\nGenerating titles with Gemma … this may take a while.")
        titles_df = generate_titles_with_gemma(rep_comments, gemma_root=GEMMA_PATH)
        titles_csv = out / "topics_llm.csv"
        titles_df.to_csv(titles_csv, index=False)
        print(f"Gemma titles saved to {titles_csv}")


if __name__ == "__main__":
    # Deactivate TorchDynamo JIT as in the notebook
    os.environ["TORCHDYNAMO_DISABLE"] = "1"
    main() 