#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Master Pipeline Module

Core orchestration and integration for the AI4Deliberation pipeline.
"""

from .pipeline_orchestrator import run_pipeline, process_consultation

__all__ = ['run_pipeline', 'process_consultation'] 