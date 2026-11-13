"""Background jobs for the desktop GUI.

Two kinds of jobs: the pipeline (collection then aggregation, see
:meth:`JobRunner.start_pipeline`) and generic tasks such as an export or an
analysis (:meth:`JobRunner.start_task`).

A job runs in its own thread; the UI polls :class:`Job` fields with a timer.

**Resources.** Several jobs run at the same time; a job declares what it uses
and is refused only when an active job holds a conflicting use (see
:func:`conflicts`):

- ``collect`` (``exclusive``): the source APIs, rate limits and VPN, shared by
  every review: one collection at a time in the app;
- ``results:<review id>``: the review's ``aggregated_results.csv``, in mode
  ``read`` (charts, graph, summaries, exports: never blocked), ``write`` (column
  enrichers, which merge only what they changed, so they run together, see
  :mod:`results_store`) or ``rows`` (aggregation, extension, consolidation,
  imports, Zotero link/pull: alone on that review's results);
- ``zotero:<library>`` (``rows``): writes to a Zotero library;
- ``job:<kind>:<review id>`` (``rows``, added to every job): the same action
  twice on one review.

Log capture: records of the collector's anonymous threads cannot be traced to
a job; they go to the collection when one runs, else to the only active job.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from scilex.config import SciLExConfig
from scilex.crawlers.utils import sanitize_secrets
from scilex.gui.services import extend as extension
from scilex.gui.services import journal, run_history
from scilex.gui.services.workspace import Review
from scilex.pipeline import jobs as job_states
from scilex.pipeline.jobs import LogLinesHandler, WorkerThreadFilter

logger = logging.getLogger(__name__)

# Share of the progress bar given to each pipeline stage.
PIPELINE = "pipeline"

COLLECT_RANGE = (0, 70)
AGGREGATE_RANGE = (70, 100)


class CollectionFailedError(RuntimeError):
    """The collection finished without a single paper (refused key, no network…)."""


class JobConflictError(RuntimeError):
    """Raised when a job is started while a conflicting one is still active."""


READ, WRITE, ROWS, EXCLUSIVE = "read", "write", "rows", "exclusive"
COLLECT = "collect"
Resource = tuple[str, str]  # (name, mode)


def results_resource(review_id: str, mode: str) -> Resource:
    """Use of a review's aggregated results."""
    return (f"results:{review_id}", mode)


def zotero_resource(library: str) -> Resource:
    """Writes to one Zotero library (``"group:123"``, ``"user:45"``)."""
    return (f"zotero:{library}", ROWS)


def review_zotero(review: Review) -> Resource:
    """Writes to the review's Zotero library (its own, else the keys' library)."""
    from scilex.gui.services.zotero_library import load_source

    try:
        source = load_source(review.folder)
    except Exception:  # unreadable zotero_source.yml: the default library
        source = None
    if source is None:
        return zotero_resource("default")
    return zotero_resource(f"{source.library_type}:{source.library_id}")


def conflicts(mode_a: str, mode_b: str) -> bool:
    """Whether two uses of the same resource cannot run at the same time.

    Readers never conflict; column writers (``write``) run together; ``rows``
    and ``exclusive`` exclude every other writer.
    """
    if READ in (mode_a, mode_b):
        return False
    return not (mode_a == WRITE and mode_b == WRITE)


KIND_LABELS = {"pipeline": "collection"}
# Name of an extension's Zotero collection: "Extension <n> · <label> · <date>".
EXTENSION_LABELS = {
    extension.ADD_NEW: "New collect",
    extension.REAGGREGATE: "Re-aggregation",
    None: "Full collection",
}


@dataclass
class Job:
    """State of one pipeline run, read by the UI."""

    id: str
    review_id: str
    kind: str = PIPELINE
    status: str = job_states.PENDING
    phase: str = "pending"
    progress: int = 0
    message: str = ""
    logs: list[str] = field(default_factory=list)
    api_stats: dict = field(default_factory=dict)
    aggregation_phase: str | None = None  # last phase of the aggregation callback
    screening_fraction: float | None = None  # LLM screening progress, 0..1
    error: str | None = None
    result: Any = None  # value returned by a task body, for the page to display
    started_at: datetime = field(default_factory=datetime.now)
    # Where and under which name a completed run is kept in the run history
    # (see run_history); an empty key keeps nothing (e.g. a dry run).
    history_key: str = ""
    folder: Path | None = field(default=None, repr=False)
    # Results file of the review and its state when the job started: a job
    # that rewrites it records the new papers in the paper log.
    results_path: Path | None = field(default=None, repr=False)
    results_mtime: float | None = field(default=None, repr=False)
    review_name: str = ""
    resources: tuple[Resource, ...] = ()
    finished_at: datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    thread_ids: set[int] = field(default_factory=set, repr=False)

    @property
    def is_active(self) -> bool:
        """True while the job is pending, running or cancelling."""
        return self.status in job_states.ACTIVE_STATUSES

    def describe(self) -> str:
        """``"collection on rag_kg"``: what the user sees of a blocking job."""
        kind = KIND_LABELS.get(self.kind) or self.kind.removeprefix(
            "analysis-"
        ).replace("-", " ")
        return f"{kind} on {self.review_name or self.review_id}"


async def wait_for(job: Job, interval: float = 0.1) -> Job:
    """Wait (without blocking the event loop) until ``job`` has ended.

    For short actions a page awaits (Zotero sync, BibTeX import): running them
    as jobs makes them respect the resources of longer jobs.
    """
    import asyncio

    while job.is_active:
        await asyncio.sleep(interval)
    return job


def _default_run_collection(*args, **kwargs):
    from scilex.pipeline.orchestrator import run_collection

    return run_collection(*args, **kwargs)


def _default_run_aggregation(*args, **kwargs):
    from scilex.pipeline.orchestrator import run_aggregation

    return run_aggregation(*args, **kwargs)


def _mtime(path: Path | None) -> float | None:
    try:
        return path.stat().st_mtime if path is not None else None
    except OSError:
        return None


def _scale(value: float, bounds: tuple[int, int]) -> int:
    low, high = bounds
    return low + int(max(0.0, min(1.0, value)) * (high - low))


class JobRunner:
    """Start, track and cancel jobs; independent jobs run at the same time."""

    def __init__(
        self,
        run_collection: Callable = _default_run_collection,
        run_aggregation: Callable = _default_run_aggregation,
    ):
        """Create a runner; pipeline functions are injectable for tests."""
        self._run_collection = run_collection
        self._run_aggregation = run_aggregation
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        """Return the job with this id, or None."""
        return self._jobs.get(job_id)

    def active_job(self) -> Job | None:
        """Return an active job of the app (the oldest), if any."""
        return next(iter(self.active_jobs()), None)

    def active_jobs(self) -> list[Job]:
        """Every active job, oldest first."""
        jobs = [job for job in self._jobs.values() if job.is_active]
        return sorted(jobs, key=lambda job: job.started_at)

    def recent_jobs(self, within_seconds: float = 900) -> list[Job]:
        """Jobs finished in the last ``within_seconds``, most recent first."""
        now = datetime.now()
        jobs = [
            job
            for job in self._jobs.values()
            if not job.is_active
            and job.finished_at is not None
            and (now - job.finished_at).total_seconds() <= within_seconds
        ]
        return sorted(jobs, key=lambda job: job.finished_at, reverse=True)

    @staticmethod
    def resources_for(
        review: Review, kind: str, resources: list[Resource] | tuple | None = None
    ) -> tuple[Resource, ...]:
        """Resources of a job of ``kind`` on ``review``.

        Without ``resources``, the job rewrites the review's results (``rows``):
        the safe default for an action that did not say what it does.
        """
        declared = (
            tuple(resources)
            if resources is not None
            else (results_resource(review.id, ROWS),)
        )
        return (*declared, (f"job:{kind}:{review.id}", ROWS))

    def conflicting_job(
        self, review: Review, kind: str, resources: list[Resource] | tuple | None = None
    ) -> Job | None:
        """The active job that would refuse this one (None: it can start)."""
        wanted = self.resources_for(review, kind, resources)
        for job in self.active_jobs():
            for name, mode in wanted:
                for other_name, other_mode in job.resources:
                    if name == other_name and conflicts(mode, other_mode):
                        return job
        return None

    def _anonymous_owner(self) -> Job | None:
        """The job that gets the log records of anonymous pipeline threads."""
        active = self.active_jobs()
        collecting = [job for job in active if (COLLECT, EXCLUSIVE) in job.resources]
        if collecting:
            return collecting[0]
        return active[0] if len(active) == 1 else None

    def latest_for(self, review_id: str, kind: str | None = None) -> Job | None:
        """Return the most recent job of a review (of ``kind`` if given), if any."""
        jobs = [
            job
            for job in self._jobs.values()
            if job.review_id == review_id and (kind is None or job.kind == kind)
        ]
        return max(jobs, key=lambda job: job.started_at, default=None)

    def _new_job(
        self,
        review: Review,
        kind: str,
        history_key: str | None = None,
        resources: list[Resource] | tuple | None = None,
    ) -> Job:
        with self._lock:
            blocking = self.conflicting_job(review, kind, resources)
            if blocking is not None:
                raise JobConflictError(
                    f"Cannot start now: {blocking.describe()} is running"
                )
            job = Job(
                id=uuid.uuid4().hex[:12],
                review_id=review.id,
                kind=kind,
                history_key=kind if history_key is None else history_key,
                folder=review.folder,
                results_path=review.results_path,
                results_mtime=_mtime(review.results_path),
                review_name=review.name,
                resources=self.resources_for(review, kind, resources),
            )
            self._jobs[job.id] = job
        return job

    def _start_thread(self, job: Job, body: Callable[[], str]) -> None:
        threading.Thread(
            target=self._execute,
            args=(job, body),
            name=f"scilex-job-{job.id}",
            daemon=True,
        ).start()

    def start_task(
        self,
        review: Review,
        kind: str,
        body: Callable[[Job], str | None],
        *,
        history_key: str | None = None,
        resources: list[Resource] | tuple | None = None,
    ) -> Job:
        """Run ``body(job)`` in a background thread, with log capture.

        ``body`` may update ``job.progress`` (0-100), ``job.message`` and
        ``job.result``, should check ``job.cancel_event`` if it can stop
        early, and returns the completion message (or None).

        Once completed, the run is kept in the review's run history under
        ``history_key`` (default: ``kind``; ``""`` keeps nothing).

        ``resources``: what the job uses (see the module docstring); default:
        it rewrites the review's results.

        Raises:
            JobConflictError: If an active job holds a conflicting resource.
        """
        job = self._new_job(review, kind, history_key, resources)
        self._start_thread(job, lambda: body(job) or "Done.")
        return job

    def start_pipeline(
        self,
        review: Review,
        config: SciLExConfig,
        *,
        skip_citations: bool = False,
        since: str | None = None,
        resume: bool = False,
        fresh: bool = False,
        extend: str | None = None,
    ) -> Job:
        """Run collection then aggregation for ``review`` in a background thread.

        Args:
            review: The review to run.
            config: Its loaded configuration.
            skip_citations: Skip the citation counts in the aggregation.
            since: ``YYYY-MM-DD``; only collect papers since that date
                (like ``scilex-collect --since``).
            resume: Resume the interrupted collection from its saved
                configuration (like ``scilex-collect --resume``).
            fresh: Delete the raw results already collected first, so every
                query is collected again (ignored with ``resume``).
            extend: Extend the review's existing papers instead of replacing
                them: ``"add"`` or ``"reaggregate"`` (see
                :mod:`scilex.gui.services.extend`). Ignored with ``fresh``.

        Raises:
            JobConflictError: If a collection runs, or a job uses this review's results.
            ValueError: If ``since`` is not a valid date.
            FileNotFoundError: If ``resume`` is set but nothing can be resumed.
            ExtensionNeedsGroupError: The review has papers (this is an
                extension) but no Zotero group for their collection.
        """
        from scilex.gui.services import extension_collection
        from scilex.gui.services.collect_summary import (
            clear_collection,
            collection_failure,
            resume_config,
            target_collection_dir,
        )
        from scilex.since_utils import parse_since

        if resume:
            config = resume_config(review.collection_dir, config)
        if since:
            parse_since(since)
            config.main["since"] = since
        clear_dir = target_collection_dir(config) if fresh and not resume else None
        if fresh:
            extend = None
        if extend is not None and extend not in extension.MODES:
            raise ValueError(f"Unknown extension mode {extend!r}")
        # On a review with papers, any collect is an extension: its new papers
        # go into a Zotero collection of the review's group.
        extending = review.has_results
        if extending:
            extension_collection.group_required(review)
        history_key = {
            extension.ADD_NEW: run_history.EXTEND_ADD,
            extension.REAGGREGATE: run_history.EXTEND_REAGGREGATE,
        }.get(extend, run_history.PIPELINE)
        job = self._new_job(
            review,
            PIPELINE,
            history_key,
            [(COLLECT, EXCLUSIVE), results_resource(review.id, ROWS)],
        )

        def body() -> str:
            if clear_dir is not None:
                job.message = "Deleting the previous collection…"
                clear_collection(clear_dir)
            previous = self._snapshot(review) if extending else None
            self._collect(job, config)
            if job.cancel_event.is_set():
                return ""
            collected = any(s.get("articles") for s in job.api_stats.values())
            failure = (
                job.api_stats
                and not collected
                and collection_failure(
                    target_collection_dir(config), job.api_stats, job.logs
                )
            )
            if failure:
                # Aggregating nothing would end "Completed" with an empty review.
                raise CollectionFailedError(failure)
            self._aggregate(job, config, skip_citations)
            summary = self._extend(job, review, extend, previous)
            return summary or "Pipeline completed."

        self._start_thread(job, body)
        return job

    def start_aggregation(
        self,
        review: Review,
        config: SciLExConfig,
        *,
        skip_citations: bool = False,
        keep_outside: bool = False,
    ) -> Job:
        """Aggregate the existing collection of ``review`` with its current config.

        Works on a partial collection and can be replayed after editing
        ``scilex.yml``: nothing is collected again. With ``keep_outside``, papers
        that do not come from the raw collection (imported, snowballed) are kept.

        Raises:
            JobConflictError: If a job uses this review's results.
            ExtensionNeedsGroupError: ``keep_outside`` (an extension) on a
                review without a Zotero group.
        """
        if keep_outside:
            from scilex.gui.services import extension_collection

            extension_collection.group_required(review)
        job = self._new_job(
            review,
            PIPELINE,
            run_history.AGGREGATE,
            [results_resource(review.id, ROWS)],
        )
        mode = extension.REAGGREGATE if keep_outside else None

        def body() -> str:
            previous = self._snapshot(review) if mode else None
            self._aggregate(job, config, skip_citations)
            summary = self._extend(job, review, mode, previous)
            return summary or "Aggregation completed."

        self._start_thread(job, body)
        return job

    @staticmethod
    def _snapshot(review: Review):
        """Read (and back up) the review's results before an extension rewrites them."""
        previous = extension.read_results(review.results_path)
        extension.backup(review.results_path)
        return previous

    @staticmethod
    def _extend(job: Job, review: Review, mode: str | None, previous) -> str:
        from scilex.gui.services.paper_enrich import tag_types

        if job.cancel_event.is_set():
            return ""
        summary = ""
        if mode and previous is not None:
            job.message = "Merging with the papers already in the review…"
            summary = extension.apply_extension(mode, previous, review.results_path)
        tag_types(review.results_path)  # every paper gets its default type
        # Before the new papers are pushed: excluded ones arrive tagged.
        applied = JobRunner._apply_criteria(job, review)
        summary = " ".join(part for part in (summary, applied) if part)
        if previous is not None:
            # Every extension: its new papers go into a Zotero collection.
            from scilex.gui.services import extension_collection

            job.message = "Zotero collection of the new papers…"
            published = extension_collection.publish(
                review,
                extension_collection.paper_keys(previous),
                EXTENSION_LABELS.get(mode, "New collect"),
            )
            summary = f"{summary} {published.message()}".strip()
        if summary:
            logger.info(summary)
        return summary

    @staticmethod
    def _apply_criteria(job: Job, review: Review) -> str:
        """Apply the review's saved eligibility criteria to the new results.

        Excluded papers get ``DELETED_BY:filter:<id> <cause>`` (see
        :func:`scilex.gui.services.criteria.apply`). Nothing happens while the
        criteria were never saved (step Eligibility criteria); a failure is
        reported in the summary and never fails the aggregation.
        """
        from scilex.gui.services import criteria
        from scilex.gui.services.workspace import Workspace

        if job.cancel_event.is_set() or not criteria.path_of(review.folder).is_file():
            return ""
        job.message = "Applying the eligibility criteria…"
        try:
            try:
                main = Workspace.load_config(review).main
            except Exception:
                main = {}
            items = criteria.load(review.folder, main)
            if not any(c.enabled for c in items):
                return ""
            counts = criteria.apply(review, items)
        except Exception as exc:
            logger.warning("Cannot apply the eligibility criteria", exc_info=True)
            return f"The eligibility criteria could not be applied ({exc})."
        excluded = ", ".join(f"{cid} {n}" for cid, n in counts.items() if n)
        return (
            f"Eligibility criteria applied: {excluded} excluded."
            if excluded
            else "Eligibility criteria applied: no paper excluded."
        )

    def cancel(self, job_id: str) -> bool:
        """Request cancellation; returns False if the job is not active.

        Collection stops at the next query; aggregation stops at the next
        stage boundary or LLM request (a long citation fetch finishes first).
        """
        job = self._jobs.get(job_id)
        if job is None or not self._set_status(job, job_states.CANCELLING):
            return False
        job.cancel_event.set()
        job.message = "Cancelling… (stops after the current query or step)"
        return True

    def _set_status(self, job: Job, status: str) -> bool:
        with self._lock:
            if not job_states.transition_allowed(job.status, status):
                return False
            job.status = status
            return True

    @staticmethod
    def _log_papers(job: Job) -> None:
        """Date the papers a completed job added to the review (see paper_log)."""
        if job.folder is None or job.results_path is None:
            return
        if _mtime(job.results_path) in (None, job.results_mtime):
            return  # results not written by this job
        from scilex.gui.services import paper_log

        try:
            paper_log.update_from_file(
                job.folder,
                job.results_path,
                when=datetime.now().date(),
                fresh=job.results_mtime is None,
            )
        except Exception:  # never fail a completed job for its bookkeeping
            logger.warning("Cannot update the paper log", exc_info=True)

    def _finish(self, job: Job, status: str, message: str) -> None:
        if self._set_status(job, status):
            job.message = message
            job.phase = status
            if status == job_states.COMPLETED:
                job.progress = 100
        job.finished_at = datetime.now()

    def _cancelled(self, job: Job) -> bool:
        if not job.cancel_event.is_set():
            return False
        self._finish(job, job_states.CANCELLED, "Cancelled.")
        return True

    def _execute(self, job: Job, body: Callable[[], str]) -> None:
        job.thread_ids.add(threading.get_ident())
        handler = LogLinesHandler(job.logs)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )
        handler.addFilter(
            WorkerThreadFilter(
                job.thread_ids, accept_anonymous=lambda: self._anonymous_owner() is job
            )
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            self._set_status(job, job_states.RUNNING)
            if self._cancelled(job):
                return
            message = body()
            if self._cancelled(job):
                return
            # Saved before the job turns COMPLETED: the page redraws its
            # "last run" chip as soon as it sees the job finished.
            self._remember(job, message)
            self._log_papers(job)
            journal.record_job(job, message)
            self._finish(job, job_states.COMPLETED, message)
        except BaseException as exc:
            # BaseException too: a SystemExit raised by pipeline code must not
            # leave the job RUNNING, which would block every later job.
            error = sanitize_secrets(str(exc) or type(exc).__name__)
            trace = sanitize_secrets("".join(traceback.format_exception(exc)))
            if isinstance(exc, CollectionFailedError):
                logger.error("Job %s (%s) failed: %s", job.id, job.kind, error)
            else:
                logger.error(
                    "Job %s (%s) failed: %s\n%s", job.id, job.kind, error, trace
                )
            job.error = error
            journal.record_job(job, error, failed=True)
            self._finish(job, job_states.FAILED, f"Error: {error}")
        finally:
            root_logger.removeHandler(handler)

    @staticmethod
    def _remember(job: Job, message: str) -> None:
        """Keep a successful job in the review's run history (never fails the job)."""
        if not job.history_key or job.folder is None:
            return
        try:
            run_history.record(job.folder, job.history_key, datetime.now(), message)
        except Exception as exc:
            logger.warning("Cannot save the run history of %s: %s", job.kind, exc)

    def _collect(self, job: Job, config: SciLExConfig) -> None:
        job.phase = "collecting"
        job.progress = COLLECT_RANGE[0]
        job.message = "Collecting papers…"

        def on_progress(api_stats, completed, total):
            job.progress = _scale(completed / max(total, 1), COLLECT_RANGE)
            job.message = f"Collecting papers… {completed}/{total} queries done"
            job.api_stats = {api: dict(stats) for api, stats in api_stats.items()}

        self._run_collection(
            config, progress_callback=on_progress, cancel_event=job.cancel_event
        )

    def _aggregate(self, job: Job, config: SciLExConfig, skip_citations: bool) -> None:
        from scilex.pipeline.orchestrator import (
            SCREENING_PERCENT_RANGE,
            SCREENING_PHASE,
            AggregationCancelled,
            AggregationOptions,
        )

        job.phase = "aggregating"
        job.progress = AGGREGATE_RANGE[0]
        job.message = "Aggregating results…"

        def on_progress(phase, percent, message):
            if phase == SCREENING_PHASE:
                # A sub-step of "filtering": keep the phase list on that step.
                low, high = SCREENING_PERCENT_RANGE
                job.screening_fraction = (percent - low) / (high - low)
            else:
                job.aggregation_phase = phase
                job.screening_fraction = None
            job.progress = _scale(percent / 100, AGGREGATE_RANGE)
            job.message = message

        options = AggregationOptions(
            skip_citations=skip_citations, cancel_event=job.cancel_event
        )
        try:
            self._run_aggregation(config, options, on_progress)
        except AggregationCancelled:
            logger.info("Aggregation cancelled")
