"""Collect screen: run collection + aggregation and follow its progress."""

from nicegui import ui

from scilex.gui.components.dialogs import one_shot_dialog
from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import BusyNotice, JobPanel
from scilex.gui.pages.analyses import render_tabs
from scilex.gui.services import analyses as analyses_service
from scilex.gui.services import extend as extension
from scilex.gui.services.collect_summary import (
    KEYS_HINT,
    api_rows,
    collected_api_dirs,
    detect_resume,
    load_summary,
    phase_steps,
    placeholder_keywords,
    preflight_line,
    target_collection_dir,
)
from scilex.gui.services.jobs import PIPELINE, Job, JobConflictError
from scilex.gui.services.screening import load_decisions
from scilex.gui.services.workspace import Review, Workspace
from scilex.gui.state import AppContext
from scilex.pipeline import jobs as job_states
from scilex.settings.schema import SettingsError
from scilex.since_utils import parse_since

STATE_ICONS = {
    "waiting": "hourglass_empty",
    "running": "sync",
    "done": "check_circle",
    "partial": "warning",
    "failed": "error",
}
STEP_ICONS = {
    "done": "check_circle",
    "current": "autorenew",
    "pending": "radio_button_unchecked",
}


def _show_report(title: str, path) -> None:
    with one_shot_dialog() as dialog, ui.card().classes("w-[48rem] max-w-full"):
        ui.label(title).classes("text-lg font-bold")
        with ui.scroll_area().classes("w-full h-96"):
            ui.markdown(path.read_text(encoding="utf-8"))
        ui.button("Close", on_click=dialog.close)
    dialog.open()


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Collect screen of ``review`` (Extend collect once it has papers)."""
    extending = review.has_results
    if extending:
        ui.label("Extend collect").classes("text-2xl font-bold").mark("extend-title")
        ui.label(
            "The review already has papers. Run the queries of scilex.yml that were "
            "not run yet (new keywords, years or APIs set in ① Configure), or extend "
            "the corpus by snowballing below."
        ).classes("text-gray-500")
    else:
        ui.label("Collect").classes("text-2xl font-bold")
        ui.label(
            "Query the APIs listed in scilex.yml, then deduplicate, filter and rank "
            "the papers."
        ).classes("text-gray-500")

    # Pre-flight: validate scilex.yml before offering to run.
    with ui.column().classes("gap-1"):
        try:
            preflight_text = preflight_line(
                Workspace.load_config(review), review.config_path
            )
            ui.label(preflight_text).classes("text-sm").mark("preflight")
            placeholders = placeholder_keywords(Workspace.load_config(review))
            if placeholders:
                with ui.row().classes("items-center gap-2"):
                    ui.label(
                        "Keywords still look like the template's examples: "
                        + ", ".join(placeholders)
                    ).classes("text-sm text-warning").mark("placeholder-warning")
                    ui.button(
                        "Fix in ① Configure",
                        icon="tune",
                        on_click=lambda: ui.navigate.to(
                            f"/review/{review.id}/configure"
                        ),
                    ).props("outline dense").mark("fix-placeholders")
        except (SettingsError, FileNotFoundError) as exc:
            ui.label(str(exc)).classes("text-negative whitespace-pre-wrap").mark(
                "preflight-error"
            )
            ui.button(
                "Fix in ① Configure",
                icon="tune",
                on_click=lambda: ui.navigate.to(f"/review/{review.id}/configure"),
            ).props("outline").mark("fix-config")
        except Exception as exc:
            show_error("Cannot read the configuration", exc)

    with ui.row().classes("items-center gap-4"):
        skip_citations = ui.checkbox("Skip citation counts (faster)").mark(
            "skip-citations"
        )
        since_input = (
            ui.input("Only papers since", placeholder="YYYY-MM-DD")
            .props("dense clearable")
            .mark("since")
        )
    if load_decisions(review):
        ui.label(
            "Decisions are kept; papers that are no longer in the new results "
            "will appear as orphans in ④ Screen."
        ).classes("text-sm text-gray-600").mark("screening-kept-notice")
    busy_notice = BusyNotice(ctx)
    with ui.row().classes("items-center gap-4"):
        if extending:
            run_button = ui.button("Add new papers", icon="playlist_add").mark(
                "extend-add"
            )
            with run_button:
                busy_tooltip = ui.tooltip("Another job is running")
            reaggregate_button = (
                ui.button("Re-aggregate everything", icon="sync")
                .props("outline")
                .mark("extend-reaggregate")
            )
            start_over_button = (
                ui.button("Start over", icon="restart_alt")
                .props("outline color=negative")
                .mark("run")
            )
        else:
            run_button = ui.button("Run", icon="play_arrow").mark("run")
            with run_button:
                busy_tooltip = ui.tooltip("Another job is running")
            reaggregate_button = start_over_button = None
        resume_button = (
            ui.button("Resume interrupted collection", icon="replay")
            .props("outline")
            .mark("resume")
        )
        aggregate_button = (
            ui.button("Aggregate existing results", icon="filter_alt")
            .props("outline")
            .mark("aggregate-only")
        )
        cancel_button = (
            ui.button("Cancel", icon="stop")
            .props("outline color=negative")
            .mark("cancel")
        )
    resume_hint = ui.label().classes("text-sm text-gray-500")
    if extending:
        ui.markdown(
            "- **Add new papers**: keeps the papers of the review (and their ranking "
            "and screening) as they are and appends the new ones only.\n"
            "- **Re-aggregate everything**: deduplicates, filters and ranks the whole "
            "collection again; imported and snowballed papers are kept.\n"
            "- **Start over**: deletes the raw results and collects every query again.\n\n"
            "The previous results are saved in `previous_results/` first."
        ).classes("text-sm text-gray-600").mark("extend-help")
    ui.label(
        "Aggregate existing results re-runs deduplication, filters and ranking on "
        "what is already collected (even a partial collection) with the current "
        "scilex.yml; nothing is collected again."
    ).classes("text-sm text-gray-500")

    # The resume state needs a disk scan: compute it at render and when a job
    # finishes, never on the 0.5 s tick of the job panel.
    resume_cache = {"info": detect_resume(review.collection_dir)}

    def has_collection() -> bool:
        return (review.collection_dir / "config_used.yml").is_file()

    def update_buttons(job: Job | None) -> None:
        running = job is not None and job.is_active
        busy_elsewhere = not running and ctx.runner.active_job() is not None
        run_button.set_enabled(not running and not busy_elsewhere)
        for extra in (reaggregate_button, start_over_button):
            if extra is not None:
                extra.set_enabled(not running and not busy_elsewhere)
        # One tooltip, shown or hidden: calling .tooltip() here would add a new one every tick.
        busy_tooltip.set_visibility(busy_elsewhere)
        busy_notice.update(job)
        aggregate_button.set_visibility(not running and has_collection())
        aggregate_button.set_enabled(not busy_elsewhere)
        cancel_button.set_visibility(running)
        resume_info = None if running else resume_cache["info"]
        resume_button.set_visibility(resume_info is not None)
        resume_button.set_enabled(not busy_elsewhere)
        resume_hint.set_visibility(resume_info is not None)
        if resume_info is not None:
            partly = (
                f" ({resume_info.partial} partly collected, fetched again)"
                if resume_info.partial
                else ""
            )
            resume_hint.text = (
                f"The last collection stopped at {resume_info.done}/"
                f"{resume_info.total} finished queries{partly}; resuming skips "
                "the finished ones."
            )

    def on_job_finished(job: Job) -> None:
        resume_cache["info"] = detect_resume(review.collection_dir)
        update_buttons(job)

    panel = JobPanel(
        ctx,
        review,
        PIPELINE,
        on_change=update_buttons,
        on_finished=on_job_finished,
    )
    refresh = panel.refresh

    # --- live details: API table and aggregation phases -------------------
    api_container = ui.column().classes("w-full gap-1")
    phase_container = ui.column().classes("gap-0")
    screening_label = ui.label().classes("text-sm").mark("screening-label")
    screening_bar = (
        ui.linear_progress(value=0, show_value=False)
        .classes("w-full")
        .mark("screening-bar")
    )
    screening_label.set_visibility(False)
    screening_bar.set_visibility(False)
    shown: dict = {}

    def update_details(job: Job | None) -> None:
        if job is None:
            return
        rows = api_rows(job.api_stats, job.logs, job.status, job.is_active)
        if shown.get("rows") != (job.id, rows):
            shown["rows"] = (job.id, rows)
            api_container.clear()
            if rows:
                with api_container:
                    ui.table(
                        columns=[
                            {
                                "name": "api",
                                "label": "API",
                                "field": "api",
                                "align": "left",
                            },
                            {"name": "queries", "label": "Queries", "field": "queries"},
                            {"name": "papers", "label": "Papers", "field": "papers"},
                            {"name": "errors", "label": "Errors", "field": "errors"},
                            {
                                "name": "state",
                                "label": "State",
                                "field": "state",
                                "align": "left",
                            },
                        ],
                        rows=[
                            {
                                "api": row.api,
                                "queries": f"{row.queries_done}/{row.queries_total}",
                                "papers": row.papers,
                                "errors": row.errors,
                                "state": row.state
                                + (f": {row.reason}" if row.reason else ""),
                            }
                            for row in rows
                        ],
                        row_key="api",
                    ).props("dense flat wrap-cells").classes("w-full").mark("api-table")
        if not job.is_active and shown.get("finished") != job.id:
            shown["finished"] = job.id
            show_failure.refresh()
            show_summary.refresh()
        screening = job.is_active and job.screening_fraction is not None
        screening_label.set_visibility(screening)
        screening_bar.set_visibility(screening)
        if screening:
            screening_bar.value = job.screening_fraction
            screening_label.text = job.message
        aggregating = job.phase == "aggregating" or job.aggregation_phase is not None
        finished = job.status == job_states.COMPLETED
        steps = (
            phase_steps(job.aggregation_phase, finished)
            if aggregating or finished
            else []
        )
        if shown.get("steps") != (job.id, steps):
            shown["steps"] = (job.id, steps)
            phase_container.clear()
            with phase_container:
                for label, state in steps:
                    with ui.row().classes("items-center gap-2"):
                        ui.icon(STEP_ICONS[state])
                        ui.label(label).classes("text-sm")

    # --- failure and completion summary ------------------------------------
    @ui.refreshable
    def show_failure() -> None:
        # The job panel shows the error and the log; add the fix when there is one.
        job = panel.job
        if job is None or job.status != job_states.FAILED:
            return
        if KEYS_HINT in (job.error or ""):
            ui.button(
                "Open API keys",
                icon="key",
                on_click=lambda: ui.navigate.to(f"/review/{review.id}/keys"),
            ).props("outline").mark("open-keys")

    @ui.refreshable
    def show_summary() -> None:
        summary = load_summary(review.collection_dir)
        if summary is None:
            return
        ui.label("Last results").classes("text-lg font-bold")
        with ui.row().classes("gap-6").mark("summary"):
            for label, value in (
                ("Collected", summary.collected),
                ("After deduplication", summary.after_dedup),
                ("Kept", summary.kept),
            ):
                with ui.column().classes("gap-0"):
                    ui.label("-" if value is None else f"{value:,}").classes("text-xl")
                    ui.label(label).classes("text-xs text-gray-500")
        partial = resume_cache["info"]
        if partial is not None:
            ui.label(
                f"Partial collection: {partial.done}/{partial.total} queries "
                "finished. These numbers cover only what was collected; use "
                "Resume to collect the rest."
            ).classes("text-sm text-warning").mark("summary-partial")
        with ui.row():
            if summary.prisma_report:
                ui.button(
                    "PRISMA report",
                    icon="description",
                    on_click=lambda: _show_report(
                        "PRISMA report", summary.prisma_report
                    ),
                ).props("outline").mark("prisma-report")
            if summary.aggregation_report:
                ui.button(
                    "Aggregation report",
                    icon="description",
                    on_click=lambda: _show_report(
                        "Aggregation report", summary.aggregation_report
                    ),
                ).props("outline").mark("aggregation-report")

    show_failure()
    show_summary()
    # Details are drawn after the panel, so hook them in once they exist.
    panel.on_change = lambda job: (update_buttons(job), update_details(job))
    panel.refresh()

    def start(
        *, resume: bool, confirmed: bool = False, extend: str | None = None
    ) -> None:
        since = (since_input.value or "").strip() or None
        try:
            if since:
                parse_since(since)
        except ValueError as exc:
            show_error(
                "Invalid date", ValueError(f"Use YYYY-MM-DD ({exc})"), expected=True
            )
            return
        try:
            config = Workspace.load_config(review)
            if not resume and not confirmed and extend is None:
                previous = collected_api_dirs(target_collection_dir(config, since))
                if previous:
                    confirm_fresh_run(previous)
                    return
            ctx.runner.start_pipeline(
                review,
                config,
                skip_citations=skip_citations.value,
                since=since,
                resume=resume,
                fresh=not resume and extend is None,
                extend=extend,
            )
        except (SettingsError, FileNotFoundError, JobConflictError) as exc:
            show_error("Cannot start the collection", exc, expected=True)
        except Exception as exc:
            show_error("Cannot start the collection", exc)
        show_failure.refresh()
        refresh()

    def confirm_fresh_run(previous: list) -> None:
        """Ask before Run deletes the raw results of the previous collection."""
        names = ", ".join(path.name for path in previous)
        with one_shot_dialog() as dialog, ui.card().mark("fresh-confirm"):
            ui.label("Start the collection from zero?").classes("text-lg")
            ui.label(
                f"The raw results already collected ({names}) will be deleted "
                "and every query collected again. The previous aggregated "
                "results and reports are moved to previous_results/; screening "
                "decisions are kept. To continue an interrupted collection "
                "instead, use Resume."
            )
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat").mark(
                    "fresh-cancel"
                )

                def go() -> None:
                    dialog.close()
                    start(resume=False, confirmed=True)

                ui.button("Delete and run", on_click=go).props("color=negative").mark(
                    "fresh-run"
                )
        dialog.open()

    def aggregate_only() -> None:
        try:
            ctx.runner.start_aggregation(
                review,
                Workspace.load_config(review),
                skip_citations=skip_citations.value,
                keep_outside=extending,
            )
        except (SettingsError, FileNotFoundError, JobConflictError) as exc:
            show_error("Cannot start the aggregation", exc, expected=True)
        except Exception as exc:
            show_error("Cannot start the aggregation", exc)
        show_failure.refresh()
        refresh()

    def cancel() -> None:
        job = panel.job
        if job is not None:
            ctx.runner.cancel(job.id)
        refresh()

    if extending:
        run_button.on_click(lambda: start(resume=False, extend=extension.ADD_NEW))
        reaggregate_button.on_click(
            lambda: start(resume=False, extend=extension.REAGGREGATE)
        )
        start_over_button.on_click(lambda: start(resume=False))
    else:
        run_button.on_click(lambda: start(resume=False))
    resume_button.on_click(lambda: start(resume=True))
    aggregate_button.on_click(aggregate_only)
    cancel_button.on_click(cancel)

    if extending:
        ui.separator()
        ui.label("Extend the corpus").classes("text-lg font-bold")
        render_tabs(ctx, review, analyses_service.in_group("extend"))
