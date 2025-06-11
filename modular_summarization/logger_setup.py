"""Centralised logger initialisation so all modules share formatters."""
import logging
import sys
from .config import RUN_TIMESTAMP

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

_DEF_LEVEL = logging.INFO


def init_logging(level=_DEF_LEVEL):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATEFMT))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    # also file handler
    file_handler = logging.FileHandler(f"summarization_{RUN_TIMESTAMP}.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATEFMT))
    root.addHandler(file_handler)
