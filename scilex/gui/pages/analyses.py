"""Analyses screen: one tab per analysis of the collected papers."""

from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.graph_view import render_graph_results
from scilex.gui.components.job_panel import JobPanel
from scilex.gui.components.run_status import RunStatus, set_tab_dot, state_of
from scilex.gui.components.tag_tools import render_tag_tools
from scilex.gui.services import analyses as service
from scilex.gui.services import run_history, screening
from scilex.gui.services.jobs import Job, JobConflictError, results_resource
from scilex.gui.services.workspace import Review, Workspace
from scilex.gui.state import AppContext
from scilex.settings.schema import SettingsError

TABLE_ROWS_SHOWN = 200
TEXT_SUFFIXES = {".md": "markdown", ".yml": "yaml", ".yaml": "yaml"}
DIRECTIONS = {
    "both": "References and citing papers",
    "backward": "References only (cited by the corpus)",
    "forward": "Citing papers only",
}


ONLY_KEPT = "only_kept"
CITATION_SOURCES = {
    "auto": "Semantic Scholar, then CrossRef, then OpenCitations",
    "crossref": "CrossRef (references) + OpenCitations",
    "opencitations": "OpenCitations only (open data, no key)",
    "zotero": "Zotero snapshot (frozen: the citation notes of the review's library)",
}


def kept_papers_filter(review: Review) -> Callable:
    """Row filter keeping the papers included (or maybe) in screening.

    Raises:
        service.AnalysisError: If no paper is kept yet.
    """
    kept = {
        key
        for key, decision in screening.load_decisions(review).items()
        if decision.decision in (screening.INCLUDE, screening.MAYBE)
    }
    if not kept:
        raise service.AnalysisError(
            'No paper is kept in ③ Screen yet: untick "Only the papers kept" '
            "or screen first."
        )

    def keep(data):
        return data[data.apply(screening.paper_key, axis=1).isin(kept)]

    return keep


def _snowball_seed_options(review, select, checkbox, stored: dict) -> None:
    """Seeds of the snowballing: Zotero collections, paper types, eligibility."""
    from scilex.gui.services import snowball_scope
    from scilex.paper_types import TYPES

    collections: list[str] = []
    if review is not None:
        try:
            from scilex.gui.services.extend import read_results

            collections = snowball_scope.collection_options(
                read_results(review.results_path)
            )
        except Exception:  # unreadable results: no collection choices
            collections = []
    collections = sorted(set(collections) | set(stored.get("collections") or []))
    ui.label(
        "Seeds: the corpus papers to start from (empty = all). A collection "
        "includes its sub-collections; candidates already in the review are "
        "never added again."
    ).classes("text-xs text-gray-600")
    with ui.row().classes("items-center gap-4 w-full"):
        select(
            "collections",
            "Zotero collections",
            collections,
            [],
            multiple=True,
            with_input=True,
            clearable=True,
        )
        select("paper_types", "Paper types", list(TYPES), [], multiple=True)
        checkbox("eligible_only", "Only papers meeting the eligibility criteria")


def kind_of(name: str) -> str:
    """Job kind of analysis ``name``."""
    return f"analysis-{name}"


def _job_label(job: Job) -> str:
    """Human name of a job: the analysis title, else what the job says it is."""
    prefix = "analysis-"
    if job.kind.startswith(prefix):
        for info in service.ANALYSES:
            if info.name == job.kind[len(prefix) :]:
                return f"{info.title} on {job.review_name or job.review_id}"
    return job.describe()


def resources_of(review: Review, name: str, options: dict) -> list:
    """Resources of analysis ``name`` with these (normalised) options."""
    return [results_resource(review.id, service.results_mode(name, options))]


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Analyses screen of ``review``."""
    ui.label("Analyses").classes("text-2xl font-bold")
    ui.label(
        "Explore the corpus: charts, citation graph and communities. "
        "Citation data comes from ⑥ Enrich."
    ).classes("text-gray-500")
    render_tabs(ctx, review, service.in_group("analyse"))


def render_tabs(
    ctx: AppContext, review: Review, analyses: tuple[service.AnalysisInfo, ...]
) -> None:
    """Draw one tab per analysis of ``analyses`` (shared by Enrich, Extend and Analyses).

    Each tab carries a dot coloured by its last run (see
    :mod:`scilex.gui.components.run_status`), so a costly action already done
    is visible without opening its tab.
    """
    history = run_history.load(review.folder)
    tab_items: dict[str, ui.tab] = {}
    with ui.tabs().classes("w-full").props("mobile-arrows outside-arrows") as tabs:
        for info in analyses:
            tab = ui.tab(info.name, label=info.title).mark(f"analysis-tab-{info.name}")
            set_tab_dot(tab, state_of(review, kind_of(info.name), history)[1])
            tab_items[info.name] = tab
    # Finishing one analysis (e.g. Citations) can lift another tab's warning.
    problem_refreshers: list[Callable[[], None]] = []
    infos = {info.name: info for info in analyses}
    tab_containers: dict[str, ui.tab_panel] = {}
    panels: dict[str, JobPanel] = {}
    first = analyses[0].name
    with ui.tab_panels(tabs, value=first).classes("w-full min-w-0") as tab_panels:
        for name in infos:
            tab_containers[name] = ui.tab_panel(name)

    def show_tab(name: str) -> None:
        # A tab is drawn when first opened, and only the visible tab polls its
        # job: six panels ticking every 0.5 s cost more than the page itself.
        if name not in panels:
            with tab_containers[name]:
                panels[name] = _render_analysis(
                    ctx,
                    review,
                    infos[name],
                    problem_refreshers,
                    on_run_recorded=lambda fresh, tab=tab_items[name]: set_tab_dot(
                        tab, fresh
                    ),
                )
        for other, panel in panels.items():
            panel.timer.active = other == name
            if other == name:
                panel.refresh()

    show_tab(first)
    tab_panels.on_value_change(lambda event: show_tab(event.value))


def _run_crossref_first(ctx: AppContext, review: Review) -> None:
    """Start the Crossref enrichment (fills empty abstracts) from another tab."""
    try:
        config = Workspace.load_config(review)

        def body(job: Job) -> str:
            def progress(percent: int, message: str) -> None:
                job.progress, job.message = percent, message

            result = service.RUNNERS["crossref"](
                config, progress, cancel_event=job.cancel_event
            )
            job.result = result
            return result.message

        ctx.runner.start_task(
            review,
            kind_of("crossref"),
            body,
            resources=resources_of(review, "crossref", {}),
        )
    except (SettingsError, FileNotFoundError, JobConflictError) as exc:
        show_error("Cannot run Crossref now", exc, expected=True)
        return
    ui.notify(
        "Crossref is filling the empty abstracts (progress in ⑥ Enrich > Crossref, "
        "and in the jobs list). Run the keywords once it is done.",
        type="info",
        multi_line=True,
    )


def _render_analysis(
    ctx: AppContext,
    review: Review,
    info: service.AnalysisInfo,
    problem_refreshers: list[Callable[[], None]],
    on_run_recorded: Callable[[str], None] | None = None,
) -> JobPanel:
    name = info.name
    ui.label(info.description).classes("text-gray-500")
    collect_dir = review.collection_dir

    @ui.refreshable
    def show_problem() -> None:
        problem = service.missing_prerequisite(collect_dir, info.needs)
        if problem:
            ui.label(problem).classes("text-orange-700").mark(
                f"analysis-missing-{name}"
            )

    show_problem()
    problem_refreshers.append(show_problem.refresh)
    if name in ("search_keywords", "keywords"):
        gap = service.abstract_gap(collect_dir)
        if gap:
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.label(gap).classes("text-sm text-orange-700").mark(
                    f"analysis-abstracts-{name}"
                )
                ui.button(
                    "Run Crossref first",
                    icon="auto_awesome",
                    on_click=lambda: _run_crossref_first(ctx, review),
                ).props("outline dense no-caps").mark(f"analysis-crossref-first-{name}")

    options = _render_options(name, review)
    reason_label = (
        ui.label("").classes("text-orange-700").mark(f"analysis-reason-{name}")
    )
    reason_label.set_visibility(False)

    with ui.row().classes("items-center gap-2"):
        run_button = ui.button("Run", icon="play_arrow").mark(f"analysis-run-{name}")
        with run_button:
            busy_tooltip = ui.tooltip("A job using the same data is running")
        cancel_button = (
            ui.button("Cancel", icon="stop")
            .props("outline color=negative")
            .mark(f"analysis-cancel-{name}")
        )
        with cancel_button:
            ui.tooltip(info.cancel_note)
        run_status = RunStatus(review, kind_of(name))

    result_area = ui.column().classes("w-full")

    def show_result(
        message: str, files: list[Path], warning: str | None = None
    ) -> None:
        result_area.clear()
        with result_area:
            if message:
                ui.label(message).classes("font-bold").mark(f"analysis-message-{name}")
            if warning:
                ui.label(warning).classes("text-orange-700").mark(
                    f"analysis-stale-{name}"
                )
            if name == "graph":
                # The graph files are drawn as a network, not listed one by one.
                render_graph_results(service.graph_dir_of(collect_dir), review)
                return
            for path in files:
                _render_file(path)
            if name == "tags":
                render_tag_tools(ctx, review, collect_dir)

    def show_existing() -> None:
        files = service.existing_outputs(collect_dir, name)
        if files:
            show_result(
                "Previous results:",
                files,
                service.stale_warning(collect_dir, name, files),
            )

    shown_job: list[str] = []

    def update_buttons(job: Job | None) -> None:
        running = job is not None and job.is_active
        # Show a finished job's result once (a fast job may end between two ticks).
        if (
            job is not None
            and not running
            and job.id not in shown_job
            and isinstance(job.result, service.AnalysisResult)
        ):
            shown_job.append(job.id)
            show_result(job.result.message, job.result.files)
        try:
            current = service.normalize_options(
                name, {key: widget.value for key, widget in options.items()}
            )
        except (TypeError, ValueError):
            current = {}
        # Only a job that really conflicts (e.g. a collection rewriting this
        # review's results) blocks this analysis; others run alongside.
        active = (
            None
            if running
            else ctx.runner.conflicting_job(
                review, kind_of(name), resources_of(review, name, current)
            )
        )
        busy_elsewhere = active is not None
        missing = service.missing_prerequisite(collect_dir, info.needs)
        run_button.set_enabled(not running and not busy_elsewhere and not missing)
        # One tooltip, shown or hidden: calling .tooltip() here would add one per tick.
        busy_tooltip.set_visibility(busy_elsewhere)
        # A missing input is already explained by the line above the options.
        if busy_elsewhere:
            reason_label.set_text(f"Waiting for: {_job_label(active)}")
        reason_label.set_visibility(busy_elsewhere)
        cancel_button.set_visibility(running)

    def on_finished(job: Job) -> None:
        for refresh_problem in problem_refreshers:
            refresh_problem()
        fresh = run_status.update()
        if on_run_recorded is not None:
            on_run_recorded(fresh)

    panel = JobPanel(
        ctx,
        review,
        kind_of(name),
        on_change=update_buttons,
        on_finished=on_finished,
    )
    show_existing()

    def cancel() -> None:
        job = panel.job
        if job is not None:
            ctx.runner.cancel(job.id)

    cancel_button.on_click(cancel)

    def run() -> None:
        title = f"Cannot run {info.title}"
        try:
            missing = service.missing_prerequisite(collect_dir, info.needs)
            if missing:
                raise service.AnalysisError(missing)
            config = Workspace.load_config(review)
            kwargs = service.normalize_options(
                name, {key: widget.value for key, widget in options.items()}
            )
            if name in service.SCOPED and options[ONLY_KEPT].value:
                kwargs["row_filter"] = kept_papers_filter(review)
            if name == "tags":
                kwargs["review_folder"] = review.folder
            if name in ("citations", "snowball"):
                kwargs["review"] = review

            def body(job: Job) -> str:
                def progress(percent: int, message: str) -> None:
                    job.progress = percent
                    job.message = message

                result = service.RUNNERS[name](
                    config, progress, cancel_event=job.cancel_event, **kwargs
                )
                job.result = result
                return result.message

            # A dry run writes nothing: it must not look like a finished run.
            dry_run = "dry_run" in options and options["dry_run"].value
            ctx.runner.start_task(
                review,
                kind_of(name),
                body,
                history_key="" if dry_run else None,
                resources=resources_of(review, name, kwargs),
            )
            # Disable at once: the panel timer would leave a double-click window.
            run_button.set_enabled(False)
        except (
            SettingsError,
            FileNotFoundError,
            JobConflictError,
            service.AnalysisError,
        ) as exc:
            show_error(title, exc, expected=True)
        except Exception as exc:
            show_error(title, exc)

    run_button.on_click(run)
    return panel


def _render_options(name: str, review: Review | None = None) -> dict:
    """Draw the option widgets of analysis ``name``; keys match the runner's kwargs.

    Snowballing settings are stored in the review (``snowball.yml``): the
    widgets start from them and every change is saved.
    """
    from scilex.gui.services import snowball_scope

    widgets: dict = {}
    stored = (
        snowball_scope.load(review.folder)
        if name == "snowball" and review is not None
        else {}
    )

    def number(key: str, label: str, value: float, **props) -> None:
        widgets[key] = ui.number(label, value=stored.get(key, value), **props).mark(
            f"analysis-opt-{name}-{key}"
        )

    def select(key: str, label: str, choices, value, **kwargs) -> None:
        widgets[key] = ui.select(
            choices, label=label, value=stored.get(key, value), **kwargs
        ).mark(f"analysis-opt-{name}-{key}")

    def checkbox(key: str, label: str, value: bool = False) -> None:
        widgets[key] = ui.checkbox(label, value=stored.get(key, value)).mark(
            f"analysis-opt-{name}-{key}"
        )

    if name in service.SCOPED:
        checkbox(ONLY_KEPT, "Only the papers kept in ③ Screen (included or maybe)")
    with ui.row().classes("items-center gap-4"):
        if name in ("keywords", "summaries"):
            select("clusters", "Clusters", service.CLUSTER_CHOICES, "auto")
        if name in ("report", "coverage", "tags", "summaries"):
            from scilex.gui.services.compare import COMPARE_BY, PAPER_TYPE

            select("compare_by", "Compare by", COMPARE_BY, PAPER_TYPE)
        if name == "keywords":
            number("top_k", "Max suggestions", 30, min=1, precision=0)
            number("min_freq", "Min frequency", 2, min=1, precision=0)
        elif name == "enrich":
            checkbox("dry_run", "Dry run (do not write the CSV)")
            number("limit", "Max papers (0 = all)", 0, min=0, precision=0)
            number("threshold", "Title match threshold (0-100)", 85, min=0, max=100)
        elif name == "tags":
            checkbox(
                "from_zotero",
                "Read the tags from Zotero now (else: as of the last import)",
            )
            number(
                "max_dimensions", "Dimensions to cross", 5, min=2, max=12, precision=0
            )
            number(
                "similarity",
                "Merge suggestions: min similarity (0-100)",
                88,
                min=50,
                max=100,
            )
        elif name in ("crossref", "lpwc", "orkg", "github", "zenodo"):
            number("limit", "Max papers (0 = all)", 0, min=0, precision=0)
            if name == "zenodo":
                checkbox(
                    "datasets_only", "Only the dataset papers (PAPER_TYPE:Dataset)"
                )
        elif name == "metrics":
            checkbox("tags", "Also as tags (CITATIONS:10^2, PAGERANK:top5%…)", True)
        elif name == "citations":
            select("source", "Source", CITATION_SOURCES, "auto")
            number("limit", "Max papers (0 = all)", 0, min=0, precision=0)
            checkbox("skip_citers", "Skip citing papers (references only)")
            checkbox(
                "no_fallback",
                "Semantic Scholar only (skip the OpenCitations fallback)",
            )
        elif name == "snowball":
            select("direction", "Direction", DIRECTIONS, "both")
            number("top_k", "Max candidates", 200, min=1, precision=0)
            number("min_frequency", "Min corpus links", 2, min=1, precision=0)
            checkbox("dry_run", "Dry run (list candidates only)")
            checkbox(
                "add_to_collection",
                "Add to the collection (otherwise aggregated_results_snowball.csv)",
                value=True,
            )
    if name == "snowball":
        _snowball_seed_options(review, select, checkbox, stored)
        if review is not None:

            def store(_=None) -> None:
                settings = {
                    key: widget.value
                    for key, widget in widgets.items()
                    if key in snowball_scope.KEYS
                }
                try:
                    snowball_scope.save(review.folder, settings)
                except OSError as exc:
                    show_error("Cannot save the snowballing settings", exc)

            for key, widget in widgets.items():
                if key in snowball_scope.KEYS:
                    widget.on_value_change(store)
        elif name == "graph":
            select(
                "graph_type",
                "Graph",
                {
                    "cocitation": "Co-citation",
                    "coupling": "Bibliographic coupling",
                    "both": "Both",
                },
                "cocitation",
            )
            number("resolution", "Resolution (higher = more clusters)", 1.0, min=0.1)
            number("min_weight", "Min edge weight", 1, min=1, precision=0)
            select("fmt", "Export format", ["gexf", "graphml"], "gexf")
    return widgets


def _render_file(path: Path) -> None:
    """Show one output file according to its type."""
    ui.label(path.name).classes("text-xs text-gray-500").tooltip(str(path))
    suffix = path.suffix.lower()
    try:
        if suffix == ".png":
            data = base64.b64encode(path.read_bytes()).decode()
            ui.image(f"data:image/png;base64,{data}").classes("max-w-3xl")
        elif suffix == ".md":
            # "mermaid" draws the ```mermaid blocks (cluster mindmap) as diagrams.
            ui.markdown(
                path.read_text(encoding="utf-8"),
                extras=["fenced-code-blocks", "tables", "mermaid"],
            ).classes("w-full")
        elif suffix in (".yml", ".yaml"):
            ui.code(path.read_text(encoding="utf-8"), language="yaml").classes("w-full")
        elif suffix == ".csv":
            _render_csv(path)
    except Exception as exc:  # a broken file must not break the whole screen
        ui.label(f"Cannot display this file: {exc}").classes("text-red-700")


def _render_csv(path: Path) -> None:
    try:
        frame = service.read_result_csv(path, nrows=TABLE_ROWS_SHOWN).fillna("")
    except ValueError:
        ui.label("This table cannot be displayed (unreadable CSV).").classes(
            "text-sm text-orange-700"
        )
        return
    columns = [{"name": c, "label": c, "field": c} for c in frame.columns[:12]]
    rows = frame[[c["name"] for c in columns]].to_dict("records")
    ui.table(columns=columns, rows=rows).classes("w-full overflow-x-auto").props(
        "dense"
    )
