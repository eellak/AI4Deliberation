# Config

Configuration management for the AI4Deliberation pipeline.

## Overview
This module handles all configuration aspects of the pipeline, including loading settings, validating configurations, and managing environment variable overrides.

## Components

### Files
- `config_manager.py` - Main configuration management module
- `pipeline_config.yaml` - Default pipeline configuration file

### Key Features
- **YAML Configuration**: Load settings from YAML files
- **Environment Overrides**: Override config values with environment variables
- **Validation**: Ensure configuration completeness and correctness
- **Default Values**: Sensible defaults for all settings

## Configuration Structure
The configuration typically includes:
- Database connection settings
- API endpoints and credentials
- Processing parameters
- Logging configuration
- Model selection and parameters
- Pipeline behavior settings

## Usage
```python
from config.config_manager import load_config

config = load_config()
# Or with custom config file
config = load_config('custom_config.yaml')
```

## Environment Variables
Configuration values can be overridden using environment variables following the pattern:
`AI4DELIB_SECTION_KEY=value`

Example:
```bash
export AI4DELIB_DATABASE_PATH=/custom/path/to/db
export AI4DELIB_API_KEY=your_api_key
```

## Best Practices
- Keep sensitive information (API keys, passwords) in environment variables
- Use version control for configuration files (excluding secrets)
- Document all configuration options
- Validate configurations before use