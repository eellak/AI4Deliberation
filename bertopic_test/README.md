# BERTopic Test

Topic modeling implementation using BERTopic for analyzing Greek consultation comments.

## Overview
This module implements topic modeling on Greek consultation comments using BERTopic, with support for Greek text preprocessing and interactive visualization.

## Main Components

### Core Scripts
- `run_topic_modeling.py` - Main script for running topic modeling on consultation comments
- `embeddings_clustering.py` - Interactive Dash application for clustering and visualizing comment embeddings
- `vizualization_example_code.py` - Example code for topic visualization

### Key Features
- **Greek Text Support**: Specialized preprocessing for Greek language text
- **Database Integration**: Loads comments directly from SQLite database
- **Sentence Embeddings**: Generates embeddings for semantic analysis
- **Interactive Visualization**: Dash-based web interface for exploring topics
- **CSV Export**: Outputs topic analysis results to CSV files

## Output Files
- Topic analysis results are saved as CSV files
- Embedding data for further analysis
- Visualization exports

## Requirements
- BERTopic
- Sentence Transformers
- Dash (for interactive visualization)
- SQLite3
- pandas, numpy

## Usage
```bash
python run_topic_modeling.py
```

For interactive visualization:
```bash
python embeddings_clustering.py
```