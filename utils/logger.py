"""
utils/logger.py
===============
Centralised logging configuration for Nova Voice Assistant.

Features
--------
- Rotating file handler (10 MB per file, keep 5 backups)
- Coloured console output (when a TTY is attached)
- ISO-8601 timestamps
- Separate log levels for file vs console
- Thread-safe by design (Python's logging module is already thread-safe)

Usage
-----
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Nova started")
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# ANSI colour codes (console only)
# ---------------------------------------------------------------------------
class _ColourFormatter(logging.Formatter):
    """
    A logging formatter that prepends ANSI escape codes to add colour to
    log records in terminal output.  Falls back to plain text if the stream
    is not a TTY (e.g. when piped to a file).
    """

    GREY   = "\x1b[38;5;245m"
    CYAN   = "\x1b[36m"
    YELLOW = "\x1b[33m"
    RED    = "\x1b[31m"
    BOLD_RED = "\x1b[1;31m"
    RESET  = "\x1b[0m"

    _LEVEL_COLOURS: dict[int, str] = {
        logging.DEBUG:    GREY,
        logging.INFO:     CYAN,
        logging.WARNING:  YELLOW,
        logging.ERROR:    RED,
        logging.CRITICAL: BOLD_RED,
    }

    _FMT = "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
    _DATE_FMT = "%Y-%m-%dT%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        colour = self._LEVEL_COLOURS.get(record.levelno, self.RESET)
        formatter = logging.Formatter(
            fmt=f"{colour}{self._FMT}{self.RESET}",
            datefmt=self._DATE_FMT,
        )
        return formatter.format(record)


class _PlainFormatter(logging.Formatter):
    """Plain text formatter for file output (no ANSI codes)."""

    _FMT = "%(asctime)s  %(levelname)-8s  %(name)s  [%(filename)s:%(lineno)d] — %(message)s"
    _DATE_FMT = "%Y-%m-%dT%H:%M:%S"

    def __init__(self) -> None:
        super().__init__(fmt=self._FMT, datefmt=self._DATE_FMT)


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_configured: bool = False


def configure_logging(
    log_file: Optional[Path] = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> None:
    """
    Configure the root logger once.

    Parameters
    ----------
    log_file:       Path to the rotating log file.  If None, file logging is skipped.
    console_level:  Minimum level for console output (default INFO).
    file_level:     Minimum level for file output   (default DEBUG).
    max_bytes:      Maximum size of each log file before rotation.
    backup_count:   Number of rotated backups to keep.
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # handlers filter independently

    # ------------------------------------------------------------------
    # Console handler
    # ------------------------------------------------------------------
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    if sys.stdout.isatty():
        console_handler.setFormatter(_ColourFormatter())
    else:
        console_handler.setFormatter(_PlainFormatter())
    root.addHandler(console_handler)

    # ------------------------------------------------------------------
    # Rotating file handler
    # ------------------------------------------------------------------
    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(_PlainFormatter())
        root.addHandler(file_handler)

    # ------------------------------------------------------------------
    # Silence noisy third-party loggers
    # ------------------------------------------------------------------
    for noisy in ("urllib3", "httpcore", "httpx", "openai", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.  Logging must have been configured beforehand
    via :func:`configure_logging`.

    Parameters
    ----------
    name:   Typically ``__name__`` of the calling module.

    Returns
    -------
    logging.Logger
    """
    return logging.getLogger(name)
