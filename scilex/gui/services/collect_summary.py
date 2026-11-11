"""Data behind the Collect screen, free of any UI code.

Per-API status rows, aggregation phases, pre-flight summary, resume detection
and the summary of a finished run read from the collection folder.
"""

from __future__ import annotations

import csv
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from scilex.config import SciLExConfig
from scilex.pipeline import jobs as job_states

logger = logging.getLogger(__name__)

# Phases reported by run_aggregation's progress callback, in order.
AGGREGATION_PHASES = [
    ("initializing", "Loading configuration"),
    ("aggregating", "Loading and deduplicating"),
    ("filtering", "Applying filters"),
    ("citations", "Fetching citations"),
    ("ranking", "Ranking papers"),
    ("completed", "Writing results"),
]
CONFIG_USED_FILENAME = "config_used.yml"


@dataclass(frozen=True)
class ApiRow:
    """One line of the per-API status table."""

    api: str
    queries_done: int
    queries_total: int
    papers: int
    errors: int
    state: str  # waiting | running | done | partial | failed
    reason: str = ""


def _api_error_lines(api: str, logs: list[str]) -> list[str]:
    needle = api.lower()
    return [
        line
        for line in logs
        if needle in line.lower()
        and ("[ERROR]" in line or "[CRITICAL]" in line)
        and "] Job " not in line  # the job's own failure line repeats the diagnosis
    ]


# Log fragments mapped to a cause the user can act on, checked in this order.
_FAILURE_CAUSES = (
    (
        ("401", "403", "unauthorized", "forbidden", "invalid api key"),
        "API key refused: check it in API keys",
    ),
    (
        ("429", "too many requests", "rate limit"),
        "rate limited by the API: wait a few minutes, or add a key in API keys",
    ),
    (
        (
            "proxyerror",
            "connectionerror",
            "connection refused",
            "name resolution",
            "nodename nor servname",
            "max retries exceeded",
            "timed out",
            "timeout",
            "network is unreachable",
        ),
        "API unreachable: check your internet connection",
    ),
)
KEYS_HINT = "API keys"


def _failure_cause(error_lines: list[str]) -> str:
    text = " ".join(error_lines).lower()
    for fragments, cause in _FAILURE_CAUSES:
        if any(fragment in text for fragment in fragments):
            return cause
    return error_lines[-1].split("] ", 1)[-1][:200]


def collection_failure(
    collection_dir: Path, api_stats: dict, logs: list[str]
) -> str | None:
    """Explain why a finished collection brought no paper at all, else None.

    Papers already on disk (a resumed collection) count as collected: only a
    run that leaves nothing to aggregate is a failure.
    """
    if not api_stats:
        return None  # no query reported anything: nothing to diagnose
    if any(stats.get("articles", 0) for stats in api_stats.values()):
        return None
    if any(
        any(api_dir.glob("*/page_*")) for api_dir in collected_api_dirs(collection_dir)
    ):
        return None
    causes = [
        f"{api}: {_failure_cause(lines)}"
        for api in sorted(api_stats)
        if (lines := _api_error_lines(api, logs))
    ]
    if not causes:
        return (
            "No paper was collected: the queries returned no result. Try broader "
            "keywords, more years or other APIs in Configure."
        )
    return "No paper was collected. " + "; ".join(causes) + "."


def api_rows(
    api_stats: dict, logs: list[str], job_status: str | None, active: bool
) -> list[ApiRow]:
    """Build the table rows from ``job.api_stats`` (``completed/total/articles/incomplete``).

    Errors are the ERROR log lines mentioning the API (the collector reports
    no error count in its progress callback).
    """
    rows = []
    for api, stats in sorted(api_stats.items()):
        done, total = stats.get("completed", 0), stats.get("total", 0)
        papers = stats.get("articles", 0)
        error_lines = _api_error_lines(api, logs)
        reason = _failure_cause(error_lines) if error_lines else ""
        incomplete = stats.get("incomplete", 0)
        if total and done >= total and not incomplete:
            state = "done"
        elif not active and total and done >= total and not papers and error_lines:
            state = "failed"  # every query stopped on an error, nothing came back
        elif total and done >= total:
            # Every query ran, but some stopped on an error: resumable.
            state = "partial"
            reason = reason or f"{incomplete}/{total} queries incomplete"
        elif active:
            state = "running" if done else "waiting"
        elif job_status == job_states.FAILED and error_lines:
            state = "failed"
        elif done:
            state = "partial"
            reason = reason or f"{done}/{total} queries"
        else:
            state = "failed" if error_lines else "partial"
            reason = reason or "No query completed"
        # A query that stopped on an error is not finished: do not count it.
        finished = max(done - incomplete, 0)
        rows.append(
            ApiRow(api, finished, total, papers, len(error_lines), state, reason)
        )
    return rows


def phase_steps(current_phase: str | None, finished: bool) -> list[tuple[str, str]]:
    """Return ``(label, state)`` per aggregation phase: done / current / pending."""
    names = [name for name, _ in AGGREGATION_PHASES]
    index = names.index(current_phase) if current_phase in names else -1
    steps = []
    for position, (_, label) in enumerate(AGGREGATION_PHASES):
        if finished or position < index:
            state = "done"
        elif position == index:
            state = "current"
        else:
            state = "pending"
        steps.append((label, state))
    return steps


def _years_text(years: list[int], config_path: Path | None) -> str:
    """Years as written in scilex.yml: a ``"YYYY-YYYY"`` range or the explicit list."""
    if config_path is not None:
        try:
            raw = (
                (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
                .get("search", {})
                .get("years")
            )
        except (OSError, yaml.YAMLError, AttributeError):
            raw = None
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        if isinstance(raw, list) and raw:
            return ", ".join(str(year) for year in raw)
        if isinstance(raw, int) and not isinstance(raw, bool):
            return str(raw)
    if not years:
        return "no year"
    years = sorted(years)
    if years == list(range(years[0], years[-1] + 1)) and len(years) > 1:
        return f"{years[0]}-{years[-1]}"
    return ", ".join(str(year) for year in years)


def preflight_line(config: SciLExConfig, config_path: Path | None = None) -> str:
    """One-line description of what the run will do."""
    main = config.main
    apis = main.get("apis", [])
    years = main.get("years", [])
    groups = [group for group in main.get("keywords", []) if group]
    year_text = _years_text(years, config_path)
    group_text = " + ".join(str(len(group)) for group in groups) or "no"
    return (
        f"Will query {len(apis)} API(s) ({', '.join(apis) or 'none'}) for {year_text}, "
        f"{group_text} keyword(s) in {len(groups)} group(s)."
    )


def placeholder_keywords(config: SciLExConfig) -> list[str]:
    """Return the configured keywords that are still the blank template's examples."""
    from scilex.init_templates import skeleton_text

    skeleton = yaml.safe_load(skeleton_text("x")) or {}
    placeholders = {
        str(term).lower()
        for group in skeleton.get("search", {}).get("keywords", [])
        for term in group
    }
    configured = [
        str(term) for group in config.main.get("keywords", []) for term in group or []
    ]
    return [term for term in configured if term.lower() in placeholders]


@dataclass(frozen=True)
class ResumeInfo:
    """An interrupted collection that can be resumed."""

    done: int
    total: int
    partial: int = 0  # started but not finished: collected again on resume


def detect_resume(collection_dir: Path) -> ResumeInfo | None:
    """Return resume info if the last collection did not finish, else None.

    Reads ``config_used.yml`` and the per-query ``_complete`` sentinels, like
    ``scilex status``.
    """
    config_path = collection_dir / CONFIG_USED_FILENAME
    if not config_path.is_file():
        return None
    try:
        from scilex.collect_status import build_status

        used = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        totals = build_status(str(collection_dir), used)["totals"]
    except Exception:
        logger.warning("Cannot read collection state of %s", collection_dir)
        return None
    started = totals["done"] + totals["partial"] > 0
    if started and totals["done"] < totals["total"]:
        return ResumeInfo(totals["done"], totals["total"], totals["partial"])
    return None


def resume_config(collection_dir: Path, config: SciLExConfig) -> SciLExConfig:
    """Return ``config`` with the main settings of the interrupted collection.

    Same as ``scilex-collect --resume``: the snapshot ``config_used.yml`` wins
    over the current ``scilex.yml`` (completed queries are then skipped), the
    API keys stay those of the current configuration.

    Raises:
        FileNotFoundError: If the collection has no saved configuration.
    """
    config_path = collection_dir / CONFIG_USED_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(f"No saved configuration in {collection_dir}")
    main = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    main["output_dir"] = config.main["output_dir"]
    return SciLExConfig.from_dicts(main, config.api)


def target_collection_dir(config: SciLExConfig, since: str | None = None) -> Path:
    """Return the folder a collection run will write to.

    A since-run (``since``, or ``since`` in the config) writes to the sibling
    ``<collect_name>_since_<date>`` folder.
    """
    from scilex.config_defaults import DEFAULT_OUTPUT_DIR
    from scilex.since_utils import parse_since, prepare_since_config

    main = config.main
    since_date = parse_since(since or main.get("since"))
    if since_date:
        main = prepare_since_config(main, since_date)
    output_dir = main.get("output_dir", DEFAULT_OUTPUT_DIR)
    return Path(output_dir) / str(main.get("collect_name", "unknown"))


def collected_api_dirs(collection_dir: Path) -> list[Path]:
    """Return the per-API folders of raw results in ``collection_dir``."""
    from scilex.crawlers.collector_collection import api_collectors

    if not collection_dir.is_dir():
        return []
    return [
        path
        for path in sorted(collection_dir.iterdir())
        if path.is_dir() and path.name in api_collectors
    ]


# Outputs of the previous aggregation: a fresh run moves them aside, so the
# old numbers are never shown as those of the new collection. Caches and
# screening decisions stay.
PREVIOUS_RESULTS_DIRNAME = "previous_results"
AGGREGATION_OUTPUTS = (
    "aggregated_results.csv",
    "aggregation_stats.csv",
    "aggregation_report.md",
    "filtering_summary.json",
    "prisma_report.md",
    "collect_errors.log",
    "chart_aggregated_papers",
)


def clear_collection(collection_dir: Path) -> None:
    """Delete the raw API results so the next run starts from zero.

    The collector skips queries whose results are on disk; removing the
    per-API folders and the config snapshot makes it collect every query
    again. The previous aggregated results and reports are moved to
    ``previous_results/`` (replacing an older copy there).
    """
    for api_dir in collected_api_dirs(collection_dir):
        shutil.rmtree(api_dir)
    (collection_dir / CONFIG_USED_FILENAME).unlink(missing_ok=True)
    outputs = [
        collection_dir / name
        for name in AGGREGATION_OUTPUTS
        if (collection_dir / name).exists()
    ]
    if not outputs:
        return
    backup = collection_dir / PREVIOUS_RESULTS_DIRNAME
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir()
    for path in outputs:
        shutil.move(str(path), backup / path.name)


@dataclass(frozen=True)
class CollectionSummary:
    """Numbers of a finished run and its report files."""

    collected: int | None
    after_dedup: int | None
    kept: int | None
    prisma_report: Path | None
    aggregation_report: Path | None


def _to_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def load_summary(collection_dir: Path) -> CollectionSummary | None:
    """Read the summary of the last aggregation, or None if there is nothing."""
    stats: dict[str, str] = {}
    stats_path = collection_dir / "aggregation_stats.csv"
    if stats_path.is_file():
        with open(stats_path, newline="", encoding="utf-8") as handle:
            stats = {row["stat"]: row["value"] for row in csv.DictReader(handle)}
    final_count = None
    summary_path = collection_dir / "filtering_summary.json"
    if summary_path.is_file():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            final_count = _to_int(data.get("final_count"))
        except (OSError, ValueError):
            logger.warning("Unreadable %s", summary_path)
    if not stats and final_count is None:
        return None
    kept = (
        final_count if final_count is not None else _to_int(stats.get("papers_output"))
    )
    prisma = collection_dir / "prisma_report.md"
    report = collection_dir / "aggregation_report.md"
    return CollectionSummary(
        collected=_to_int(stats.get("papers_loaded")),
        after_dedup=_to_int(stats.get("papers_after_dedup")),
        kept=kept,
        prisma_report=prisma if prisma.is_file() else None,
        aggregation_report=report if report.is_file() else None,
    )
