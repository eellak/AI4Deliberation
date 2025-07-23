# Master

Main orchestration layer for the AI4Deliberation pipeline.

## Overview
This module contains the master pipeline orchestrator that coordinates all components of the AI4Deliberation system, implementing an efficient data flow from web scraping through text extraction, cleaning, and storage.

## Core Component

### pipeline_orchestrator.py
The main orchestrator that:
- Manages the complete pipeline workflow
- Coordinates between different processing modules
- Handles consultation discovery and updates
- Implements efficient data flow: scrape → extract → clean → store

## Pipeline Flow

1. **Discovery Phase**
   - Identifies new consultations on opengov.gr
   - Checks for updates to existing consultations

2. **Scraping Phase**
   - Downloads consultation metadata
   - Retrieves consultation content and documents

3. **Extraction Phase**
   - Processes PDF documents
   - Extracts text content
   - Handles document structure

4. **Cleaning Phase**
   - Applies text cleaning algorithms
   - Calculates quality metrics
   - Removes noise and artifacts

5. **Storage Phase**
   - Updates database with processed content
   - Maintains data integrity
   - Tracks processing status

## Key Features
- **Modular Design**: Each phase can be run independently
- **Error Recovery**: Robust error handling and retry mechanisms
- **Progress Tracking**: Detailed logging and status updates
- **Efficiency**: Avoids reprocessing unchanged content
- **Scalability**: Designed for batch processing

## Usage
```python
from master.pipeline_orchestrator import PipelineOrchestrator

orchestrator = PipelineOrchestrator(config)
orchestrator.process_consultation(consultation_url)
# Or batch process
orchestrator.process_all_consultations()
```

## Configuration
Configured through the pipeline configuration system, controlling:
- Processing parameters
- Retry policies
- Logging levels
- Component selection