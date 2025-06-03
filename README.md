# AI4Deliberation Project

This project encompasses a suite of tools and pipelines designed for processing, analyzing, and summarizing data related to public deliberations, primarily focusing on content from opengov.gr.

## Key Components

### 1. AI4Deliberation Pipeline (`ai4deliberation_pipeline/`)
A comprehensive pipeline for:
- Scraping consultation data (metadata, articles, comments, documents) from opengov.gr.
- Processing HTML content to Markdown.
- Processing PDF and other document formats.
- Cleaning textual content using specialized tools.
- Storing and managing data in a structured database.

For more details, see the [AI4Deliberation Pipeline Documentation](./ai4deliberation_pipeline/README.md).

### 2. Gemma Summarization Task (`gemma_summarization_task/`)
This component focuses on leveraging Gemma models for generating summaries of consultation texts or related documents. It likely involves multi-stage summarization processes.

For more details, see the [Gemma Summarization Task Documentation](./gemma_summarization_task/README.md).

### 3. Cleaning Scripts (`cleaning/`)
Contains scripts and tools, including those in `cleaning/nomoi/`, dedicated to cleaning and preprocessing textual data, potentially with a focus on legal texts (Nomoi - Laws).

### 4. Legal Text Analysis Scripts (`legal_text_analysis_scripts/`)
A collection of scripts specifically designed for analyzing legal texts, possibly for tasks like identifying legal references, structuring legal documents, or other specialized analyses.

## Future Documentation
Detailed documentation for each component and its sub-modules is planned. See `TODO_DOCUMENTATION.md` for a list of areas requiring comprehensive investigation and documentation.

## Setup and Usage

### 1. Python Environment
It is highly recommended to use a virtual environment (e.g., `venv`, `conda`) to manage project dependencies and avoid conflicts with system-wide packages or other projects.

**Important Note:** Ensure you do not install dependencies in both your global/user Python environment AND a virtual environment simultaneously for this project, as it can lead to conflicts and unpredictable behavior.

### 2. Python Dependencies
Most Python dependencies for the core pipeline are listed in `ai4deliberation_pipeline/requirements.txt`.

To install them:
```bash
# Activate your virtual environment first
# e.g., source myenv/bin/activate

pip install -r ai4deliberation_pipeline/requirements.txt
```
Individual components (like `gemma_summarization_task`) might have additional specific dependencies not listed in the main pipeline's `requirements.txt`. Refer to their respective `README.md` files or documentation once created.

### 3. Rust Library (Text Cleaner)
The project uses a Rust-based library (`text_cleaner_rs`, also referred to as `extraction_metrics_rs` in some contexts) for efficient text cleaning. This library needs to be built from source.

**Prerequisites:**
- Install Rust: Follow the instructions at [rust-lang.org](https://www.rust-lang.org/tools/install)
- Install `maturin`: `pip install maturin`

**Building the library:**
The Rust project for the text cleaner is located at `cleaning/nomoi/check_badness/extraction_metrics_rs/`.

1.  Navigate to the Rust project directory:
    ```bash
    cd cleaning/nomoi/check_badness/extraction_metrics_rs/
    ```
2.  Build and install the library into your current Python environment (preferably your activated virtual environment):
    ```bash
    maturin develop
    ```
    Alternatively, to build a wheel that can be installed with pip:
    ```bash
    maturin build --release
    # Then install the wheel from the target/wheels/ directory
    # pip install target/wheels/your_wheel_name.whl
    ```

After these steps, the `text_cleaner_rs` module should be available for import in your Python environment.

### 4. Configuration
Review and update configuration files as needed, particularly `ai4deliberation_pipeline/config/pipeline_config.yaml` for database paths and other pipeline settings.
