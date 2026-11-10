"""Export screen: BibTeX, CSV, RDF/Turtle and Zotero for the chosen papers."""

from __future__ import annotations

from nicegui import run, ui

from scilex.gui.components.dialogs import one_shot_dialog
from scilex.gui.components.errors import show_error
from scilex.gui.components.job_panel import BusyNotice, JobPanel
from scilex.gui.components.run_status import RunStatus
from scilex.gui.components.zotero_picker import ZoteroPicker
from scilex.gui.services import exports, kg_export, run_history, zotero_library
from scilex.gui.services.jobs import Job, JobConflictError
from scilex.gui.services.screening import ReviewFileError
from scilex.gui.services.workspace import Review, Workspace
from scilex.gui.state import AppContext
from scilex.settings.schema import SettingsError

KIND = "export"
KG = "kg"


def history_key(fmt: str) -> str:
    """Run-history key of the export to ``fmt`` (each format has its own date)."""
    return f"{KIND}-{fmt}"

FORMATS = (
    (
        exports.BIBTEX,
        "BibTeX",
        "Reference file for LaTeX, Zotero or JabRef.",
    ),
    (
        exports.CSV,
        "CSV",
        "Spreadsheet table (';' separated) with your screening decision and note.",
    ),
    (
        exports.TURTLE,
        "RDF / Turtle",
        "Knowledge graph of the papers, authors and venues.",
    ),
    (
        exports.ZOTERO,
        "Zotero",
        "Pushes the papers into the review's Zotero collection (above), or a "
        "collection named after the review; papers already there are skipped.",
    ),
    (
        KG,
        "Knowledge graph (scilex-lpwc-ap)",
        "Maps the review's Zotero papers, citations and annotations with the "
        "scilex-lpwc-ap application profile (OpenCitations/SPAR + Linked Papers "
        "With Code), with you (ORCID) as creator, and checks it with SHACL. "
        "Uses every paper of the Zotero source, whatever the choice above.",
    ),
)


def kg_summary(result) -> str:
    """Human-readable result of a knowledge-graph export."""
    report = result.report
    shacl = {
        True: "conforms to the profile",
        False: "has SHACL violations (see the .shacl.txt report)",
        None: "not validated",
    }[report.conforms]
    return (
        f"{report.papers} papers -> {report.triples} triples in {result.turtle}; "
        f"the graph {shacl}."
    )


def zotero_summary(counts: dict[str, int]) -> str:
    """Human-readable result of a Zotero push."""
    return (
        f"{counts.get('success', 0)} pushed, "
        f"{counts.get('skipped', 0)} skipped as duplicates, "
        f"{counts.get('skipped_for_incompatibility', 0)} without usable URL or type, "
        f"{counts.get('failed', 0)} failed."
    )


def _zotero_target_card(review: Review) -> None:
    """Show, and let the user change, the review's own Zotero library and collection."""
    with ui.card().classes("w-full").mark("zotero-target"):
        ui.label("Zotero library of this review").classes("font-bold")

        @ui.refreshable
        def current() -> None:
            source = zotero_library.load_source(review.folder)
            ui.label(
                source.describe()
                if source
                else f"Not chosen: the library of your API keys, collection "
                f"'{review.name}' (created when pushing)."
            ).classes("text-sm").mark("zotero-target-current")

        current()

        def change() -> None:
            with one_shot_dialog() as dialog, ui.card().classes("w-[36rem]"):
                ui.label("Zotero library and collection of this review").classes(
                    "text-lg font-bold"
                )
                ui.label(
                    "Each review can use its own library (yours or a group) and "
                    "collection, or a whole library."
                ).classes("text-sm text-gray-500")
                picker = ZoteroPicker(zotero_library.load_source(review.folder))

                def save() -> None:
                    source = picker.source()
                    if source is None:
                        ui.notify("Load the libraries and choose one", type="warning")
                        return
                    zotero_library.save_source(review.folder, source)
                    dialog.close()
                    current.refresh()

                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")
                    ui.button("Save", on_click=save).mark("zotero-target-save")
            dialog.open()

        ui.button("Change", icon="edit", on_click=change).props("outline dense").mark(
            "zotero-target-change"
        )


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Export screen of ``review``."""
    ui.label("Export").classes("text-2xl font-bold")
    ui.label("Choose which papers to export, then a format.").classes("text-gray-500")
    _zotero_target_card(review)

    scope = ui.radio(
        {
            exports.SCOPE_INCLUDED: "Included papers only (…)",
            exports.SCOPE_ALL: "All papers (…)",
        },
        value=exports.SCOPE_ALL,
    ).mark("export-scope")
    scope_note = ui.column().classes("gap-0")
    has_included = {"value": False}

    def refuse_empty_scope(event) -> None:
        # A radio cannot disable one option: refuse it (the note says why).
        if event.value == exports.SCOPE_INCLUDED and not has_included["value"]:
            scope.set_value(exports.SCOPE_ALL)

    async def load_counts() -> None:
        # Counting reads the whole results CSV: keep it off the event loop.
        try:
            included, total = await run.io_bound(exports.scope_counts, review)
        except Exception as exc:
            with scope_note:
                show_error(
                    "Cannot read the results",
                    exc,
                    expected=isinstance(exc, ReviewFileError),
                )
            return
        has_included["value"] = bool(included)
        scope.set_options(
            {
                exports.SCOPE_INCLUDED: f"Included papers only ({included})",
                exports.SCOPE_ALL: f"All papers ({total})",
            },
            value=exports.SCOPE_INCLUDED if included else exports.SCOPE_ALL,
        )
        if not included:
            with scope_note:
                ui.label(
                    "Included papers only is unavailable: no paper is included yet "
                    "(mark papers as included in ③ Screen)."
                ).classes("text-sm text-gray-500")

    scope.on_value_change(refuse_empty_scope)
    ui.timer(0, load_counts, once=True)
    config_error = None
    zotero_ready = False
    try:
        zotero_ready = (
            exports.zotero_settings(Workspace.load_config(review)) is not None
        )
    except (SettingsError, FileNotFoundError) as exc:
        config_error = exc

    kg_problem = kg_export.missing_dependencies()
    buttons = {}
    with ui.column().classes("gap-3 w-full"):
        history = run_history.load(review.folder)
        run_statuses: list[RunStatus] = []
        for fmt, label, text in FORMATS:
            with ui.card().classes("w-full"), ui.row().classes("items-center gap-4"):
                with ui.column().classes("gap-0 w-96"):
                    ui.label(label).classes("font-bold")
                    ui.label(text).classes("text-sm text-gray-500")
                buttons[fmt] = ui.button(
                    f"Export {label}",
                    icon="cloud_upload" if fmt == exports.ZOTERO else "download",
                ).mark(f"export-{fmt}")
                run_statuses.append(RunStatus(review, history_key(fmt), history=history))
                if fmt == KG and kg_problem:
                    ui.label(kg_problem).classes("text-sm text-negative").mark(
                        "export-kg-missing"
                    )
                    buttons[fmt].set_enabled(False)
                if fmt == exports.ZOTERO and not zotero_ready:
                    ui.label(
                        str(config_error)
                        if config_error
                        else "Zotero user ID and API key are missing."
                    ).classes("text-sm text-negative")
                    ui.link(
                        "Set up API keys",
                        f"/review/{review.id}/keys",
                    ).mark("export-zotero-keys")
                    buttons[fmt].set_enabled(False)

    busy_notice = BusyNotice(ctx)
    result_box = ui.column().classes("gap-1 w-full")
    history_box = ui.column().classes("gap-1 w-full")

    def update_buttons(job: Job | None) -> None:
        busy = ctx.runner.active_job() is not None
        busy_notice.update(job)
        for fmt, button in buttons.items():
            if fmt == exports.ZOTERO and not zotero_ready:
                continue
            if fmt == KG and kg_problem:
                continue
            button.set_enabled(not busy)

    def show_history() -> None:
        history_box.clear()
        with history_box:
            ui.label("Previous exports").classes("font-bold mt-2")
            files = exports.list_exports(review)
            if not files:
                ui.label("No export yet.").classes("text-sm text-gray-500")
            for path in files:
                ui.label(path.name).classes("text-sm")

    def show_result(job: Job) -> None:
        latest = run_history.load(review.folder)
        for status in run_statuses:
            status.update(latest)
        result_box.clear()
        with result_box:
            if job.error or job.result is None:
                ui.label(job.message).classes("text-negative")
            elif isinstance(job.result, dict):
                ui.label(zotero_summary(job.result)).classes("font-bold").mark(
                    "export-result"
                )
            elif isinstance(job.result, kg_export.KgExport):
                result = job.result
                ui.label(kg_summary(result)).classes("font-bold break-all").mark(
                    "export-result"
                )
                ui.button(
                    "Reveal in folder",
                    icon="folder_open",
                    on_click=lambda: exports.reveal_in_folder(result.turtle),
                ).props("outline").mark("export-reveal")
            else:
                path = job.result
                ui.label(f"Exported to {path}").classes("font-bold break-all").mark(
                    "export-result"
                )
                ui.button(
                    "Reveal in folder",
                    icon="folder_open",
                    on_click=lambda: exports.reveal_in_folder(path),
                ).props("outline").mark("export-reveal")
        show_history()

    JobPanel(
        ctx,
        review,
        KIND,
        on_change=update_buttons,
        on_finished=show_result,
        show_logs=False,
    )
    show_history()

    async def confirm_zotero() -> None:
        """Ask before anything is sent to Zotero."""
        chosen = scope.value
        try:
            settings = exports.zotero_settings(Workspace.load_config(review))
            papers = await run.io_bound(exports.select_papers, review, chosen)
            count = len(papers)
        except Exception as exc:
            show_error("Cannot prepare the Zotero push", exc)
            return
        if settings is None:
            show_error(
                "Cannot prepare the Zotero push",
                ValueError("Zotero user ID and API key are missing."),
                expected=True,
            )
            return
        with one_shot_dialog() as dialog, ui.card().mark("zotero-confirm"):
            ui.label(
                f"Push {count} papers to the Zotero {settings.user_mode} library "
                f'{settings.user_id} (collection "{review.name}")?'
            )
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat").mark(
                    "zotero-cancel"
                )

                def push() -> None:
                    dialog.close()
                    start(exports.ZOTERO)

                ui.button("Push", on_click=push).props("color=negative").mark(
                    "zotero-push"
                )
        dialog.open()

    def start(fmt: str) -> None:
        chosen = scope.value

        def body(job: Job) -> str:
            job.progress = 10
            if fmt == KG:

                def progress(percent: int, message: str) -> None:
                    job.progress, job.message = percent, message

                job.result = kg_export.export_knowledge_graph(
                    keys=Workspace.load_config(review).api,
                    folder=review.folder,
                    review_name=review.name,
                    output_dir=review.collection_dir / kg_export.KG_DIRNAME,
                    creator=ctx.profile.orcid_uri,
                    progress=progress,
                )
                return kg_summary(job.result)
            if fmt == exports.ZOTERO:
                job.message = "Pushing to Zotero…"
                job.result = exports.push_to_zotero(
                    review, Workspace.load_config(review), chosen
                )
                return zotero_summary(job.result)
            job.message = f"Writing {fmt}…"
            job.result = exports.run_file_export(review, fmt, chosen)
            return f"Exported {job.result.name}"

        try:
            job = ctx.runner.start_task(
                review, KIND, body, history_key=history_key(fmt)
            )
        except JobConflictError as exc:
            show_error("Cannot start the export", exc, expected=True)
            return
        except Exception as exc:
            show_error("Cannot start the export", exc)
            return
        # Disable at once: the panel timer would leave a double-click window.
        update_buttons(job)

    for fmt, button in buttons.items():
        if fmt == exports.ZOTERO:
            button.on_click(confirm_zotero)
        else:
            button.on_click(lambda fmt=fmt: start(fmt))
