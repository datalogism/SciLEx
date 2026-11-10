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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from scilex.crawlers.utils import sanitize_secrets

logger = logging.getLogger(__name__)

FILENAME = "workflow.jsonl"
_SECRET_FIELDS = re.compile(r"(api_?key|token|password|secret|authorization)", re.I)
_lock = threading.Lock()
_agent = {"id": "", "name": ""}
UNKNOWN_AGENT = {"id": "", "name": "unknown (before tracking)"}

# Origin types of a review (first event, "created").
SCILEX_COLLECT, ZOTERO_IMPORT, KG_IMPORT, BIBTEX_IMPORT, EMPTY = (
    "scilex_collect",
    "zotero_import",
    "kg_import",
    "bibtex_import",
    "empty",
)
ORIGIN_LABELS = {
    SCILEX_COLLECT: "SciLEx collection",
    ZOTERO_IMPORT: "Zotero import",
    KG_IMPORT: "knowledge graph import",
    BIBTEX_IMPORT: "BibTeX import",
    EMPTY: "empty review",
}
VALIDATED_PREFIX = "ANNOT_VALID_BY:"

# Job history keys by kind, with the results columns an enricher writes.
EXTENSIONS = {
    "pipeline": "collection",
    "extend-add": "new queries (add new papers)",
    "extend-reaggregate": "re-aggregation",
    "aggregate": "aggregation",
    "analysis-snowball": "snowball",
}
ENRICHERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "analysis-citations": ("citations", ()),
    "analysis-enrich": ("Papers with Code", ("tags", "pwc_url", "github_repo")),
    "analysis-crossref": (
        "Crossref",
        (
            "abstract",
            "journalAbbreviation",
            "volume",
            "pages",
            "date",
            "publisher",
            "rights",
            "crossref_type",
            "crossref_cited_by",
            "crossref_funders",
            "issn",
        ),
    ),
    "analysis-lpwc": (
        "Linked Papers With Code",
        (
            "lpwc_paper",
            "lpwc_tasks",
            "lpwc_methods",
            "lpwc_datasets",
            "lpwc_repositories",
            "lpwc_conference",
        ),
    ),
    "analysis-orkg": (
        "ORKG",
        ("orkg_paper", "orkg_research_fields", "orkg_research_problems"),
    ),
    "analysis-search_keywords": (
        "search keywords",
        ("collect_keywords", "bonus_keyword_tags"),
    ),
    "analysis-zotero_citations": ("Zotero citation snapshot", ()),
    "analysis-citation_metrics": ("citation metrics", ()),
}

# Readable names of the activities (Overview history).
LABELS = {
    "created": "Review created",
    "create": "Review created",
    "zotero-sync-link": "Linked with Zotero",
    "zotero-pull": "Changes pulled from Zotero",
    "zotero-push": "Changes pushed to Zotero",
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


def set_agent(uri: str, name: str = "") -> None:
    """Who acts in this app session: IRI of the user's ORCID iD and display name."""
    _agent["id"] = uri or ""
    _agent["name"] = name or ""


def current_agent() -> dict:
    """The agent of new events (never empty: "unknown user" without a profile)."""
    return {
        "id": _agent["id"],
        "name": _agent["name"] or _agent["id"] or "unknown user",
    }


def agent_name(event: Mapping) -> str:
    """Display name of an event's agent (older string agents accepted)."""
    agent = event.get("agent")
    if isinstance(agent, Mapping):
        return str(agent.get("name") or agent.get("id") or "unknown user")
    return str(agent or UNKNOWN_AGENT["name"])


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
    annotation: Mapping | None = None,
    zotero_actors: Mapping | None = None,
) -> dict | None:
    """Append one event to the review's journal; return it (None on failure).

    ``annotation``: annotation state after the event (see
    :func:`annotation_state`); its change since the previous state is added as
    ``delta``. ``zotero_actors``: who changed the Zotero items (see
    :func:`zotero_actors`). The first event of a review triggers
    :func:`backfill`. Never raises: the journal must not make an action fail.
    """
    when = at or datetime.now()
    event = {
        "at": when.isoformat(timespec="seconds")
        if isinstance(when, datetime)
        else when,
        "activity": activity,
        "agent": dict(UNKNOWN_AGENT) if inferred else current_agent(),
        "used": dict(used or {}),
        "generated": dict(generated or {}),
        "params": dict(params or {}),
        "status": status,
        "message": message,
    }
    if inferred:
        event["inferred"] = True
    if zotero_actors:
        event["zotero_actors"] = dict(zotero_actors)
    try:
        with _lock:
            if not journal_path(folder).is_file():
                _backfill_locked(Path(folder))
            if annotation:
                event["annotation"] = _with_delta(Path(folder), dict(annotation))
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


def _results_file(folder: Path) -> Path | None:
    """The review's results file, found without reading scilex.yml's schema."""
    try:
        state = (
            yaml.safe_load((folder / "review_state.yml").read_text(encoding="utf-8"))
            or {}
        )
    except (OSError, yaml.YAMLError):
        state = {}
    if isinstance(state, dict) and state.get("output_folder"):
        candidate = folder / str(state["output_folder"]) / "aggregated_results.csv"
        if candidate.is_file():
            return candidate
    found = sorted((folder / "output").glob("*/aggregated_results.csv"))
    return found[0] if found else None


def _archive_origin(results: Path | None) -> str | None:
    """Origin suggested by the ``archive`` column (Zotero, KG, BibTeX) of the results."""
    if results is None:
        return None
    try:
        import pandas as pd

        archives = pd.read_csv(results, sep=None, engine="python", usecols=["archive"])[
            "archive"
        ]
    except Exception:
        return None
    counts = archives.astype(str).str.split(";").str[0].str.rstrip("*").value_counts()
    if counts.empty:
        return None
    top = counts.index[0]
    return {"Zotero": ZOTERO_IMPORT, "KG": KG_IMPORT, "BibTeX": BIBTEX_IMPORT}.get(
        top, SCILEX_COLLECT
    )


def _collect_summary(main: Mapping, text: str = "") -> dict:
    """Keywords, years and sources of a collection (and the config fingerprint)."""
    import hashlib

    summary = {
        "keywords": main.get("keywords"),
        "years": main.get("years"),
        "apis": main.get("apis"),
    }
    if text:
        summary["config_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return summary


def _from_config_header(folder: Path) -> list[dict]:
    """The "created" event: origin of the review, inferred from what exists."""
    try:
        head = (folder / "scilex.yml").read_text(encoding="utf-8").splitlines()[:5]
    except (OSError, UnicodeDecodeError):
        head = []
    at = None
    origin_text = ""
    for line in head:
        match = _CREATED.search(line)
        if match:
            origin_text, at = match["origin"], f"{match['date']}T00:00:00"
            break
    source = _from_zotero_source(folder)
    library = source[0]["used"]["zotero"] if source else {}
    collections = sorted((folder / "output").glob("*/config_used.yml"), key=_mtime_key)
    params: dict = {}
    used: dict = {}
    if "Zotero" in origin_text:
        origin = ZOTERO_IMPORT
        used = {"zotero": library, "source": origin_text}
    elif "knowledge graph" in origin_text:
        origin = KG_IMPORT
        used = {"source": origin_text}
    elif collections:
        origin = SCILEX_COLLECT
        text = collections[0].read_text(encoding="utf-8", errors="replace")
        try:
            main = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            main = {}
        params = _collect_summary(main if isinstance(main, dict) else {}, text)
        at = at or _mtime(collections[0])
    else:
        origin = _archive_origin(_results_file(folder)) or EMPTY
        if origin == ZOTERO_IMPORT:
            used = {"zotero": library}
    at = at or _mtime(folder / "scilex.yml")
    return [
        {
            "at": at,
            "activity": "created",
            "params": {"origin": origin, **params},
            "used": used,
            "message": f"Origin: {ORIGIN_LABELS[origin]}"
            + (f" ({origin_text})" if origin_text else "")
            + ".",
        }
    ]


def _mtime_key(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


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
            params = {"history_key": key}
            if key in EXTENSIONS:
                params.update(category="extension", mode=EXTENSIONS[key])
            elif key in ENRICHERS:
                params.update(category="enrichment", source=ENRICHERS[key][0])
            events.append(
                {
                    "at": record["finished_at"],
                    "activity": f"job:{key}",
                    "params": params,
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
                "agent": dict(UNKNOWN_AGENT),
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


def annotation_state(papers_tags) -> dict:
    """Annotation state of a list of tag lists (one per paper).

    Same counts as the Overview snapshots (:func:`overview.snapshot_of`), plus
    the papers validated against the grid (``ANNOT_VALID_BY:<id>`` tags) and
    who validated them.
    """
    from scilex.gui.services.overview import snapshot_of

    # TODO(after merging main a618f403): read the workflow tags (ANNOT,
    # ANNOT_VALID_BY, DELETED_BY) with scilex.review_tags.workflow instead of the
    # VALIDATED_PREFIX match below, and count ANNOT / DELETED_BY the same way.
    tag_lists = [list(tags) for tags in papers_tags]
    # Validation marks are not codes of the grid: counted apart below.
    snap = snapshot_of(
        [
            [t for t in tags if not str(t).startswith(VALIDATED_PREFIX)]
            for tags in tag_lists
        ],
        "journal",
    )
    validators: dict[str, int] = {}
    validated = 0
    for tags in tag_lists:
        ids = {
            t[len(VALIDATED_PREFIX) :]
            for t in tags
            if str(t).startswith(VALIDATED_PREFIX)
        }
        validated += bool(ids)
        for who in ids:
            validators[who] = validators.get(who, 0) + 1
    return {
        "papers": snap.papers,
        "annotated": snap.annotated,
        "pending": snap.pending,
        "codes": snap.values,
        "by_dimension": snap.by_dimension,
        "validated": validated,
        "validated_by": validators,
    }


def annotation_of_results(path: Path | None) -> dict | None:
    """Annotation state of a results file (its ``tags`` column)."""
    if path is None or not Path(path).is_file():
        return None
    try:
        import pandas as pd

        tags = pd.read_csv(path, sep=None, engine="python", usecols=["tags"])["tags"]
    except Exception:
        return None
    lists = [
        [t.strip() for t in str(v).split(";") if t.strip()]
        if isinstance(v, str)
        else []
        for v in tags
    ]
    return annotation_state(lists)


def annotation_of_items(items) -> dict:
    """Annotation state of Zotero items."""
    from scilex.gui.services.overview import zotero_tags

    return annotation_state(zotero_tags(items))


def _with_delta(folder: Path, state: dict) -> dict:
    previous = next(
        (
            e["annotation"]
            for e in reversed(load(folder))
            if isinstance(e.get("annotation"), dict)
        ),
        None,
    )
    if previous is None:
        return state
    state["delta"] = {
        key: state.get(key, 0) - previous.get(key, 0)
        for key in ("papers", "annotated", "pending", "codes", "validated")
    }
    return state


def zotero_actors(items, since: str | None = None) -> dict:
    """Who created / last modified the Zotero items (since ``since``, ISO time).

    Read from each item's ``meta.createdByUser`` and ``meta.lastModifiedByUser``
    (group libraries): group annotators appear even if they never used SciLEx.
    Returns ``{username: {"id", "name", "created", "modified"}}``.
    """
    actors: dict[str, dict] = {}

    def count(user, field: str) -> None:
        if not isinstance(user, Mapping):
            return
        key = str(user.get("username") or user.get("id") or "")
        if not key:
            return
        entry = actors.setdefault(
            key,
            {
                "id": user.get("id"),
                "name": user.get("name") or key,
                "created": 0,
                "modified": 0,
            },
        )
        entry[field] += 1

    for item in items or []:
        meta = item.get("meta") or {}
        data = item.get("data") or {}
        added = str(data.get("dateAdded") or "")
        modified = str(data.get("dateModified") or "")
        if since is None or added >= since:
            count(meta.get("createdByUser"), "created")
        if since is None or modified >= since:
            count(
                meta.get("lastModifiedByUser") or meta.get("createdByUser"), "modified"
            )
    return actors


def last_zotero_time(folder: Path) -> str | None:
    """Time of the last event that read the review's Zotero library."""
    event = last(folder, "created", "extend-zotero", "zotero-sync-link", "zotero-pull")
    if event is None:
        return None
    # Zotero dates are UTC ("2026-11-10T15:35:35Z"); the journal is local time.
    try:
        local = datetime.fromisoformat(str(event["at"])).astimezone()
    except ValueError:
        return None
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _filled(path: Path | None, columns: tuple[str, ...]) -> dict[str, int]:
    """Non-empty cells per column of a results file."""
    if path is None or not columns:
        return {}
    try:
        import pandas as pd

        data = pd.read_csv(
            path, sep=None, engine="python", dtype=str, keep_default_na=False
        )
    except Exception:
        return {}
    filled = {}
    for column in columns:
        if column in data.columns:
            values = data[column].str.strip()
            filled[column] = int(
                ((values != "") & (values != "NA") & (values != "nan")).sum()
            )
    return filled


def _last_generated(folder: Path, key: str):
    for event in reversed(load(folder)):
        value = (event.get("generated") or {}).get(key)
        if value is not None:
            return value
    return None


def _collect_params(folder: Path) -> dict:
    """Keywords, years, sources and fingerprint of the review's scilex.yml."""
    try:
        text = (Path(folder) / "scilex.yml").read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}
    search = data.get("search") if isinstance(data, dict) else None
    return _collect_summary(search if isinstance(search, dict) else {}, text)


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
        key = job.history_key or job.kind
        params = {
            "kind": job.kind,
            "history_key": job.history_key,
            "job_id": job.id,
            "started_at": job.started_at.isoformat(timespec="seconds"),
        }
        generated: dict = {}
        before = _last_generated(job.folder, "results_rows")
        if changed:
            generated["results_rows"] = _rows(results)
            if before is not None:
                generated["results_rows_before"] = before
        if key in EXTENSIONS:
            params["category"] = "extension" if key != "aggregate" else "collection"
            params["mode"] = EXTENSIONS[key]
            if key in ("pipeline", "extend-add", "extend-reaggregate"):
                params["search"] = _collect_params(job.folder)
        elif key in ENRICHERS:
            source, columns = ENRICHERS[key]
            params["category"] = "enrichment"
            params["source"] = source
            if changed and columns:
                filled = _filled(results, columns)
                previous = _last_generated(job.folder, "filled") or {}
                generated["filled"] = {**previous, **filled}
                gains = {c: n - previous.get(c, 0) for c, n in filled.items()}
                generated["columns_written"] = sorted(c for c, g in gains.items() if g)
                if previous:
                    generated["papers_updated"] = max(gains.values(), default=0)
        append(
            job.folder,
            f"job:{key}",
            params=params,
            generated=generated,
            status="failed" if failed else "completed",
            message=message,
        )
    except Exception:
        logger.warning("Cannot journal job %s", getattr(job, "id", "?"), exc_info=True)
