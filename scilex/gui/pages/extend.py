"""Extend screen: add papers to a review that already has some.

New queries (add new papers only, or re-aggregate everything), snowballing,
keyword suggestions, and papers from a Zotero library or a BibTeX file. Same pipeline as ② Collect, see
:mod:`scilex.gui.pages.collect`.
"""

from nicegui import events, run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import JobPanel
from scilex.gui.components.run_status import RunStatus
from scilex.gui.components.zotero_picker import ZoteroPicker
from scilex.gui.pages import collect
from scilex.gui.services import bibtex_import, zotero_extend, zotero_library
from scilex.gui.services.jobs import Job, JobConflictError
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Extend screen of ``review``."""
    collect.render(ctx, review, extending=True)
    _zotero_card(ctx, review)
    _bibtex_card(review)


ZOTERO_JOB = "extend-zotero"


def _zotero_card(ctx: AppContext, review: Review) -> None:
    """Add the papers of a Zotero library or collection (yours or a group)."""
    ui.separator()
    ui.label("Add papers from Zotero").classes("text-lg font-bold")
    ui.label(
        "Add the papers of a Zotero library (yours or a group) or of a collection. "
        "Papers already in the review (same DOI, else same title and year) are not "
        "added again; they get the Zotero tags and sub-corpora they lack. The "
        "current results are backed up first."
    ).classes("text-sm text-gray-500")
    current = zotero_library.load_source(review.folder)
    ui.label(
        "Zotero library of the review: "
        + (zotero_extend.describe(current) if current else "none yet")
    ).classes("text-sm").mark("extend-zotero-current")
    picker = ZoteroPicker(current)
    link = ui.checkbox(
        "Make it the review's Zotero library (sync, push, knowledge-graph export)",
        value=True,
    ).mark("extend-zotero-link")

    def start() -> None:
        source = picker.source()
        if source is None:
            ui.notify(
                "Load the libraries and choose a library or collection", type="warning"
            )
            return

        def body(job: Job) -> str:
            def progress(percent: int, message: str) -> None:
                job.progress, job.message = percent, message

            return zotero_extend.extend_from_zotero(
                review, source, link=link.value, progress=progress
            ).message()

        try:
            ctx.runner.start_task(review, ZOTERO_JOB, body)
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


def _bibtex_card(review: Review) -> None:
    """Add the papers of a .bib file (Zotero, Google Scholar, DBLP exports…)."""
    ui.separator()
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
            summary = await run.io_bound(
                bibtex_import.import_bibtex, review, text, event.file.name
            )
        except bibtex_import.BibtexImportError as exc:
            show_error("Cannot import this BibTeX file", exc, expected=True)
            return
        except Exception as exc:
            show_error("Cannot import this BibTeX file", exc)
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
