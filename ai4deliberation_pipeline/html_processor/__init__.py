#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTML Processor Module

HTML to markdown conversion and content extraction functionality.
"""

from .html_processor import HTMLProcessor, process_articles_batch, get_unprocessed_articles

__all__ = [
    'HTMLProcessor',
    'process_articles_batch',
    'get_unprocessed_articles'
] 