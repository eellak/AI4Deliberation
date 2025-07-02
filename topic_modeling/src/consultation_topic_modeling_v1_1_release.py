# ---------------------------------------------------------------------------
# consultation_topic_modeling_v1_1_release.py – Τελική «v1 . 1 release» του
#   υποσυστήματος θεματικής ομαδοποίησης σχολίων δημόσιας διαβούλευσης.
# ---------------------------------------------------------------------------
# Περιγραφή
#   • Αυτόματη προσαρμογή `min_topic_size` ≈ 1 % των καθαρών σχολίων
#     (όρια: 3–10) όταν δεν ορίζεται ρητά.
#   • Ασφαλής εναλλακτική σε CPU όταν η Gemma εξαντλεί VRAM (CUDA-OOM).
#   • Νέο prompt τύπου JSON (Title, Explanation, Topic)· τίτλος 8-20 λέξεις.
#   • Προαιρετικός ορθογραφικός έλεγχος με LanguageTool (εάν υπάρχει Java).
#   • Συγχώνευση θεμάτων βάσει κοσίνου ≥ 0.90 (Sentence-BERT) για αποφυγή
#     κατακερματισμού.
#   • **Batch** εκτέλεση διαθέσιμη μέσω `run_consultation_batch.py`.
#   • Όλα τα artefacts αποθηκεύονται σε `outputs/v1/<consultation_id>/` με
#     σταθερή ιεραρχία φακέλων (raw / clustering / reps / titles / evaluation).
#
# Χρήση (βασικό παράδειγμα):
#   python consultation_topic_modeling_v1_1_release.py \
#         --consultation_id 320 \
#         --db_url postgresql://user:pass@host/dbname \
#         --gemma_path /abs/path/to/gemma-3-4b-it \
#         --random_state 42 
#
# Σημαντικές επιλογές CLI:
#   --min_topic_size N          Χειροκίνητη ρύθμιση μεγέθους cluster.
#   --embedding_backend sbert|gte_large
#   --prob_threshold 0.85       Κατώφλι για representative comments.
#   --merge_threshold 0.90      Κοσίνη για συγχώνευση θεμάτων.
#   --enable_spellcheck         Ενεργοποίηση LanguageTool.
#   --export_reps_only          Τερματισμός μετά το CSV με σχόλια.
# ---------------------------------------------------------------------------

#python topic_modeling/consultation_topic_modeling.py --use_gemma

import argparse
import os
from pathlib import Path
from collections import Counter
import unicodedata as ud
import re
import json

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

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

# Optional grammar checker
try:
    import language_tool_python  # type: ignore
except ImportError:
    language_tool_python = None  # type: ignore

# ---------------------------------------------------------------------------
# Output folders
# ---------------------------------------------------------------------------
OUTPUT_ROOT = (Path(__file__).resolve().parent.parent / "outputs").resolve()
VERSION_TAG = "v1"

# ---------------------------------------------------------------------------
# Domain-specific stop-words & boiler-plate phrase regex --------------------
# ---------------------------------------------------------------------------
# These must be defined at module level so that downstream functions (e.g.
# build_stopwords) can access them safely.
DOMAIN_STOPWORDS: list[str] = [
    "άρθρο", "άρθρου", "άρθρα", "παράγραφος", "παράγραφοι", "παρ",
    "εδάφιο", "εδάφια", "τροποποίηση", "τροποποιήσεις", "τροποποιούμενη",
    "σχόλια", "σχόλιο", "διαβούλευση", "θεματική", "ενότητα", "κείμενο",
]

# κοινές γενικές φράσεις που θέλουμε να αφαιρούμε από τα σχόλια πριν
# τα στείλουμε στο LLM για τίτλο – οδηγούν σε γενικούς τίτλους.
STOP_PHRASES_REGEX = re.compile(
    r"\b(τα\s+σχόλια\s+επικεντρώνονται|τα\s+σχόλια\s+εστιάζουν|"
    r"τα\s+σχόλια\s+αναφέρονται|υπάρχει\s+ανάγκη|ζητείται)\b",
    flags=re.IGNORECASE,
)

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
    """Combine corpus-derived frequent words with project-wide Greek stop-word list."""
    from pathlib import Path

    stop_file = Path(__file__).resolve().parent.parent / "stopwords_el.txt"
    manual: list[str] = []
    if stop_file.exists():
        manual = [w.strip() for w in stop_file.read_text(encoding="utf-8").splitlines() if w.strip()]

    # merge corpus, project, and domain specific lists
    return list(set(manual + common_words + DOMAIN_STOPWORDS))


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
    """Train BERTopic while safeguarding UMAP against tiny corpora.

    The default internal UMAP initialisation uses ``n_neighbors=15``.  When the
    corpus has <15 documents, UMAP's spectral initialisation crashes with
    ``TypeError: Cannot use scipy.linalg.eigh for sparse A with k >= N``.

    We therefore create a custom UMAP instance whose ``n_neighbors`` never
    exceeds ``len(corpus) - 1`` (and is at least 2).  This simple heuristic
    avoids the small-corpus failure without otherwise affecting behaviour for
    regular-sized consultations.
    """

    import umap  # local import to avoid mandatory dependency for callers

    n_docs = len(df_clean)
    # Safeguard: neighbours must be < n_docs
    n_neighbors = max(2, min(15, n_docs - 1))

    umap_model = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=0.1,
        random_state=42,
    )

    # ------------------------------------------------------------------
    # Safe HDBSCAN configuration
    # ------------------------------------------------------------------
    import hdbscan  # type: ignore

    # HDBSCAN fails when ``min_samples`` (k in KD-Tree) exceeds the corpus
    # size.  Keep it bounded by *n_docs*.
    cluster_size = min(min_topic_size, n_docs) if n_docs >= 2 else 1
    min_samples_safe = max(1, min(cluster_size, n_docs))

    hdbscan_model = hdbscan.HDBSCAN(
        min_cluster_size=cluster_size,
        min_samples=min_samples_safe,
        prediction_data=True,
        metric="euclidean",
    )

    representation_model = [
        KeyBERTInspired(top_n_words=15),
        MaximalMarginalRelevance(diversity=0.3, top_n_words=15),
    ]
    ctfidf_model = ClassTfidfTransformer(reduce_frequent_words=True)

    topic_model = BERTopic(
        representation_model=representation_model,
        language="multilingual",
        min_topic_size=cluster_size,
        top_n_words=15,
        ctfidf_model=ctfidf_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
    )

    topics, probs = topic_model.fit_transform(df_clean)
    return topic_model, topics, probs


def generate_titles_with_gemma(rep_df: pd.DataFrame, gemma_root: str, device: str = "auto", enable_spellcheck: bool = True) -> pd.DataFrame:
    """Generate a concise title + short explanation for each topic using Gemma and the exact prompt from the notebook."""

    # Torch is only required for the GPU/CPU fallback logic below.  Import it
    # lazily here so the rest of the script remains usable even if torch is
    # not installed in environments where only the clustering part is needed.
    try:
        import torch  # type: ignore
    except ModuleNotFoundError:
        torch = None  # type: ignore

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

    # ---------------------------------------------------------------------------
    # LanguageTool init
    # ---------------------------------------------------------------------------
    LT_TOOL = None
    if enable_spellcheck and 'language_tool_python' in globals() and language_tool_python is not None:
        from language_tool_python import LanguageTool

        # Some wheel versions lack JavaNotFoundError; provide stub if needed.
        try:
            from language_tool_python import JavaNotFoundError  # type: ignore
        except ImportError:  # pragma: no cover
            class JavaNotFoundError(Exception):
                """Stub used when language_tool_python has no JavaNotFoundError"""
                pass

        # Try to import the public-API helper class; name differs across releases.
        try:
            from language_tool_python import LanguageToolPublicAPI as LanguageToolPublic  # type: ignore
        except ImportError:  # pragma: no cover – very old versions
            LanguageToolPublic = None

        try:
            LT_TOOL = LanguageTool("el")  # prefer offline local server
        except JavaNotFoundError:
            if LanguageToolPublic is not None:
                print("[info] Java runtime not found – falling back to public LanguageTool API.")
                LT_TOOL = LanguageToolPublic("el")
            else:
                print("[warn] Java runtime not found and LanguageToolPublicAPI missing – spell-check disabled.")
                LT_TOOL = None

    print(f"[info] LanguageTool spell-check: {'ON' if LT_TOOL else 'OFF'}")

    def _spell_correct(txt: str) -> str:
        if LT_TOOL is None:
            return txt
        try:
            matches = LT_TOOL.check(txt)
            return language_tool_python.utils.correct(txt, matches)  # type: ignore
        except Exception:
            return txt

    # ---------------------------------------------------------------------------
    # Simple validators ---------------------------------------------------------
    # ---------------------------------------------------------------------------
    def _sentence_count(text: str) -> int:
        """Rudimentary sentence count based on punctuation."""
        return len(re.findall(r"[.!?]\s", text + " ")) or (1 if text.strip() else 0)

    def _is_valid(title: str, explanation: str) -> bool:
        words = len(title.split())
        return 6 <= words <= 20 and 1 <= _sentence_count(explanation) <= 3

    # ---------------------------------------------------------------------------
    # Output folders defined earlier (OUTPUT_ROOT, VERSION_TAG)
    # ---------------------------------------------------------------------------

    # ---------------------------------------------------------------------------
    # JSON prompt (new organisation)
    # ---------------------------------------------------------------------------
    # JSON_PROMPT = (
    #     "Είσαι αξιολογητής θεματικής συνάφειας για διαβουλεύσεις. Για μία διαβούλευση σου δίνονται τα εξής keywords που τη χαρακτηρίζουν: {keywords}\n"
    #     "και ένα αντιπροσωπευτικό δείγμα σχολίων πολιτών που έχουν ομαδοποιηθεί σε μια ενιαία θεματική (topic).\n"
    #     "σχόλια:\n{comments}\n"
    #     "Για κάθε θεματική (topic) εντόπισε το βασικό θέμα ή θεματική ενότητα στην οποία εντάσσονται τα σχόλια.\n"
    #     "Επέστρεψε σαν έξοδο σε μορφή JSON με ΑΚΡΙΒΩΣ αυτά τα πεδία και με αυτή τη σειρά: Title, Explanation, Topic.\n"
    #     "• Title: σύντομος (έως 15 λέξεις) περιγραφικός τίτλος στα ελληνικά.\n"
    #     "• Explanation: 1–3 προτάσεις στα ελληνικά που δικαιολογούν τον τίτλο.\n"
    #     "• Topic: ο αριθμός του topic (όπως σου δίνεται).\n"
    #     "Παράδειγμα (δομή & σειρά πεδίων):\n"
    #     "{{\"Title\": \"Ενίσχυση εθελοντών πυροσβεστών\", \"Explanation\": \"Τα σχόλια επισημαίνουν ανάγκη για εκπαίδευση και θεσμικό πλαίσιο\", \"Topic\": 0}}\n"
    #     "Επέστρεψε αποκλειστικά ένα αντικείμενο JSON χωρίς επιπλέον κείμενο, markdown ή ```json``` fences."
    # )

    JSON_PROMPT = (
        """You are an expert AI analyst specializing in summarizing public consultation feedback. Your task is to analyze a cluster of citizen comments for a given topic and generate a structured summary.
            The overall consultation is about these keywords: {keywords}
            You will be given a topic ID and a set of comments belonging to that topic.
            **Input:**
            - Topic ID: {topic_id}
            - Citizen Comments for this Topic:
            {comments}

            **Instructions:**
            1.  Read all the comments to understand the main, recurring theme or issue.
            2.  Generate a concise title and a short explanation for this theme **in Greek**.
            3.  Your entire response MUST be a single, raw JSON object and nothing else.

            **Output Format Rules:**
            - The JSON object must contain exactly these three keys, in this exact order: "title", "explanation", "topic".
            - The value for "title" must be a short, descriptive title in Greek (maximum 20 words but not less than 8 words).
            - The value for "explanation" must be a justification of the title in Greek (1-3 sentences).
            - The value for "topic" must be the integer Topic ID provided in the input.

            **Example of the required output structure and language:**
            {{
            "title": "Ενίσχυση εθελοντών πυροσβεστών",
            "explanation": "Τα σχόλια επισημαίνουν την ανάγκη για καλύτερη εκπαίδευση και σαφέστερο θεσμικό πλαίσιο για τους εθελοντές. Πολλοί ζητούν παροχή σύγχρονου εξοπλισμού.",
            "topic": 0
            }}

            **CRITICAL:** Do NOT write any text, introduction, or explanation before or after the JSON object. Do not use Markdown code fences like ```json. Your output must start with `{{` and end with `}}` and it should be exclusively in Greek.
            """

    )


    outputs = []

    for topic_id, group in rep_df.groupby("Topic"):
        if topic_id == -1:
            continue

        comments_block = "\n".join([
            f"{i}. \"{STOP_PHRASES_REGEX.sub('', c).strip()}\"" for i, c in enumerate(group["content"].tolist()[:10])
        ])
        keywords = group["Representation"].iloc[0]

        user_prompt = JSON_PROMPT.format(keywords=keywords,
                                         comments=comments_block,
                                         topic_id=topic_id)

        # Gemma3Processor expects the prompt under the 'text' keyword.
        inputs = tokenizer(text=user_prompt, return_tensors="pt").to(model.device)
        input_len = inputs["input_ids"].shape[1]

        def _run_generation(do_sample: bool) -> str:
            """Generate text; if GPU OOM occurs, retry once on CPU."""
            try:
                out_ids = model.generate(
                    **inputs,
                    max_new_tokens=200,
                    do_sample=do_sample,
                    temperature=0.7 if do_sample else 1.0,
                )
                return tokenizer.decode(out_ids[0][input_len:], skip_special_tokens=True)
            except RuntimeError as e:
                if "out of memory" in str(e).lower() and torch.cuda.is_available():
                    print("[warn] CUDA OOM – retrying on CPU …")
                    torch.cuda.empty_cache()
                    model.to("cpu")
                    cpu_inputs = tokenizer(text=user_prompt, return_tensors="pt")
                    cpu_input_len = cpu_inputs["input_ids"].shape[1]
                    out_ids = model.generate(
                        **cpu_inputs,
                        max_new_tokens=200,
                        do_sample=do_sample,
                        temperature=0.7 if do_sample else 1.0,
                    )
                    return tokenizer.decode(out_ids[0][cpu_input_len:], skip_special_tokens=True)
                raise

        # First attempt: deterministic generation
        gen_text = _run_generation(do_sample=False).strip()

        # If Gemma unexpectedly returns empty output, retry with sampling
        if not gen_text:
            gen_text = _run_generation(do_sample=True).strip()

        # As a last fallback derive title from keywords
        if not gen_text:
            if isinstance(keywords, list):
                primary_kw = keywords[0] if keywords else f"Θέμα {topic_id}"
            else:
                primary_kw = str(keywords).split(",")[0].strip() if keywords else f"Θέμα {topic_id}"
            data = {"title": primary_kw.strip(), "explanation": ""}
            outputs.append({"Title": _spell_correct(data["title"]), "Explanation": "", "Topic": topic_id})
            continue

        # ------------------------------
        # parse JSON output
        # ------------------------------
        # Strip common markdown fences even if only opening or closing present
        if gen_text.startswith("```"):
            # remove first line starting with ```json or ```
            gen_text = re.sub(r"^```(?:json)?", "", gen_text, count=1, flags=re.IGNORECASE).lstrip()
        if gen_text.endswith("```"):
            gen_text = gen_text.rsplit("```", 1)[0].rstrip()
        # If both fences exist on same string capture inner block (safer)
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", gen_text, flags=re.DOTALL)
        if m:
            gen_text = m.group(1)

        try:
            data_parsed = json.loads(gen_text)
            # If model returned a list, keep the first element
            if isinstance(data_parsed, list) and data_parsed:
                data_parsed = data_parsed[0]
        except json.JSONDecodeError:
            data_parsed = None

        if not isinstance(data_parsed, dict):
            # Fallback regex extraction (case-insensitive, accept both Title/title etc.)
            title_match = re.search(r"[\"'](?i:title)[\"']\s*:\s*[\"'](.*?)[\"']", gen_text, flags=re.DOTALL)
            expl_match = re.search(r"[\"'](?i:explanation)[\"']\s*:\s*[\"'](.*?)[\"']", gen_text, flags=re.DOTALL)
            if not expl_match:
                # handle missing closing quote – capture until newline/end
                expl_match = re.search(r"[\"'](?i:explanation)[\"']\s*:\s*[\"'](.*)$", gen_text, flags=re.DOTALL)
            data_parsed = {
                "Title": title_match.group(1) if title_match else gen_text[:120],
                "Explanation": expl_match.group(1) if expl_match else "",
            }
        # Normalise keys to Title/Explanation (capitalised)
        data = {
            "Title": data_parsed.get("Title") or data_parsed.get("title", ""),
            "Explanation": data_parsed.get("Explanation") or data_parsed.get("explanation", ""),
            "Topic": data_parsed.get("Topic") or data_parsed.get("topic", topic_id),
        }

        def _clean_title(text: str) -> str:
            """Remove γενικά προθέματα τύπου 'Αναφορά/Αναφορές σε/στην/για', 'Αναφορικά με'."""
            prefix_re = re.compile(
                r"^(?:Αναφορ(?:ές|ά|α)|Αναφορικά)\s+(?:σε|στην|στη|στις|για)\s+",
                flags=re.IGNORECASE,
            )
            cleaned = prefix_re.sub("", text).strip()
            if cleaned:
                cleaned = cleaned[0].upper() + cleaned[1:]
            # Remove dangling Greek articles that may have been appended for padding
            trailing_articles = {
                "ο", "οι", "η", "το", "τα", "του", "των", "τον", "την", "τους", "τις",
                "στο", "στον", "στα", "στους", "στη", "στην", "στις"
            }
            tokens = cleaned.split()
            if tokens and tokens[-1].lower() in trailing_articles:
                cleaned = " ".join(tokens[:-1])
            return cleaned

        def _clean_expl(text: str) -> str:
            """Strip generic lead-in phrases from explanations."""
            expl_re = re.compile(
                r"^Τα\s+σχόλια\s+(?:επικεντρώνονται|εκφράζουν|αναφέρονται|εστιάζουν|εστιάζονται|αναδεικνύουν)\s+",
                flags=re.IGNORECASE,
            )
            cleaned = expl_re.sub("", text).strip()
            if cleaned:
                cleaned = cleaned[0].upper() + cleaned[1:]
            return cleaned

        title_out = _spell_correct(data.get("Title", "").strip())
        title_out = _clean_title(title_out)
        expl_out = _spell_correct(data.get("Explanation", "").strip())
        expl_out = _clean_expl(expl_out)

        # ------------------------------------------------------------
        # Validate & retry once with sampling if needed -------------
        # ------------------------------------------------------------
        if not _is_valid(title_out, expl_out):
            # attempt a second generation with sampling if first was deterministic
            gen_text_retry = _run_generation(do_sample=True).strip()
            if gen_text_retry and gen_text_retry != gen_text:
                gen_text = gen_text_retry
                # RE-parse JSON as earlier (reuse parsing logic)
                if gen_text.startswith("```"):
                    gen_text = re.sub(r"^```(?:json)?", "", gen_text, count=1, flags=re.IGNORECASE).lstrip()
                if gen_text.endswith("```"):
                    gen_text = gen_text.rsplit("```", 1)[0].rstrip()
                m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", gen_text, flags=re.DOTALL)
                if m:
                    gen_text = m.group(1)
                try:
                    data_parsed = json.loads(gen_text)
                    if isinstance(data_parsed, list) and data_parsed:
                        data_parsed = data_parsed[0]
                except json.JSONDecodeError:
                    data_parsed = None
                if isinstance(data_parsed, dict):
                    title_out = _spell_correct(data_parsed.get("Title") or data_parsed.get("title", "").strip())
                    expl_out = _spell_correct(data_parsed.get("Explanation") or data_parsed.get("explanation", "").strip())
        # *Still* invalid? Final heuristic fixes
        if not _is_valid(title_out, expl_out):
            words_needed = 8 - len(title_out.split())
            if words_needed > 0:
                extra_words = " ".join(expl_out.split()[:words_needed])
                title_out = (title_out + " " + extra_words).strip()
            title_out = " ".join(title_out.split()[:20])  # cap 20 words
            # Trim explanation to 3 sentences max
            sentences = re.split(r"(?<=[.!?])\s+", expl_out)
            expl_out = " ".join(sentences[:3]).strip()

        # Final pass: ensure no dangling articles after potential padding
        title_out = _clean_title(title_out)

        outputs.append({"Title": title_out, "Explanation": expl_out, "Topic": data.get("Topic", topic_id)})

    return pd.DataFrame(outputs)


# ---------------------------------------------------------------------------
# TOPIC POST-PROCESSING -------------------------------------------------------
# ---------------------------------------------------------------------------

def merge_similar_topics(
    topic_model: BERTopic,
    docs: list[str],
    similarity_threshold: float = 0.9,
) -> BERTopic:
    """Merge topics that are semantically similar above *similarity_threshold*.

    Uses sentence-BERT embeddings of the top words per topic and the native
    `topic_model.merge_topics` API.
    """

    try:
        st_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    except Exception as exc:  # pragma: no cover
        print(f"[warn] Could not load SentenceTransformer ({exc}) – skipping merge step.")
        return topic_model

    # Build list of topic IDs (exclude outlier -1)
    topic_ids = [t for t in topic_model.get_topics() if t != -1]
    if len(topic_ids) < 2:
        return topic_model  # nothing to merge

    rep_texts: list[str] = []
    for t in topic_ids:
        words = [w for w, _ in topic_model.get_topic(t)[:10]]
        rep_texts.append(" ".join(words))

    embeddings = st_model.encode(rep_texts, normalize_embeddings=True)
    sim_mat = cosine_similarity(embeddings)

    # Union–find clustering based on similarity threshold
    parent = {i: i for i in range(len(topic_ids))}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pj] = pi

    for i in range(len(topic_ids)):
        for j in range(i + 1, len(topic_ids)):
            if sim_mat[i, j] >= similarity_threshold:
                union(i, j)

    # Build clusters
    clusters: dict[int, list[int]] = {}
    for idx, t in enumerate(topic_ids):
        root = find(idx)
        clusters.setdefault(root, []).append(t)

    # Merge clusters with >1 topics
    for cl in clusters.values():
        # Ensure we only pass topic IDs that still exist after previous merges
        valid_ids = set(topic_model.get_topics().keys())
        cl = [t for t in cl if t in valid_ids]
        if len(cl) <= 1:
            continue
        # BERTopic API: merge_topics may modify the model in-place and return
        # (topics, probs) *or* a new model depending on library version.
        merge_ret = topic_model.merge_topics(docs, topics_to_merge=cl)
        # Depending on BERTopic version, merge_topics returns either:
        #   • a *new* BERTopic instance, or
        #   • a tuple (model, topics, probabilities)
        if isinstance(merge_ret, BERTopic):
            topic_model = merge_ret
        elif isinstance(merge_ret, tuple) and isinstance(merge_ret[0], BERTopic):
            topic_model = merge_ret[0]
        else:
            # Unexpected return type; skip merge to avoid corrupting state
            continue

    return topic_model


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run BERTopic on Greek consultation comments (with optional Gemma titles)."
    )
    parser.add_argument("--db_url", help="SQLAlchemy-style DB URL (else reads DB_URL env var or db_secret.db)")
    parser.add_argument("--consultation_id", type=int, default=320, help="Consultation ID to analyse")
    parser.add_argument("--output_root", type=Path, default=OUTPUT_ROOT, help="Root folder for outputs (default topic_modeling/outputs)")
    parser.add_argument(
        "--min_topic_size",
        type=int,
        default=0,  # 0 means automatic sizing based on corpus size
        help="Minimum docs per topic (0 = auto; set explicit value to override)",
    )
    parser.add_argument("--prob_threshold", type=float, default=0.8, help="Min. probability for representative comments")
    parser.add_argument("--max_comments_per_topic", type=int, default=10, help="Limit of comments kept per topic when building representative set")
    parser.add_argument("--exclude_topics", default="1", help="Comma-separated list of topic IDs to skip when building representative comments")
    parser.add_argument("--no_spellcheck", action="store_true", help="Disable LanguageTool spell-checking for titles/explanations")
    GEMMA_PATH = "/home/glossapi/.cache/huggingface/hub/models--google--gemma-3-4b-it"
    args = parser.parse_args()

    # ------------------------------------------------------------
    # Structured output folders
    # ------------------------------------------------------------
    base_out: Path = args.output_root / VERSION_TAG / str(args.consultation_id)
    raw_dir = base_out / "raw"
    cluster_dir = base_out / "clustering"
    reps_dir = base_out / "reps"
    titles_dir = base_out / "titles"
    evaluation_dir = base_out / "evaluation"

    for d in (raw_dir, cluster_dir, reps_dir, titles_dir, evaluation_dir):
        d.mkdir(parents=True, exist_ok=True)

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
    cleaned_csv = raw_dir / "cleaned.csv"
    comments_df.to_csv(cleaned_csv, index=False)
    print(f"Saved cleaned comments to {cleaned_csv}")

    # 4. BERTopic ------------------------------------------------------
    # ------------------------------------------------------------
    # Determine min_topic_size if auto (0)
    # ------------------------------------------------------------
    if args.min_topic_size <= 0:
        n_docs = len(comments_df)
        min_topic_auto = max(3, round(0.01 * n_docs))
        min_topic_auto = min_topic_auto if n_docs < 600 else 10
    else:
        min_topic_auto = args.min_topic_size

    topic_model, topics, _ = train_bertopic(
        comments_df["content_clean"], min_topic_size=min_topic_auto
    )

    # ------------------------------------------------------------
    # 3b. Merge semantically similar topics ----------------------
    # ------------------------------------------------------------
    original_num_topics = len([t for t in topic_model.get_topics() if t != -1])
    topic_model = merge_similar_topics(topic_model, comments_df["content_clean"].tolist())
    merged_num_topics = len([t for t in topic_model.get_topics() if t != -1])
    if merged_num_topics < original_num_topics:
        print(f"[info] Merged topics: {original_num_topics} → {merged_num_topics}")

    # Recompute document info after merging
    doc_info = topic_model.get_document_info(comments_df["content_clean"])  # type: ignore
    doc_info["content_clean"] = doc_info["Document"]
    merged = pd.merge(comments_df, doc_info, on="content_clean")

    topics_csv = cluster_dir / "topics.csv"
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

    rep_csv = reps_dir / "representative_comments.csv"
    rep_comments.to_csv(rep_csv, index=False)
    print(f"Representative comments saved to {rep_csv}")

    # 5. Generate Gemma titles (mandatory) ---------------------------------
    print("\nGenerating titles with Gemma … this may take a while.")
    titles_df = generate_titles_with_gemma(rep_comments, gemma_root=GEMMA_PATH, enable_spellcheck=not args.no_spellcheck)
    titles_jsonl = titles_dir / "topics_llm_v1.jsonl"
    with titles_jsonl.open("w", encoding="utf-8") as fh:
        for _, row in titles_df.iterrows():
            fh.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
    print(f"Gemma titles saved to {titles_jsonl}")

    print(f"[success] Outputs saved under {base_out}")


if __name__ == "__main__":
    # Deactivate TorchDynamo JIT as in the notebook
    os.environ["TORCHDYNAMO_DISABLE"] = "1"
    main() 