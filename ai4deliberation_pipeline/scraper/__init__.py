#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper Module

Web scraping functionality for Greek online consultations from opengov.gr
"""

from .scrape_single_consultation import scrape_and_store
from .db_models import init_db
from .metadata_scraper import scrape_consultation_metadata
from .content_scraper import scrape_consultation_content

__all__ = [
    'scrape_and_store',
    'init_db', 
    'scrape_consultation_metadata',
    'scrape_consultation_content'
] 