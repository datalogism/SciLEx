"""
Centralized logging configuration for SciLEx.

This module provides:
1. Environment-variable controlled log levels (LOG_LEVEL)
2. Optional colored output (LOG_COLOR=true)
3. Progress tracking helpers
4. Structured logging utilities

Usage:
    import logging
    from scilex.logging_config import setup_logging

    # In the CLI entry point only (never at import time)
    setup_logging()

    # In modules
    logger = logging.getLogger(__name__)
    logger.info("Message")
"""

import logging
import os
import sys


# ANSI color codes for terminal output
class Colors:
    """ANSI color codes for terminal output"""

    RESET = "\033[0m"

    # Levels
    DEBUG = "\033[36m"  # Cyan
    INFO = "\033[32m"  # Green
    WARNING = "\033[33m"  # Yellow
    ERROR = "\033[31m"  # Red
    CRITICAL = "\033[35m"  # Magenta

    # Components
    API = "\033[94m"  # Light blue


class ColoredFormatter(logging.Formatter):
    """Custom formatter with color support"""

    COLORS = {
        logging.DEBUG: Colors.DEBUG,
        logging.INFO: Colors.INFO,
        logging.WARNING: Colors.WARNING,
        logging.ERROR: Colors.ERROR,
        logging.CRITICAL: Colors.CRITICAL,
    }

    def format(self, record):
        # Add color to level name
        if record.levelno in self.COLORS:
            record.levelname = (
                f"{self.COLORS[record.levelno]}{record.levelname}{Colors.RESET}"
            )

        # Add color to API names if present
        if hasattr(record, "api_name"):
            record.api_name = f"{Colors.API}{record.api_name}{Colors.RESET}"

        return super().format(record)


def setup_logging(
    level: str | None = None,
    use_colors: bool | None = None,
    log_file: str | None = None,
) -> None:
    """
    Configure logging for SciLEx.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
               Defaults to LOG_LEVEL env var or INFO (an invalid value also
               falls back to INFO)
        use_colors: Enable colored output. Defaults to LOG_COLOR env var or auto-detect
        log_file: Optional file path to write logs to
    """
    # Determine log level
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()

    log_level = getattr(logging, str(level).upper(), None)
    if not isinstance(log_level, int):
        log_level = logging.INFO

    # Determine if colors should be used
    if use_colors is None:
        use_colors_env = os.environ.get("LOG_COLOR", "").lower()
        if use_colors_env:
            use_colors = use_colors_env in ("true", "1", "yes")
        else:
            # Auto-detect: use colors if stdout is a terminal
            use_colors = sys.stdout.isatty()

    # Create formatters
    if use_colors:
        console_format = ColoredFormatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
        )
    else:
        console_format = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
        )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        # File logs always use non-colored format
        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)
        root_logger.addHandler(file_handler)

    # Log the configuration
    root_logger.debug(
        f"Logging configured: level={level}, colors={use_colors}, file={log_file}"
    )


def add_file_log_handler(
    log_path: str, level: int = logging.WARNING
) -> logging.FileHandler:
    """
    Attach a file handler to the root logger (appends; no color).

    Call this after setup_logging() once the target directory is known.
    Returns the handler so the caller can remove it or write separators.

    Args:
        log_path: Absolute path for the log file.
        level: Minimum level written to the file (default: WARNING).

    Returns:
        The FileHandler that was attached.
    """
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logging.getLogger().addHandler(handler)
    return handler


def log_section(logger: logging.Logger, title: str, level: str = "INFO"):
    """
    Log a section header with visual separator.

    Args:
        logger: Logger instance
        title: Section title
        level: Log level (INFO, DEBUG, etc.)
    """
    log_func = getattr(logger, level.lower())
    separator = "=" * 70
    log_func(separator)
    log_func(title)
    log_func(separator)
