#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib.util
import sys
import types
import uuid
from pathlib import Path


SCRAPER_ROOT = Path(__file__).resolve().parents[1] / "ai4deliberation_pipeline" / "scraper"


def load_scraper_modules():
    """Load scraper modules without importing the package-wide top-level API."""
    package_name = f"ai4d_scraper_test_{uuid.uuid4().hex}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(SCRAPER_ROOT)]
    sys.modules[package_name] = package

    modules = {}
    module_names = [
        "utils",
        "consultation_matching",
        "db_models",
        "metadata_scraper",
        "content_scraper",
        "scrape_single_consultation",
        "scrape_all_consultations",
    ]

    for module_name in module_names:
        module_path = SCRAPER_ROOT / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(f"{package_name}.{module_name}", module_path)
        module = importlib.util.module_from_spec(spec)
        module.__package__ = package_name
        sys.modules[f"{package_name}.{module_name}"] = module
        spec.loader.exec_module(module)
        modules[module_name] = module

    return modules
