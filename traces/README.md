# Traces

Directory for storing detailed processing trace logs.

## Overview
This directory contains reasoning traces and detailed logs from consultation processing runs, useful for debugging and analysis.

## Log Files
Log files follow the naming pattern:
- `reasoning_trace_c{consultation_id}_{timestamp}.log`

Example: `reasoning_trace_c133_20250702_080059.log`

## Contents
Trace logs typically include:
- Step-by-step processing information
- LLM prompts and responses
- Intermediate results
- Error messages and stack traces
- Performance metrics
- Decision points and reasoning

## Usage
These logs are invaluable for:
- Debugging failed processing runs
- Understanding model behavior
- Performance optimization
- Quality assurance
- Reproducibility of results

## Log Levels
Logs may contain multiple levels of detail:
- INFO: General processing steps
- DEBUG: Detailed internal operations
- WARNING: Non-critical issues
- ERROR: Processing failures

## Retention
Logs are retained for historical analysis but may be archived or compressed periodically to manage disk space.