"""When each costly action of a review last completed, kept across app restarts.

Jobs live in memory only (:mod:`scilex.gui.services.jobs`); this file keeps
the date of the last completed run of each action in the review folder, so a
page can say "last run 2 h ago" before the user starts a slow or paid job
again. Runs made before this history existed (or by the CLI) are inferred
from the files they wrote, when there are any.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from scilex.gui.services.workspace import Review

logger = logging.getLogger(__name__)

HISTORY_FILENAME = "gui_run_history.json"
# A run within this many days is "recent" (green); older ones are grey.
RECENT_DAYS = 30
MESSAGE_MAX_CHARS = 300

NEVER = "never"
RECENT = "recent"
OLD = "old"

# Keys of the actions that are not analyses (those are "analysis-<name>").
PIPELINE = "pipeline"
AGGREGATE = "aggregate"
EXTEND_ADD = "extend-add"
EXTEND_REAGGREGATE = "extend-reaggregate"

_lock = threading.Lock()


@dataclass(frozen=True)
class RunRecord:
    """Last completed run of one action."""

    key: str
    finished_at: datetime
    message: str = ""
    inferred: bool = False  # dated from its output files, not from the history


def history_path(folder: Path) -> Path:
    """Return the history file of the review in ``folder``."""
    return Path(folder) / HISTORY_FILENAME


def load(folder: Path) -> dict[str, RunRecord]:
    """Read the history of the review in ``folder`` (empty if missing or broken)."""
    path = history_path(folder)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable run history %s: %s", path, exc)
        return {}
    records = {}
    for key, entry in data.items() if isinstance(data, dict) else ():
        try:
            records[key] = RunRecord(
                key,
                datetime.fromisoformat(entry["finished_at"]),
                str(entry.get("message", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return records


def record(folder: Path, key: str, finished_at: datetime, message: str = "") -> None:
    """Store ``key`` as completed at ``finished_at`` (atomic write, thread-safe)."""
    path = history_path(folder)
    with _lock:
        data = {
            name: {"finished_at": rec.finished_at.isoformat(), "message": rec.message}
            for name, rec in load(folder).items()
        }
        data[key] = {
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "message": message[:MESSAGE_MAX_CHARS],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(data, out, indent=1, sort_keys=True)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _inferred_files(review: Review, key: str) -> list[Path]:
    """Files whose date tells when ``key`` last ran, for runs not in the history."""
    from scilex.gui.services import analyses

    collect_dir = review.collection_dir
    if key in (PIPELINE, AGGREGATE):
        return [review.results_path]
    if key == "analysis-citations":
        return [collect_dir / "citations_cache.json"]
    prefix = "analysis-"
    if key.startswith(prefix):
        return analyses.existing_outputs(collect_dir, key[len(prefix) :])
    return []


def last_run(review: Review, key: str, history: dict | None = None) -> RunRecord | None:
    """Return the last completed run of ``key`` for ``review``, or None if never run.

    ``history`` is the result of :func:`load`, to read the file once per page.
    """
    history = load(review.folder) if history is None else history
    if key in history:
        return history[key]
    times = []
    for path in _inferred_files(review, key):
        try:
            times.append(path.stat().st_mtime)
        except OSError:
            continue
    if not times:
        return None
    return RunRecord(key, datetime.fromtimestamp(max(times)), inferred=True)


def freshness(run: RunRecord | None, now: datetime | None = None) -> str:
    """Return ``NEVER``, ``RECENT`` (within ``RECENT_DAYS``) or ``OLD``."""
    if run is None:
        return NEVER
    now = now or datetime.now()
    return RECENT if now - run.finished_at <= timedelta(days=RECENT_DAYS) else OLD


def ago(when: datetime, now: datetime | None = None) -> str:
    """Return ``when`` as "just now", "5 min ago", "3 h ago", "2 days ago" or a date."""
    seconds = max(0, int(((now or datetime.now()) - when).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    days = seconds // 86400
    if days < RECENT_DAYS:
        return "yesterday" if days == 1 else f"{days} days ago"
    return f"on {when:%d %b %Y}"


def describe(run: RunRecord | None, now: datetime | None = None) -> str:
    """Short text of the chip: "Never run" or "Last run 3 h ago"."""
    if run is None:
        return "Never run"
    return f"Last run {ago(run.finished_at, now)}"


def details(run: RunRecord | None) -> str:
    """Longer text of the tooltip: date, result and where the date comes from."""
    if run is None:
        return "Not run yet for this review."
    text = f"Completed on {run.finished_at:%d %b %Y at %H:%M}."
    if run.message:
        text += f" {run.message}"
    if run.inferred:
        text += " (Date of its output files.)"
    return text
