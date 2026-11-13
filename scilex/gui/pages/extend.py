"""Extend screen: add papers to a review that already has some.

One tab per way of extending the corpus:

- **New collect**: the queries of scilex.yml not run yet (add new papers only,
  or re-aggregate everything); the Collect step of a review with papers;
- **Snowballing**: papers often cited by, or citing, the corpus;
- **Keyword suggestions**: new search keywords from the paper clusters;
- **BibTeX**: the papers of a .bib file;
- **Zotero**: the papers of another Zotero library or collection.

Each extension that adds papers goes into a collection of the review's
Zotero group, a new one by default (see
:mod:`scilex.gui.services.extension_collection`); without a group, the
review cannot be extended.
"""

from nicegui import events, run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import JobPanel
from scilex.gui.components.review_group import group_problem
from scilex.gui.components.run_status import RunStatus
from scilex.gui.components.zotero_picker import ZoteroPicker
from scilex.gui.pages import collect
from scilex.gui.services import analyses as analyses_service
from scilex.gui.services import (
    bibtex_import,
    extension_collection,
    zotero_extend,
    zotero_library,
)
from scilex.gui.services.jobs import (
    ROWS,
    Job,
    JobConflictError,
    results_resource,
    wait_for,
)
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext

NEW_COLLECT, SNOWBALL, KEYWORDS, BIBTEX, ZOTERO = (
    "new-collect",
    "snowball",
    "keywords",
    "bibtex",
    "zotero",
)
TABS = {
    NEW_COLLECT: ("New collect", "travel_explore"),
    SNOWBALL: ("Snowballing", "hub"),
    KEYWORDS: ("Keyword suggestions", "lightbulb"),
    BIBTEX: ("BibTeX import", "upload_file"),
    ZOTERO: ("Zotero", "library_add"),
}


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Extend screen of ``review``: one tab per kind of extension."""
    ui.label("Extend").classes("text-2xl font-bold").mark("extend-title")
    ui.label(
        "Add papers to the review. Choose how: a new collect, snowballing through "
        "citations, a BibTeX file or another Zotero library. Each extension gets "
        "its own collection in the review's Zotero group."
    ).classes("text-gray-500")
    problem = group_problem(review)
    if problem:
        # Every extension goes into a Zotero collection of the review's group.
        with ui.row().classes("items-center gap-2 no-wrap").mark("extend-no-group"):
            ui.icon("block").classes("text-negative")
            ui.label(
                problem + " Every extension goes into a Zotero collection of the "
                "review's group: choose the group before extending the review."
            ).classes("text-sm")
            ui.button(
                "Zotero group",
                icon="groups",
                on_click=lambda: ui.navigate.to(f"/review/{review.id}/group"),
            ).props("flat dense no-caps")
        return
    _target_card(review)
    with ui.tabs().classes("w-full").props("align=left") as tabs:
        for key, (label, icon) in TABS.items():
            ui.tab(key, label=label, icon=icon).mark(f"extend-tab-{key}")
    analyses = {info.name: info for info in analyses_service.in_group("extend")}
    drawn: set[str] = set()
    with ui.tab_panels(tabs, value=NEW_COLLECT).classes("w-full min-w-0") as panels:
        containers = {key: ui.tab_panel(key) for key in TABS}

    def show(key: str) -> None:
        # Drawn when first opened: each tab polls its own jobs.
        if key in drawn:
            return
        drawn.add(key)
        with containers[key]:
            if key == NEW_COLLECT:
                collect.render(ctx, review, extending=True)
            elif key in (SNOWBALL, KEYWORDS):
                from scilex.gui.pages.analyses import _render_analysis

                _render_analysis(ctx, review, analyses[key], [])
            elif key == BIBTEX:
                _bibtex_card(ctx, review)
            else:
                _zotero_card(ctx, review)

    panels.on_value_change(lambda event: show(event.value))
    show(NEW_COLLECT)


NEW_TARGET, EXISTING_TARGET = "new", "existing"


def _target_card(review: Review) -> None:
    """Zotero collection of the next extensions: a new one (default) or an existing one.

    The choice is saved for the background jobs (new collect, snowballing) and
    goes back to a new collection each time the page opens.
    """
    extension_collection.save_target(review, extension_collection.Target())
    collections: dict[str, str] = {}  # key -> path

    def save() -> None:
        if mode.value == EXISTING_TARGET:
            key = existing.value
            target = (
                extension_collection.Target(key=key, path=collections[key])
                if key in collections
                else extension_collection.Target()  # nothing chosen yet
            )
        else:
            target = extension_collection.Target(name=(name.value or "").strip())
        extension_collection.save_target(review, target)

    async def load() -> None:
        loading.visible = True
        try:
            found = await run.io_bound(
                extension_collection.candidate_collections, review
            )
        except Exception as exc:
            show_error("Cannot list the Zotero collections", exc, expected=True)
            return
        finally:
            loading.visible = False
        collections.clear()
        collections.update({c.key: c.path for c in found})
        existing.set_options(
            {c.key: f"{c.path} ({c.num_items})" for c in found}, value=None
        )
        if not found:
            ui.notify("The review's Zotero group has no collection yet", type="info")

    async def on_mode() -> None:
        new_row.visible = mode.value == NEW_TARGET
        existing_row.visible = mode.value == EXISTING_TARGET
        if mode.value == EXISTING_TARGET and not collections:
            await load()
        save()

    with ui.card().classes("w-full").props("flat bordered").mark("extend-target"):
        ui.label("Zotero collection of the new papers").classes("font-bold")
        mode = (
            ui.radio(
                {
                    NEW_TARGET: "Create a new collection",
                    EXISTING_TARGET: "Add them to an existing collection",
                },
                value=NEW_TARGET,
                on_change=on_mode,
            )
            .props("inline dense")
            .mark("extend-target-mode")
        )
        with ui.row().classes("items-center gap-2 w-full") as new_row:
            name = (
                ui.input(
                    "Name (optional)",
                    placeholder="Extension <n> · <how> · <date>",
                    on_change=save,
                )
                .props("dense outlined clearable debounce=400")
                .classes("w-96")
                .mark("extend-target-name")
            )
        with ui.row().classes("items-center gap-2 w-full") as existing_row:
            existing = (
                ui.select(
                    {},
                    label="Collection",
                    with_input=True,
                    on_change=save,
                )
                .props("dense outlined")
                .classes("w-96")
                .mark("extend-target-collection")
            )
            ui.button(icon="refresh", on_click=load).props("flat dense round").tooltip(
                "Reload the collections"
            )
            loading = ui.spinner(size="sm")
            loading.visible = False
        existing_row.visible = False
        ui.label(
            "Applies to every tab below. Without a choice of collection, a new one "
            "is created."
        ).classes("text-xs text-gray-500")


ZOTERO_JOB = "extend-zotero"


def _zotero_card(ctx: AppContext, review: Review) -> None:
    """Add the papers of a Zotero library or collection (yours or a group)."""
    ui.label("Add papers from Zotero").classes("text-lg font-bold")
    ui.label(
        "Add the papers of a Zotero library (yours or a group) or of a collection. "
        "Papers already in the review (same DOI, else same title and year) are not "
        "added again; they get the Zotero tags and sub-corpora they lack. Papers "
        "of another library are copied into a new collection of the review's "
        "group. The current results are backed up first."
    ).classes("text-sm text-gray-500")
    current = zotero_library.load_source(review.folder)
    ui.label(
        "Zotero library of the review: "
        + (zotero_extend.describe(current) if current else "none yet")
    ).classes("text-sm").mark("extend-zotero-current")
    picker = ZoteroPicker(current)
    link = ui.checkbox(
        "Make it the review's Zotero library (sync, push, knowledge-graph export)",
        value=current is None,  # a review keeps its dedicated group
    ).mark("extend-zotero-link")

    def start() -> None:
        source = picker.source()
        if source is None:
            ui.notify(
                "Load the libraries and choose a library or collection", type="warning"
            )
            return
        if link.value and source.library_type != "group":
            ui.notify(
                "A review's Zotero library is a dedicated group: choose a group, "
                "or untick the link",
                type="warning",
            )
            return

        target = extension_collection.load_target(review)  # the choice at start

        def body(job: Job) -> str:
            def progress(percent: int, message: str) -> None:
                job.progress, job.message = percent, message

            current = zotero_library.load_source(review.folder)
            before = extension_collection.review_keys(review)
            message = zotero_extend.extend_from_zotero(
                review, source, link=link.value, progress=progress
            ).message()
            if not link.value and not zotero_extend.same_library(current, source):
                # Papers of another library: copied into the review's group.
                published = extension_collection.publish(
                    review, before, "Zotero", progress=progress, target=target
                )
                message = f"{message} {published.message()}"
            return message

        try:
            # Rewrites the review's rows (reads Zotero only).
            ctx.runner.start_task(
                review, ZOTERO_JOB, body, resources=[results_resource(review.id, ROWS)]
            )
        except JobConflictError as exc:
            show_error(
                "Cannot add papers from Zotero now",
                JobConflictError(f"{exc}: wait for it to finish, or cancel it."),
                expected=True,
            )

    ui.button("Add papers", icon="library_add", on_click=start).props("no-caps").mark(
        "extend-zotero-start"
    )
    run_status = RunStatus(review, ZOTERO_JOB, "Added from Zotero")
    JobPanel(
        ctx,
        review,
        ZOTERO_JOB,
        show_logs=False,
        on_finished=lambda job: run_status.update(),
    )


BIBTEX_JOB = "bibtex-import"


def _bibtex_card(ctx: AppContext, review: Review) -> None:
    """Add the papers of a .bib file (Zotero, Google Scholar, DBLP exports…)."""
    ui.label("Import a BibTeX file").classes("text-lg font-bold")
    ui.label(
        "Add the papers of a .bib file to the review. Papers already in the review "
        "(same DOI, else same title and year) are skipped, so the same file can be "
        "imported again after adding entries. Keywords of the entries become tags. "
        "The current results are backed up first."
    ).classes("text-sm text-gray-500")
    result = ui.column().classes("gap-1").mark("bibtex-result")

    async def imported(event: events.UploadEventArguments) -> None:
        upload.reset()
        try:
            raw = await event.file.read()
            text = raw.decode("utf-8-sig", errors="replace")
            target = extension_collection.load_target(review)  # the choice now

            def body(job: Job) -> str:
                before = extension_collection.review_keys(review)
                try:
                    job.result = bibtex_import.import_bibtex(
                        review, text, event.file.name
                    )
                except bibtex_import.BibtexImportError as exc:
                    job.result = exc  # the user's file, not a failure of the app
                    return str(exc)
                message = job.result.message()
                if job.result.added:
                    published = extension_collection.publish(
                        review, before, "BibTeX", target=target
                    )
                    message = f"{message} {published.message()}"
                    job.result.warnings.insert(0, published.message())
                return message

            # A job: it rewrites the rows, so it waits for (and blocks) the jobs
            # using this review's papers.
            job = ctx.runner.start_task(
                review, BIBTEX_JOB, body, resources=[results_resource(review.id, ROWS)]
            )
            job = await wait_for(job)
        except JobConflictError as exc:
            show_error("Cannot import this BibTeX file now", exc, expected=True)
            return
        except Exception as exc:
            show_error("Cannot import this BibTeX file", exc)
            return
        if job.error:
            show_error("Cannot import this BibTeX file", RuntimeError(job.error))
            return
        if isinstance(job.result, bibtex_import.BibtexImportError):
            show_error("Cannot import this BibTeX file", job.result, expected=True)
            return
        summary = job.result
        if summary is None:  # cancelled before it ran
            return
        result.clear()
        with result:
            ui.label(summary.message()).classes("text-sm").mark("bibtex-summary")
            for warning in summary.warnings[:5]:
                ui.label(warning).classes("text-xs text-warning")
            if summary.added:
                ui.button(
                    "Screen the new papers",
                    icon="fact_check",
                    on_click=lambda: ui.navigate.to(f"/review/{review.id}/screen"),
                ).props("outline dense")
        ui.notify(summary.message(), type="positive" if summary.added else "info")

    upload = (
        ui.upload(on_upload=imported, auto_upload=True, label="BibTeX file (.bib)")
        .props("accept=.bib,.bibtex,.txt")
        .mark("bibtex-upload")
    )
