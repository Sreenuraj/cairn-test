"""
Structured logging for cairn-test.
"""

from __future__ import annotations
import json
import logging
import sys
from typing import Any

class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""
    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "level": record.levelname,
            "time": self.formatTime(record, self.datefmt),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

def setup_logging(json_mode: bool = False, level: int = logging.INFO) -> None:
    """Configure root logger for cairn-test."""
    root = logging.getLogger("cairn_test")
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if json_mode:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    root.addHandler(handler)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"cairn_test.{name}")
