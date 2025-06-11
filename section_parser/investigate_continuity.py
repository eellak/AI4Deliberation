#!/usr/bin/env python3
"""Investigate continuity issues detected by section_parser.

Typical workflow
----------------
1. Generate the main report (already done):

   $ python section_parser.py  # or the batch script used earlier

2. List all consultations that have problems:

   $ python investigate_continuity.py list  --report continuity_report.json

   This prints a concise summary **and** writes a file ``continuity_issues.json``
   containing only the problematic consultations for easier inspection.

3. Inspect article titles of a specific consultation:

   $ python investigate_continuity.py titles 123  --db <path/to/db>

   Prints ``id: title`` lines so you can evaluate where the numbering problem
   originates (article title itself vs. parser code).
"""

import argparse
import json
import sqlite3
import sys
import os
import textwrap
from pathlib import Path

DEFAULT_DB = (
    "/mnt/data/AI4Deliberation/"
    "deliberation_data_gr_MIGRATED_FRESH_20250602170747.db"
)
DEFAULT_REPORT = "continuity_report.json"


def load_report(report_path: str):
    """Load continuity_report.json into Python list."""
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Report file '{report_path}' not found.", file=sys.stderr)
        sys.exit(1)


def list_issues(report):
    """Print summary of consultations flagged with issues and return list."""
    bad = [r for r in report if r.get("status") == "issues"]
    print(f"Found {len(bad)} consultations with continuity problems.\n")
    for r in bad:
        print(f"Consultation {r['consultation_id']}  –  {len(r['problems'])} problems, {r['articles']} articles")
        for p in r["problems"]:
            print("   •", textwrap.shorten(p, width=120))
        print()
    return bad


def save_issues(issues, out_path="continuity_issues.json"):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)
    print(f"Problematic consultations written to {out_path}")


def print_titles(db_path: str, consultation_id: int):
    if not Path(db_path).is_file():
        print(f"Database '{db_path}' not found.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT id, title FROM articles WHERE consultation_id = ? ORDER BY id",
            (consultation_id,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"No articles found for consultation {consultation_id}.")
        return

    for aid, title in rows:
        print(f"{aid}: {title}")


def main():
    parser = argparse.ArgumentParser(description="Investigate continuity issues in consultations")
    parser.add_argument(
        "--report",
        default=DEFAULT_REPORT,
        help="Path to continuity_report.json (default: continuity_report.json)",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help="Path to SQLite deliberation DB (default: common Greek DB)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List consultations that have issues")

    titles_parser = subparsers.add_parser("titles", help="Print article titles for a consultation")
    titles_parser.add_argument("consultation_id", type=int, help="Consultation ID")

    args = parser.parse_args()

    if args.command == "list":
        report = load_report(args.report)
        issues = list_issues(report)
        if issues:
            save_issues(issues)
    elif args.command == "titles":
        print_titles(args.db, args.consultation_id)


if __name__ == "__main__":
    main()
