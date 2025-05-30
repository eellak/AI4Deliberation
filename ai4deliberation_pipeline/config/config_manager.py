#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration Manager for AI4Deliberation Pipeline

Handles loading, validation, and environment variable overrides for pipeline configuration.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional


def get_config_path() -> str:
    """
    Get the path to the pipeline configuration file.
    
    Returns:
        str: Path to pipeline_config.yaml
    """
    config_dir = os.path.dirname(__file__)
    return os.path.join(config_dir, 'pipeline_config.yaml')


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load pipeline configuration from YAML file with environment variable overrides.
    
    Args:
        config_path: Optional custom path to config file
        
    Returns:
        dict: Configuration dictionary with environment overrides applied
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid
    """
    if config_path is None:
        config_path = get_config_path()
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Invalid YAML in config file {config_path}: {e}")
    
    # Apply environment variable overrides
    config = _apply_environment_overrides(config)
    
    # Validate and create directories
    config = _ensure_directories_exist(config)
    
    return config


def _apply_environment_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply environment variable overrides using AI4D_ prefix.
    
    Args:
        config: Base configuration dictionary
        
    Returns:
        dict: Configuration with environment overrides applied
    """
    # Environment variables that can override config values
    env_overrides = {
        'AI4D_DATABASE_DEFAULT_PATH': ['database', 'default_path'],
        'AI4D_DIRECTORIES_TEMP_PROCESSING': ['directories', 'temp_processing'],
        'AI4D_SCRAPER_REQUEST_TIMEOUT': ['scraper', 'request_timeout'],
        'AI4D_PDF_PROCESSING_GLOSSAPI_MAX_WORKERS': ['pdf_processing', 'glossapi', 'max_workers'],
        'AI4D_RUST_CLEANER_THREADS': ['rust_cleaner', 'threads'],
        'AI4D_LOGGING_LEVEL': ['logging', 'level'],
    }
    
    for env_var, config_path in env_overrides.items():
        env_value = os.getenv(env_var)
        if env_value is not None:
            # Navigate to the nested config location
            current = config
            for key in config_path[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            
            # Convert value to appropriate type
            final_key = config_path[-1]
            if final_key in ['request_timeout', 'max_workers', 'threads']:
                current[final_key] = int(env_value)
            else:
                current[final_key] = env_value
    
    return config


def _ensure_directories_exist(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure required directories exist, creating them if necessary.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        dict: Configuration with validated directories
    """
    directories = config.get('directories', {})
    
    # Create directories that should exist
    for dir_key, dir_path in directories.items():
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
                logging.info(f"Created directory: {dir_path}")
            except OSError as e:
                logging.warning(f"Could not create directory {dir_path}: {e}")
    
    return config


def validate_config(config: Dict[str, Any]) -> bool:
    """
    Validate pipeline configuration structure and required fields.
    
    Args:
        config: Configuration dictionary to validate
        
    Returns:
        bool: True if configuration is valid
        
    Raises:
        ValueError: If configuration is invalid
    """
    required_sections = ['database', 'directories', 'scraper', 'logging']
    
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required configuration section: {section}")
    
    # Validate database configuration
    if 'default_path' not in config['database']:
        raise ValueError("Missing database.default_path in configuration")
    
    # Validate directories
    required_dirs = ['temp_processing', 'logs']
    for dir_name in required_dirs:
        if dir_name not in config['directories']:
            raise ValueError(f"Missing directories.{dir_name} in configuration")
    
    # Validate scraper configuration
    scraper_required = ['request_timeout', 'batch_size']
    for field in scraper_required:
        if field not in config['scraper']:
            raise ValueError(f"Missing scraper.{field} in configuration")
    
    return True


def get_database_path(config: Optional[Dict[str, Any]] = None) -> str:
    """
    Get the database path from configuration.
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        str: Path to database file
    """
    if config is None:
        config = load_config()
    
    return config['database']['default_path']


def get_temp_directory(config: Optional[Dict[str, Any]] = None) -> str:
    """
    Get the temporary processing directory from configuration.
    
    Args:
        config: Optional configuration dictionary (loads if None)
        
    Returns:
        str: Temporary processing directory path
    """
    if config is None:
        config = load_config()
    
    return config['directories']['temp_processing'] 