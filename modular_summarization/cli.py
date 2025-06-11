"""CLI utilities for modular summarization package."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .workflow import run_workflow
from . import config as cfg


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Modular Summarization CLI")
    parser.add_argument("--consultation", "-c", type=int, default=1, help="Consultation ID")
    parser.add_argument("--db", type=str, default=str(cfg.DB_PATH), help="SQLite DB path")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline in dry-run mode (no LLM)")
    parser.add_argument("--format", choices=["md", "txt"], default="md", help="Output format in dry-run: md or txt")
    args = parser.parse_args(argv)

    cfg.DB_PATH = args.db  # patch runtime config

    res = run_workflow(args.consultation, dry_run=args.dry_run, db_path=args.db)

    if args.dry_run:
        key = "dry_run_text" if args.format == "txt" else "dry_run_markdown"
        print(res[key])
    else:
        print(res)


if __name__ == "__main__":  # pragma: no cover
    main()
