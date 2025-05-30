#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logging Utilities

Setup and configuration for pipeline logging.
"""

import os
import logging
import logging.handlers
from typing import Dict, Any


def setup_logging(config: Dict[str, Any], module_name: str = "ai4deliberation") -> logging.Logger:
    """
    Setup logging for a pipeline module.
    
    Args:
        config: Pipeline configuration dictionary
        module_name: Name of the module for logger
        
    Returns:
        logging.Logger: Configured logger
    """
    logger = logging.getLogger(module_name)
    
    # Don't add handlers if already configured
    if logger.handlers:
        return logger
    
    # Get logging configuration
    log_config = config.get('logging', {})
    log_level = getattr(logging, log_config.get('level', 'INFO').upper())
    log_format = log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Set logger level
    logger.setLevel(log_level)
    
    # Create formatter
    formatter = logging.Formatter(log_format)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    logger.addHandler(console_handler)
    
    # File handler (if log directory exists)
    log_dir = config.get('directories', {}).get('logs')
    if log_dir and os.path.exists(log_dir):
        log_file = os.path.join(log_dir, f'{module_name}.log')
        
        # Rotating file handler
        max_size = log_config.get('max_file_size', 10) * 1024 * 1024  # MB to bytes
        backup_count = log_config.get('backup_count', 5)
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_size, backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        logger.addHandler(file_handler)
    
    return logger 