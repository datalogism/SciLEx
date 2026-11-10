"""Workflow journal of a review: what happened to it, when, by whom.

One JSON line per event in ``workflow.jsonl`` next to ``scilex.yml``,
appended and never rewritten. Each event says when (``at``), what
(``activity``), who (``agent``: the ORCID iD of the app user), what it used
(``used``: a Zotero library, a file, a configuration fingerprint), what it
produced (``generated``: counts, folders, files), its parameters, its status
and a message. It maps one to one onto ``prov:Activity`` (see
``docs/kg/provenance-proposal.md``).

Before this journal existed, the history of a review was scattered: the
``scilex.yml`` header, ``zotero_source.yml``, ``gui_run_history.json``,
``annotation_history.jsonl``, ``paper_log.json``, ``output/*/config_used.yml``.
The first time the journal is written, :func:`backfill` reconstructs what it
can from them; those events carry ``"inferred": true``.

API keys never reach the journal: values of key-like fields are masked and
the whole line goes through :func:`scilex.crawlers.utils.sanitize_secrets`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from scilex.crawlers.utils import sanitize_secrets

logger = logging.getLogger(__name__)

FILENAME = "workflow.jsonl"
_SECRET_FIELDS = re.compile(r"(api_?key|token|password|secret|authorization)", re.I)
_lock = threading.Lock()
_agent = {"uri": ""}

# Readable names of the activities (Overview history).
LABELS = {
    "create": "Review created",
    "import-zotero": "Imported from Zotero",
    "import-kg": "Imported from a knowledge graph",
    "import-bibtex": "Papers added from a BibTeX file",
    "extend-zotero": "Papers added from Zotero",
    "link": "Zotero library changed",
    "configure": "scilex.yml saved",
    "rename": "Review renamed",
    "adopt-output": "Results folder adopted",
    "consolidate": "Consolidated",
    "classify": "Papers classified in sub-corpora",
    "export-kg": "Knowledge graph exported",
    "export-file": "Papers exported",
    "push-zotero": "Papers pushed to Zotero",
    "collect-started": "Collection started",
    "papers-added": "Papers added",
    "annotation-snapshot": "Annotations read",
}


def set_agent(uri: str) -> None:
    """Who acts in this app session (IRI of the user's ORCID iD)."""
    _agent["uri"] = uri or ""


def journal_path(folder: Path) -> Path:
    """Return the journal of the review in ``folder``."""
    return Path(folder) / FILENAME


def label(event: Mapping) -> str:
    """Readable name of an event's activity."""
    activity = str(event.get("activity", ""))
    if activity.startswith("job:"):
        return f"Job: {activity[4:]}"
    return LABELS.get(activity, activity)


def _scrub(value: Any) -> Any:
    """Mask the values of key-like fields, recursively; make values JSON-safe."""
    if isinstance(value, Mapping):
        return {
            str(k): ("***" if _SECRET_FIELDS.search(str(k)) and v else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_scrub(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _line(event: dict) -> str:
    text = json.dumps(_scrub(event), ensure_ascii=False, sort_keys=False)
    return sanitize_secrets(text) + "\n"


def _write(folder: Path, events: list[dict]) -> None:
    path = journal_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(_line(e) for e in events)
    # One write call per batch, then fsync: a line is never half written by us.
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def append(
    folder: Path,
    activity: str,
    *,
    used: Mapping | None = None,
    generated: Mapping | None = None,
    params: Mapping | None = None,
    status: str = "completed",
    message: str = "",
    inferred: bool = False,
    at: datetime | str | None = None,
) -> dict | None:
    """Append one event to the review's journal; return it (None on failure).

    The first event of a review triggers :func:`backfill`. Never raises: the
    journal must not make an action fail.
    """
    when = at or datetime.now()
    event = {
        "at": when.isoformat(timespec="seconds")
        if isinstance(when, datetime)
        else when,
        "activity": activity,
        "agent": _agent["uri"],
        "used": dict(used or {}),
        "generated": dict(generated or {}),
        "params": dict(params or {}),
        "status": status,
        "message": message,
    }
    if inferred:
        event["inferred"] = True
    try:
        with _lock:
            if not journal_path(folder).is_file():
                _backfill_locked(Path(folder))
            _write(Path(folder), [event])
    except OSError:
        logger.warning("Cannot write the workflow journal of %s", folder, exc_info=True)
        return None
    return event


def load(folder: Path) -> list[dict]:
    """Every event of the journal, oldest first (damaged lines are skipped)."""
    path = journal_path(folder)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and "activity" in event:
            events.append(event)
    return events


def last(folder: Path, *activities: str) -> dict | None:
    """The most recent event of one of ``activities``."""
    return next(
        (e for e in reversed(load(folder)) if e.get("activity") in activities), None
    )


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def _mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(
            timespec="seconds"
        )
    except OSError:
        return None


_CREATED = re.compile(r"created from (?P<origin>.+?) on (?P<date>\d{4}-\d{2}-\d{2})")


def _from_config_header(folder: Path) -> list[dict]:
    try:
        head = (folder / "scilex.yml").read_text(encoding="utf-8").splitlines()[:5]
    except (OSError, UnicodeDecodeError):
        return []
    for line in head:
        match = _CREATED.search(line)
        if match:
            origin = match["origin"]
            activity = (
                "import-zotero"
                if "Zotero" in origin
                else "import-kg"
                if "knowledge graph" in origin
                else "create"
            )
            return [
                {
                    "at": f"{match['date']}T00:00:00",
                    "activity": activity,
                    "used": {"source": origin},
                    "message": f"Created from {origin}.",
                }
            ]
    return []


def _from_zotero_source(folder: Path) -> list[dict]:
    path = folder / "zotero_source.yml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict) or not data.get("library_id"):
        return []
    return [
        {
            "at": _mtime(path),
            "activity": "link",
            "used": {"zotero": _library(data)},
            "message": "Zotero library of the review (as found in zotero_source.yml).",
        }
    ]


def _from_run_history(folder: Path) -> list[dict]:
    try:
        data = json.loads((folder / "gui_run_history.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    events = []
    for key, record in (data or {}).items():
        if isinstance(record, dict) and record.get("finished_at"):
            events.append(
                {
                    "at": record["finished_at"],
                    "activity": f"job:{key}",
                    "params": {"history_key": key},
                    "message": str(record.get("message", "")),
                }
            )
    return events


def _from_annotation_history(folder: Path) -> list[dict]:
    events = []
    try:
        lines = (
            (folder / "annotation_history.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    except (OSError, UnicodeDecodeError):
        return []
    for line in lines:
        try:
            snap = json.loads(line)
        except ValueError:
            continue
        if isinstance(snap, dict) and snap.get("at"):
            events.append(
                {
                    "at": snap["at"],
                    "activity": "annotation-snapshot",
                    "params": {"origin": snap.get("origin")},
                    "generated": {
                        k: snap.get(k)
                        for k in ("papers", "annotated", "pending", "values")
                    },
                }
            )
    return events


def _from_paper_log(folder: Path) -> list[dict]:
    try:
        log = json.loads((folder / "paper_log.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    groups: dict[tuple[str, str], int] = {}
    for entry in (log or {}).values():
        if isinstance(entry, dict) and entry.get("imported_at"):
            key = (entry["imported_at"], str(entry.get("origin") or ""))
            groups[key] = groups.get(key, 0) + 1
    return [
        {
            "at": f"{date}T00:00:00",
            "activity": "papers-added",
            "params": {"origin": origin},
            "generated": {"papers": count},
        }
        for (date, origin), count in sorted(groups.items())
    ]


def _from_collections(folder: Path) -> list[dict]:
    events = []
    for used in sorted((folder / "output").glob("*/config_used.yml")):
        try:
            main = yaml.safe_load(used.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            main = {}
        events.append(
            {
                "at": _mtime(used),
                "activity": "collect-started",
                "params": {
                    "apis": main.get("apis"),
                    "years": main.get("years"),
                    "collect_name": main.get("collect_name"),
                },
                "generated": {"output_folder": f"output/{used.parent.name}"},
            }
        )
    return events


def _library(data: Mapping) -> dict:
    return {
        "library_type": data.get("library_type"),
        "library_id": str(data.get("library_id") or ""),
        "library_name": data.get("library_name") or "",
        "collection_key": data.get("collection_key"),
        "collection_name": data.get("collection_name") or "",
    }


def _backfill_locked(folder: Path) -> int:
    events = []
    for source in (
        _from_config_header,
        _from_zotero_source,
        _from_run_history,
        _from_annotation_history,
        _from_paper_log,
        _from_collections,
    ):
        try:
            events.extend(source(folder))
        except Exception:  # a damaged file must not prevent the journal
            logger.warning(
                "Cannot reconstruct history from %s", source.__name__, exc_info=True
            )
    complete = []
    for event in events:
        if not event.get("at"):
            continue
        complete.append(
            {
                "at": event["at"],
                "activity": event["activity"],
                "agent": "",
                "used": event.get("used", {}),
                "generated": event.get("generated", {}),
                "params": event.get("params", {}),
                "status": "completed",
                "message": event.get("message", ""),
                "inferred": True,
            }
        )
    complete.sort(key=lambda e: str(e["at"]))
    if complete:
        _write(folder, complete)
    else:  # an empty journal still marks the backfill as done
        journal_path(folder).touch()
    return len(complete)


def backfill(folder: Path) -> int:
    """Reconstruct past events once, when the review has no journal yet.

    Returns the number of events written (0 when the journal already exists).
    """
    with _lock:
        if journal_path(folder).is_file():
            return 0
        try:
            return _backfill_locked(Path(folder))
        except OSError:
            logger.warning(
                "Cannot write the workflow journal of %s", folder, exc_info=True
            )
            return 0


# ---------------------------------------------------------------------------
# Helpers for the hooks
# ---------------------------------------------------------------------------


def library_of(source) -> dict:
    """Journal description of a :class:`ZoteroSource` (None-safe)."""
    if source is None:
        return {}
    return _library(
        {
            "library_type": source.library_type,
            "library_id": source.library_id,
            "library_name": source.library_name,
            "collection_key": source.collection_key,
            "collection_name": source.collection_name,
        }
    )


def _rows(path: Path | None) -> int | None:
    """Number of data lines of a results file (cheap; None when missing)."""
    if path is None:
        return None
    try:
        with open(path, "rb") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except OSError:
        return None


def record_job(job, message: str, *, failed: bool = False) -> None:
    """Journal a finished job (called by the job runner; never raises)."""
    try:
        if job.folder is None:
            return
        changed = False
        results = getattr(job, "results_path", None)
        if results is not None:
            try:
                changed = results.stat().st_mtime != job.results_mtime
            except OSError:
                changed = False
        generated = {"results_rows": _rows(results)} if changed else {}
        append(
            job.folder,
            f"job:{job.history_key or job.kind}",
            params={
                "kind": job.kind,
                "history_key": job.history_key,
                "job_id": job.id,
                "started_at": job.started_at.isoformat(timespec="seconds"),
            },
            generated=generated,
            status="failed" if failed else "completed",
            message=message,
        )
    except Exception:
        logger.warning("Cannot journal job %s", getattr(job, "id", "?"), exc_info=True)
