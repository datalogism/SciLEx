"""Home screen: the reviews known to the app."""

import re
from collections.abc import Callable
from pathlib import Path

import yaml
from nicegui import app, run, ui

from scilex.gui.components.branding import render_logo
from scilex.gui.components.dialogs import one_shot_dialog
from scilex.gui.components.errors import show_error
from scilex.gui.components.folder_picker import pick_folder_in_page
from scilex.gui.components.zotero_picker import ZoteroPicker
from scilex.gui.services import keys_editor, zotero_library
from scilex.gui.services.workspace import Review, reviews_home
from scilex.gui.services.zotero_library import ZoteroSource
from scilex.gui.state import AppContext
from scilex.init_templates import list_templates
from scilex.settings.schema import SettingsError

# Errors caused by the user's input or files, shown without a diagnostic report.
EXPECTED_ERRORS = (OSError, SettingsError)  # missing, existing, unwritable files
NO_TEMPLATE = "(blank)"
SCRATCH, ZOTERO = "scratch", "zotero"  # starting points of a new review
CARDS_POLL_SECONDS = 2.0


async def pick_folder(ctx: AppContext, initial: str | None = None) -> str | None:
    """Ask for a folder (native dialog, or in-page picker in a browser); None if cancelled."""
    if not ctx.native:
        return await pick_folder_in_page(initial)
    import webview

    selection = await app.native.main_window.create_file_dialog(
        webview.FileDialog.FOLDER
    )
    return selection[0] if selection else None


def render(ctx: AppContext) -> None:
    """Draw the home screen."""
    ui.page_title("My reviews · SciLEx")
    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):
        render_logo("w-56")
        with ui.row().classes("w-full items-center"):
            ui.label("My reviews").classes("text-2xl font-bold")
            ui.space()
            ui.button(
                "New review", icon="add", on_click=lambda: new_review_dialog(ctx)
            ).mark("new-review")
            ui.button(
                "Open a folder",
                icon="folder_open",
                on_click=lambda: open_review_dialog(ctx),
            ).props("outline").mark("open-review")
            ui.button(
                "API keys", icon="key", on_click=lambda: ui.navigate.to("/keys")
            ).props("outline").mark("home-keys")
            ui.button(
                ctx.profile.name or ctx.profile.orcid,
                icon="badge",
                on_click=lambda: ui.navigate.to("/profile"),
            ).props("flat no-caps").mark("home-profile").tooltip(
                f"ORCID iD {ctx.profile.orcid} (change)"
            )
        _keys_banner()

        shown: list[tuple] = [()]

        @ui.refreshable
        def cards() -> None:
            reviews = ctx.workspace.list_reviews()
            shown[0] = _cards_state(ctx, reviews)
            if not reviews:
                ui.label(
                    "No review yet. Create one, or open a folder that already "
                    "contains a scilex.yml."
                ).classes("text-gray-500")
            with ui.row().classes("w-full gap-4"):
                for review in reviews:
                    _review_card(ctx, review, cards.refresh)

        cards()

        def refresh_if_changed() -> None:
            # A running job, new results or an edited scilex.yml change a card.
            if _cards_state(ctx, ctx.workspace.list_reviews()) != shown[0]:
                cards.refresh()

        ui.timer(CARDS_POLL_SECONDS, refresh_if_changed)


def _keys_banner() -> None:
    """Invite to set the global keys when none is set, or old ones can be imported."""
    try:
        global_keys = keys_editor.load_keys()
    except Exception:
        return  # the keys screen explains a broken file
    legacy = keys_editor.legacy_blocks_to_import(global_keys)
    if global_keys and not legacy:
        return
    text = (
        "Keys from your previous configuration (api.config.yml) can be imported: "
        + ", ".join(sorted(legacy))
        + "."
        if legacy
        else "No API key yet. Set them once here; every review uses them by default."
    )
    with (
        ui.card().classes("w-full bg-blue-50").mark("home-keys-banner"),
        ui.row().classes("w-full items-center no-wrap gap-3"),
    ):
        ui.icon("key").classes("text-primary")
        ui.label(text).classes("text-sm grow")
        ui.button("Set up API keys", on_click=lambda: ui.navigate.to("/keys")).props(
            "flat no-caps"
        )


def _cards_state(ctx: AppContext, reviews: list[Review]) -> tuple:
    """What the cards show, to redraw them only when it changes."""
    state = []
    for review in reviews:
        job = ctx.runner.latest_for(review.id)
        running = job.message if job is not None and job.is_active else None
        state.append((review, review.error, review.has_results, running))
    return tuple(state)


def _review_card(
    ctx: AppContext, review: Review, on_forget: Callable[[], None]
) -> None:
    job = ctx.runner.latest_for(review.id)
    with (
        ui.card()
        .classes("w-72 cursor-pointer")
        .on("click", lambda: ui.navigate.to(f"/review/{review.id}"))
        .mark(f"review-{review.id}")
    ):
        with ui.row().classes("w-full items-start no-wrap gap-1"):
            ui.label(review.name).classes(
                "text-lg font-bold grow min-w-0 break-words"
            ).style("overflow-wrap: anywhere").tooltip(review.name)
            _card_menu(ctx, review, on_forget)
        ui.label(str(review.folder)).classes("text-xs text-gray-500 break-all")
        if review.error:
            ui.label("scilex.yml is invalid: open to fix it").classes(
                "text-sm text-negative"
            )
        elif job is not None and job.is_active:
            ui.label(f"Running: {job.message}").classes("text-sm text-primary")
        elif review.has_results:
            ui.label("Results available").classes("text-sm text-positive")
        else:
            ui.label("Not collected yet").classes("text-sm text-gray-500")


def _card_menu(ctx: AppContext, review: Review, on_forget: Callable[[], None]) -> None:
    """Small menu (⋮) of a card: forget the review or copy its folder path."""

    def forget() -> None:
        ctx.workspace.forget_review(review.folder)
        confirm.close()
        on_forget()

    with ui.dialog() as confirm, ui.card():
        ui.label(f"Remove '{review.name}' from the list?").classes("font-bold")
        ui.label(
            "The files stay on disk; you can add the folder back with 'Open a folder'."
        ).classes("text-sm")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=confirm.close).props("flat")
            ui.button("Remove", on_click=forget).props("color=negative").mark(
                f"forget-confirm-{review.id}"
            )

    def copy_path() -> None:
        ui.clipboard.write(str(review.folder))
        ui.notify("Folder path copied")

    # The card navigates on click: the menu button must not trigger it.
    with (
        ui.button(icon="more_vert")
        .props("flat dense round")
        .on("click.stop")
        .mark(f"forget-{review.id}"),
        ui.menu(),
    ):
        ui.menu_item("Remove from list", on_click=confirm.open).mark(
            f"forget-item-{review.id}"
        )
        ui.menu_item("Show folder path", on_click=copy_path)


def _folder_input(ctx: AppContext, label: str) -> ui.input:
    with ui.row().classes("w-full items-center no-wrap"):
        folder = ui.input(label).classes("grow").mark("folder")

        async def browse() -> None:
            chosen = await pick_folder(ctx, folder.value)
            if chosen:
                folder.value = chosen

        ui.button(icon="folder", on_click=browse).props("flat").tooltip("Browse…").mark(
            "browse"
        )
    return folder


async def pick_config_file(ctx: AppContext) -> str | None:
    """Ask for a scilex.yml / scilex.config.yml (native dialog only); None if cancelled."""
    if not ctx.native:
        return None
    import webview

    selection = await app.native.main_window.create_file_dialog(
        webview.FileDialog.OPEN, file_types=("SciLEx configuration (*.yml;*.yaml)",)
    )
    return selection[0] if selection else None


def new_review_dialog(ctx: AppContext) -> None:
    """Ask for a folder, a name and a starting point, then create the review.

    A review starts from scratch (a template), or from an existing Zotero
    collection whose papers become the results, with keywords, years and
    annotation grid deduced from them or read from configuration files.
    """
    with one_shot_dialog() as dialog, ui.card().classes("w-[36rem]"):
        ui.label("New review").classes("text-lg font-bold")
        start = ui.toggle(
            {SCRATCH: "From scratch", ZOTERO: "From Zotero"},
            value=SCRATCH,
        ).mark("new-review-start")
        folder = _folder_input(ctx, "Folder (optional, created if needed)")
        # Set as a value, not a props string: NiceGUI parses that string as a
        # Python literal, and a Windows path (C:\Users\...) is an invalid escape.
        folder.props["hint"] = (
            f"Empty: {reviews_home() / '<name>'}. Relative paths start in that folder."
        )
        name = (
            ui.input("Name", placeholder="e.g. rag_knowledge_graphs")
            .classes("w-full")
            .mark("name")
        )
        template = ui.select(
            [NO_TEMPLATE, *list_templates()], value=NO_TEMPLATE, label="Template"
        ).classes("w-full")
        template.bind_visibility_from(start, "value", value=SCRATCH)
        zotero = _ZoteroImportFields(ctx, name)
        zotero.column.bind_visibility_from(start, "value", value=ZOTERO)

        def target_folder() -> Path:
            # A relative folder (or the name) lands in ~/SciLEx.
            return Path((folder.value or "").strip() or name.value.strip())

        def create_from_scratch() -> None:
            try:
                review = ctx.workspace.create_review(
                    target_folder(),
                    name=name.value.strip(),
                    template=None if template.value == NO_TEMPLATE else template.value,
                )
            except EXPECTED_ERRORS as exc:
                show_error("Cannot create the review", exc, expected=True)
                return
            except Exception as exc:
                show_error("Cannot create the review", exc)
                return
            dialog.close()
            ui.navigate.to(f"/review/{review.id}/configure")

        async def create() -> None:
            if not name.value or not name.value.strip():
                ui.notify("A name is required", type="warning")
                return
            if start.value == SCRATCH:
                create_from_scratch()
                return
            create_button.disable()
            try:
                created = await zotero.create(target_folder(), name.value.strip())
            finally:
                create_button.enable()
            if created is not None:
                dialog.close()
                ui.navigate.to(f"/review/{created.id}")

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            create_button = ui.button("Create", on_click=create).mark("create")
    dialog.open()


ONE_REVIEW, PER_COLLECTION = "one", "per-collection"  # Zotero import modes


class _ZoteroImportFields:
    """Fields of the "From Zotero" mode of the New review dialog."""

    def __init__(self, ctx: AppContext, name: ui.input):
        self.ctx, self.name = ctx, name
        with ui.column().classes("w-full gap-2") as self.column:
            ui.label(
                "The papers of a Zotero library (yours or a group), or of one of its "
                "collections, become the review's results. Keywords come from SciLEx's "
                "Collect_KW tags, years from the paper dates, and the annotation grid "
                "from DIMENSION:value tags, unless a configuration file is given."
            ).classes("text-xs text-gray-500")
            self._zotero_status()
            self.picker = ZoteroPicker()
            self.picker.collection_select.on_value_change(self._suggest_name)
            self.mode = ui.radio(
                {
                    ONE_REVIEW: "One review (collections kept as sub-corpora)",
                    PER_COLLECTION: "One review per collection",
                },
                value=ONE_REVIEW,
            ).props("dense").mark("zotero-mode")
            with ui.row().classes("w-full items-center no-wrap"):
                self.config = (
                    ui.input(
                        "Configuration file (optional)",
                        placeholder="scilex.yml or legacy scilex.config.yml",
                    )
                    .classes("grow")
                    .mark("zotero-config")
                )
                if ctx.native:

                    async def browse() -> None:
                        chosen = await pick_config_file(ctx)
                        if chosen:
                            self.config.value = chosen

                    ui.button(icon="description", on_click=browse).props(
                        "flat"
                    ).tooltip("Browse…")
            self.config.props["hint"] = (
                "Its values win; keywords or years it lacks are deduced. A "
                "scilex.advanced.yml next to a legacy file is read too."
            )

    def _zotero_status(self) -> None:
        """Say that the keys are missing, when they are."""
        try:
            zotero_library.zotero_credentials(keys_editor.load_keys())
        except (zotero_library.ZoteroNotConfiguredError, OSError, ValueError):
            with (
                ui.row()
                .classes("w-full items-center no-wrap gap-2")
                .mark("zotero-missing")
            ):
                ui.icon("warning").classes("text-warning")
                ui.label(
                    "Zotero is not configured: set its key and library id in the "
                    "global API keys first."
                ).classes("text-sm grow")
                ui.button(
                    "API keys", icon="key", on_click=lambda: ui.navigate.to("/keys")
                ).props("flat dense no-caps").mark("zotero-go-keys")

    def _suggest_name(self, _event) -> None:
        if (self.name.value or "").strip():
            return
        collection = self.picker.collection
        library = self.picker.library
        leaf = (
            collection.path.split(" / ")[-1]
            if collection
            else (library.name.removeprefix("Group: ") if library else "")
        )
        self.name.value = _safe_name(leaf)

    async def create(self, folder: Path, name: str):
        """Import the chosen library / collection; None (after a message) on error.

        In "one review per collection" mode, several reviews are created in
        ``folder`` (one sub-folder each) and the first one is returned.
        """
        source = self.picker.source()
        if source is None:
            ui.notify("Load the Zotero libraries and choose one", type="warning")
            return None
        config_text = (self.config.value or "").strip()
        config_file = Path(config_text).expanduser() if config_text else None
        if config_file is not None and not config_file.is_file():
            ui.notify(f"No such file: {config_file}", type="warning")
            return None
        notice = ui.notification(
            f"Reading {source.describe()} from Zotero…", spinner=True, timeout=None
        )
        created = []
        try:
            api = zotero_library.client(library=source)
            collections = await run.io_bound(zotero_library.list_collections, api)
            papers = await run.io_bound(
                zotero_library.fetch_source_papers, api, source, collections
            )
            if self.mode.value == PER_COLLECTION:
                by_path = {c.path: c for c in collections}
                for path, items in sorted(zotero_library.split_by_collection(papers).items()):
                    collection = by_path[path]
                    part = ZoteroSource(
                        library_id=source.library_id,
                        library_type=source.library_type,
                        collection_key=collection.key,
                        collection_name=path,
                        include_subcollections=False,
                        library_name=source.library_name,
                    )
                    leaf = _safe_name(path.split(" / ")[-1])
                    created.append(
                        zotero_library.create_review_from_zotero(
                            self.ctx.workspace,
                            folder / leaf,
                            f"{name}_{leaf}",
                            part,
                            [i for i in items if i.get("data", {}).get("collections")],
                            config_file,
                        )
                    )
                if not created:
                    raise ValueError("None of the chosen collections holds a paper.")
            else:
                created.append(
                    zotero_library.create_review_from_zotero(
                        self.ctx.workspace, folder, name, source, papers, config_file
                    )
                )
        except (
            *EXPECTED_ERRORS,
            ValueError,
            ConnectionError,
            zotero_library.ZoteroNotConfiguredError,
            yaml.YAMLError,
        ) as exc:
            show_error("Cannot create the review", exc, expected=True)
            return None
        except Exception as exc:
            show_error("Cannot create the review", exc)
            return None
        finally:
            notice.dismiss()
        for review, summary in created:
            groups = " AND ".join(
                "(" + " OR ".join(group) + ")" for group in summary.keyword_groups
            )
            ui.notify(
                f"{review.name}: {summary.papers} papers imported; keywords "
                f"{groups or '—'}; years {summary.years or '—'}; "
                f"{summary.grid_dimensions} grid dimensions.",
                type="positive",
                multi_line=True,
                timeout=10000,
            )
            for warning in summary.warnings:
                ui.notify(warning, type="warning", multi_line=True, timeout=10000)
        return created[0][0]


def _safe_name(text: str) -> str:
    """A review / folder name from a collection or library name."""
    return re.sub(r"[^\w-]+", "_", text).strip("_") or "zotero"


def open_review_dialog(ctx: AppContext) -> None:
    """Register an existing folder holding a scilex.yml."""
    with one_shot_dialog() as dialog, ui.card().classes("w-[32rem]"):
        ui.label("Open a review folder").classes("text-lg font-bold")
        folder = _folder_input(ctx, "Folder containing scilex.yml")

        def open_folder() -> None:
            if not folder.value:
                ui.notify("Choose a folder", type="warning")
                return
            try:
                review = ctx.workspace.open_review(Path(folder.value))
            except EXPECTED_ERRORS as exc:
                show_error("Cannot open this folder", exc, expected=True)
                return
            except Exception as exc:
                show_error("Cannot open this folder", exc)
                return
            dialog.close()
            ui.navigate.to(f"/review/{review.id}")

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Open", on_click=open_folder).mark("open")
    dialog.open()
