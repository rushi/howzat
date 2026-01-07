"""Logging configuration for Howzat."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console()

# Module-level logger
_logger: logging.Logger | None = None


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    verbose: bool = False,
) -> logging.Logger:
    """Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for logging
        verbose: If True, set level to DEBUG

    Returns:
        Configured logger instance
    """
    global _logger

    if verbose:
        level = "DEBUG"

    # Create root logger for our package
    logger = logging.getLogger("howzat")
    logger.setLevel(level)
    logger.handlers.clear()

    # Rich console handler for pretty terminal output
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=verbose,
    )
    console_handler.setLevel(level)
    console_format = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    _logger = logger
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Optional module name for child logger

    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f"howzat.{name}")
    return logging.getLogger("howzat")


def set_console_level(level: str | int) -> None:
    """Set console handler log level without affecting file logging.

    Args:
        level: Log level (e.g., "WARNING", logging.WARNING)
    """
    logger = logging.getLogger("howzat")

    for handler in logger.handlers:
        if isinstance(handler, RichHandler):
            handler.setLevel(level)
