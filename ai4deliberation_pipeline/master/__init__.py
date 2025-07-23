#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Master Pipeline Module

Core orchestration and integration for the AI4Deliberation pipeline.
"""

"""ai4deliberation_pipeline.master package init.

Currently no public symbols exported; import the orchestrator module for side-effects only.
"""

from importlib import import_module as _imp

# Ensure orchestrator module is importable without circular dependency issues
_imp('ai4deliberation_pipeline.master.pipeline_orchestrator')

__all__: list[str] = [] 