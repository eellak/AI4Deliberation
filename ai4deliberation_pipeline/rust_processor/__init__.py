#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rust Processor Module

Rust-based text cleaning and quality assessment functionality.
"""

from .rust_processor import RustProcessor, process_documents_with_rust

__all__ = [
    'RustProcessor',
    'process_documents_with_rust'
] 