"""Diagnostic report and log file for user-facing error reports."""

import logging
import logging.handlers
import platform
import sys
import traceback
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def scilex_version() -> str:
    """Return the installed SciLEx version, or "unknown"."""
    try:
        return version("scilex")
    except PackageNotFoundError:
        return "unknown"


def diagnostic_text(exc: BaseException | None = None) -> str:
    """Build a report a user can paste into an issue (version, OS, traceback)."""
    try:
        system = platform.platform()
    except Exception:  # the report must never fail: it is built while handling errors
        system = sys.platform
    lines = [
        f"SciLEx {scilex_version()}",
        f"Python {sys.version.split()[0]} — {system}",
        f"Frozen app: {getattr(sys, 'frozen', False)}",
    ]
    if exc is not None:
        lines.append("")
        lines.extend(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return "\n".join(line.rstrip("\n") for line in lines)


def setup_file_logging(log_dir: Path | None = None) -> Path:
    """Send INFO+ logs to ``scilex-gui.log`` in the per-OS log directory."""
    if log_dir is None:
        from platformdirs import user_log_path

        log_dir = user_log_path("scilex")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "scilex-gui.log"
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(threadName)s [%(levelname)s] %(name)s: %(message)s"
        )
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(min(root_logger.level or logging.INFO, logging.INFO))
    return log_path
