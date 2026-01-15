"""Logging initialization helpers."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from subflow.config import Settings


def setup_logging(settings: Settings) -> None:
    """Configure subflow loggers using Settings.

    This configures the `subflow` logger (and its children) without touching
    other framework loggers (e.g. uvicorn).
    """
    logger = logging.getLogger("subflow")
    if getattr(logger, "_subflow_configured", False):
        return

    level_name = str(settings.logging.level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(
        fmt=str(settings.logging.format),
        datefmt=str(settings.logging.datefmt),
    )

    handlers: list[logging.Handler] = []
    if settings.logging.console:
        stream = logging.StreamHandler()
        stream.setLevel(level)
        stream.setFormatter(formatter)
        handlers.append(stream)

    if settings.logging.file:
        file_path = Path(str(settings.logging.file))
        if not file_path.is_absolute():
            file_path = Path(settings.log_dir) / file_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            file_path,
            maxBytes=int(settings.logging.max_bytes),
            backupCount=int(settings.logging.backup_count),
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(formatter)
        handlers.append(fh)

    logger.setLevel(level)
    logger.handlers = handlers
    logger.propagate = False
    setattr(logger, "_subflow_configured", True)
