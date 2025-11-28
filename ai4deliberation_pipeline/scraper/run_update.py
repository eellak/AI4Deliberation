#!/usr/bin/env python3
"""
Convenience entry point to run the full scraper without worrying about PYTHONPATH.
Usage:
    python -m ai4deliberation_pipeline.scraper.run_update [args...]
or:
    python ai4deliberation_pipeline/scraper/run_update.py [args...]
"""
import os
import sys

# Allow running as a script without package context
if __package__ is None:
    # Add project root to sys.path so relative imports resolve
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, os.pardir, os.pardir))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    __package__ = "ai4deliberation_pipeline.scraper"

from .scrape_all_consultations import main


if __name__ == "__main__":
    main()
