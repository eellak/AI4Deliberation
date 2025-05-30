#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI4Deliberation Pipeline
========================

Modular pipeline for processing Greek online consultations from opengov.gr

This package provides:
- Web scraping of consultation data
- HTML content processing 
- PDF document processing
- Rust-based text cleaning
- Integrated database operations

Modules:
- scraper: Web scraping functionality
- html_processor: HTML to markdown conversion
- pdf_processor: PDF download and extraction  
- rust_processor: Text cleaning and quality assessment
- master: Core integration and orchestration
- config: Configuration management
- utils: Shared utilities

Usage:
    from ai4deliberation_pipeline.master import run_pipeline
    
    # Process a single consultation
    result = run_pipeline(mode='single', url='...')
    
    # Update with new consultations
    result = run_pipeline(mode='update')
"""

__version__ = "1.0.0"
__author__ = "AI4Deliberation Team"

# Core API imports
from .master.pipeline_orchestrator import run_pipeline, process_consultation
from .config.config_manager import load_config, validate_config
from .utils.database import get_database_stats

__all__ = [
    'run_pipeline',
    'process_consultation', 
    'load_config',
    'validate_config',
    'get_database_stats'
] 