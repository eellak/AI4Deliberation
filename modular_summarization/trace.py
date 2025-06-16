"""Reasoning trace utilities for capturing LLM prompts and outputs.

Provides structured logging of model interactions for debugging and analysis.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from .config import TRACE_OUTPUT_DIR, TRACE_FILENAME_TEMPLATE, RUN_TIMESTAMP

__all__ = ["ReasoningTracer", "TraceEntry"]


@dataclass
class TraceEntry:
    """Single reasoning trace entry."""
    article_id: int
    article_number: Optional[int]
    classification: str  # "modifies" or "new_provision"
    prompt: str
    raw_output: str
    parsed_output: Optional[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]] = None


class ReasoningTracer:
    """Handles reasoning trace logging with structured format."""
    
    def __init__(self, consultation_id: int, output_dir: Optional[str] = None):
        self.consultation_id = consultation_id
        self.output_dir = Path(output_dir or TRACE_OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create trace file
        filename = TRACE_FILENAME_TEMPLATE.format(
            consultation_id=consultation_id,
            timestamp=RUN_TIMESTAMP
        )
        self.trace_path = self.output_dir / filename
        
        # Setup dedicated logger
        self.logger = logging.getLogger(f"reasoning_trace_{consultation_id}")
        self.logger.setLevel(logging.INFO)
        
        # Remove existing handlers to avoid duplicates
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # File handler with custom format
        handler = logging.FileHandler(self.trace_path, encoding="utf-8")
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        
        # Ensure no truncation by setting max length to unlimited
        handler.setLevel(logging.INFO)
        
        self.logger.addHandler(handler)
        
        # Prevent propagation to root logger
        self.logger.propagate = False
        
        # Write header
        self._write_header()
    
    def _write_header(self):
        """Write trace file header."""
        self.logger.info("=" * 80)
        self.logger.info(f"REASONING TRACE - Consultation {self.consultation_id}")
        self.logger.info(f"Generated: {RUN_TIMESTAMP}")
        self.logger.info("=" * 80)
        self.logger.info("")
    
    def log_entry(self, entry: TraceEntry):
        """Log a single reasoning trace entry."""
        self.logger.info(f"ARTICLE ID: {entry.article_id}")
        if entry.article_number:
            self.logger.info(f"ARTICLE NUMBER: {entry.article_number}")
        self.logger.info(f"CLASSIFICATION: {entry.classification}")
        
        if entry.metadata:
            self.logger.info("METADATA:")
            for key, value in entry.metadata.items():
                self.logger.info(f"  {key}: {value}")
        
        self.logger.info("")
        self.logger.info("PROMPT:")
        self.logger.info("-" * 40)
        # Write prompt without any truncation
        for line in entry.prompt.splitlines():
            self.logger.info(line)
        self.logger.info("-" * 40)
        self.logger.info("")
        
        self.logger.info("RAW OUTPUT:")
        self.logger.info("-" * 40)
        # Write raw output without any truncation
        for line in entry.raw_output.splitlines():
            self.logger.info(line)
        self.logger.info("-" * 40)
        self.logger.info("")
        
        if entry.parsed_output:
            self.logger.info("PARSED OUTPUT:")
            self.logger.info("-" * 40)
            import json
            # Write parsed JSON without truncation
            json_str = json.dumps(entry.parsed_output, ensure_ascii=False, indent=2)
            for line in json_str.splitlines():
                self.logger.info(line)
            self.logger.info("-" * 40)
        else:
            self.logger.info("PARSED OUTPUT: [FAILED TO PARSE]")
        
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("")
    
    def close(self):
        """Close trace logger and handlers."""
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
    
    @property
    def trace_file_path(self) -> Path:
        """Return path to trace file."""
        return self.trace_path 