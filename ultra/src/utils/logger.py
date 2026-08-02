"""
Structured Logging System
Every event is logged with context, traceable, and persistent.
"""
import logging
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from logging.handlers import RotatingFileHandler
import traceback


class StructuredLogFormatter(logging.Formatter):
    """JSON formatter for machine-readable logs"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "extra"):
            log_entry.update(record.extra)

        # Add exception info
        if record.exc_info:
            log_entry["exception"] = traceback.format_exception(*record.exc_info)

        return json.dumps(log_entry, default=str)


class HumanLogFormatter(logging.Formatter):
    """Human-readable formatter for console output"""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        return f"[{timestamp}] [{record.levelname:8}] [{record.name:20}] {record.getMessage()}"


class TradeContextFilter(logging.Filter):
    """Injects trading context into every log record"""

    def __init__(self):
        super().__init__()
        self.context: Dict[str, Any] = {}

    def set_context(self, **kwargs):
        self.context.update(kwargs)

    def clear_context(self):
        self.context.clear()

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self.context.items():
            setattr(record, key, value)
        return True


def setup_logger(
    name: str = "trading_bot",
    log_dir: str = "logs",
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> logging.Logger:
    """
    Setup structured logger with both file and console handlers.

    File: JSON formatted for analytics
    Console: Human readable for development
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level))

    # Force UTF-8 on console streams (fixes UnicodeEncodeError with emoji on Windows cp1252)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    # Ensure log directory exists
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # File handler - JSON structured
    file_handler = RotatingFileHandler(
        f"{log_dir}/bot.log",
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    file_handler.setFormatter(StructuredLogFormatter())
    file_handler.setLevel(logging.DEBUG)

    # Console handler - Human readable
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(HumanLogFormatter())
    console_handler.setLevel(getattr(logging, log_level))

    # Add context filter
    context_filter = TradeContextFilter()
    logger.addFilter(context_filter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info(f"Logger initialized | Level: {log_level} | Dir: {log_dir}")

    return logger


def get_logger(name: str = "trading_bot") -> logging.Logger:
    """Get existing logger or create new one"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


# Convenience function for structured logging
def log_event(
    logger: logging.Logger,
    level: str,
    message: str,
    **kwargs
):
    """Log with structured extra data"""
    extra = {"extra": kwargs}
    getattr(logger, level.lower())(message, extra=extra)
