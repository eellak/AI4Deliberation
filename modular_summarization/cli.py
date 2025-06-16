"""CLI utilities for modular summarization package."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import os

from .workflow import run_workflow
from . import config as cfg


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Modular Summarization CLI")
    parser.add_argument("--consultation", "-c", type=int, default=1, help="Consultation ID")
    parser.add_argument("--db", type=str, default=str(cfg.DB_PATH), help="SQLite DB path")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline in dry-run mode (no LLM, hierarchy only)")
    parser.add_argument("--format", choices=["md", "txt"], default="md", help="Output format in dry-run: md or txt")
    parser.add_argument("--trace", action="store_true", help="Enable reasoning trace logging")
    parser.add_argument("--trace-dir", type=str, help="Directory for trace files (default: traces/)")
    parser.add_argument("--article-id", type=int, help="Process only specific article ID")
    args = parser.parse_args(argv)

    cfg.DB_PATH = args.db  # patch runtime config

    # Enable trace via environment variable if --trace flag is used
    if args.trace:
        os.environ["ENABLE_REASONING_TRACE"] = "1"
        cfg.ENABLE_REASONING_TRACE = True

    res = run_workflow(
        consultation_id=args.consultation,
        article_id=args.article_id,
        dry_run=args.dry_run,
        db_path=args.db,
        enable_trace=args.trace,
        trace_output_dir=args.trace_dir,
    )

    if args.dry_run:
        key = "dry_run_text" if args.format == "txt" else "dry_run_markdown"
        print(res[key])
    else:
        print(res)


if __name__ == "__main__":  # pragma: no cover
    main()
