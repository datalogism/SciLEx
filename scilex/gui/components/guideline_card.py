"""Annotation guideline card of ④ Annotate > Parameters.

The guideline is the manual that goes with the grid (``annotation_guideline.md``):
a general part, and one ``## <DIMENSION>`` section per dimension. People read
it while annotating; SciLEx Annotator sends each section only with the question
of its dimension (see :mod:`scilex.tagging.guideline`).
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import events, ui

from scilex.gui.components.errors import show_error
from scilex.gui.services import annotations as service
from scilex.gui.services.workspace import Review
from scilex.tagging.guideline import coverage, parse_guideline


class GuidelineCard:
    """Edit, import, preview and check the review's annotation guideline."""

    def __init__(self, review: Review, dimensions: Callable[[], list[str]]):
        self.review = review
        self.dimensions = dimensions
        with ui.card().classes("w-full gap-2").mark("guideline-card"):
            with ui.row().classes("items-center w-full"):
                ui.label("Annotation guideline").classes("text-lg font-bold")
                ui.space()
                ui.label(str(service.guideline_path(review))).classes(
                    "text-xs text-gray-500 break-all"
                )
            ui.label(
                "Markdown. Everything before the first '## DIMENSION' heading is the "
                "general part; a '## DIMENSION' section (e.g. ## SAT_TASK) explains one "
                "dimension of the grid. The LLM annotator gets the general part with "
                "every question and a section only with its own dimension."
            ).classes("text-xs text-gray-500")
            with ui.tabs().props("dense align=left") as tabs:
                edit_tab = ui.tab("Edit", icon="edit")
                preview_tab = ui.tab("Preview", icon="visibility")
            with ui.tab_panels(tabs, value=edit_tab).classes("w-full"):
                with ui.tab_panel(edit_tab).classes("p-0"):
                    self.editor = (
                        ui.textarea(
                            value=service.load_guideline_text(review),
                            placeholder="# Guideline\n\nGeneral rules…\n\n## SAT_TASK\n…",
                            on_change=lambda _: self.check.refresh(),
                        )
                        .props("outlined autogrow input-class=font-mono")
                        .classes("w-full")
                        .style("max-height: 50vh; overflow: auto")
                        .mark("guideline-editor")
                    )
                with ui.tab_panel(preview_tab):
                    self.preview = ui.markdown(self.editor.value or "").classes(
                        "w-full"
                    )
            tabs.on_value_change(
                lambda _: self.preview.set_content(self.editor.value or "")
            )
            self.check()

            async def imported(event: events.UploadEventArguments) -> None:
                try:
                    text = (await event.file.read()).decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    show_error(
                        "Cannot read this file (UTF-8 expected)", exc, expected=True
                    )
                    return
                self.editor.set_value(text)
                upload_dialog.close()
                ui.notify("Guideline loaded: check it, then save it")

            with ui.dialog() as upload_dialog, ui.card():
                ui.label("Import a guideline (Markdown or text)").classes("font-bold")
                ui.upload(on_upload=imported, auto_upload=True).props(
                    "accept=.md,.markdown,.txt"
                ).mark("guideline-upload")
            with ui.row().classes("gap-2"):
                ui.button(
                    "Import file…", icon="upload_file", on_click=upload_dialog.open
                ).props("flat dense no-caps").mark("guideline-import")
                ui.button(
                    "Add missing sections",
                    icon="playlist_add",
                    on_click=self.add_missing,
                ).props("flat dense no-caps").tooltip(
                    "Append an empty '## DIMENSION' section for each dimension of the "
                    "grid the guideline does not explain yet."
                ).mark("guideline-add-missing")
                ui.space()
                ui.button("Save guideline", icon="save", on_click=self.save).mark(
                    "guideline-save"
                )

    @ui.refreshable_method
    def check(self) -> None:
        dims = self.dimensions()
        guide = parse_guideline(self.editor.value or "", dims)
        cov = coverage(guide, dims)
        with (
            ui.row().classes("items-center gap-1 flex-wrap").mark("guideline-coverage")
        ):
            if not (self.editor.value or "").strip():
                ui.label("No guideline yet.").classes("text-sm text-gray-500")
                return
            ui.label(
                f"{len(cov.covered)} of {len(dims)} dimensions explained"
                + ("" if cov.has_general else " · no general part")
            ).classes("text-sm")
            for dim in cov.missing[:30]:
                ui.badge(dim, color="warning").props("outline").tooltip(
                    "No ## section for this dimension"
                )
            if guide.other_headings:
                ui.label(
                    "Not dimensions of the grid (read as general text): "
                    + ", ".join(guide.other_headings[:8])
                ).classes("text-xs text-gray-500")

    def add_missing(self) -> None:
        dims = self.dimensions()
        text = self.editor.value or ""
        missing = coverage(parse_guideline(text, dims), dims).missing
        if not missing:
            ui.notify("Every dimension has a section")
            return
        sections = "\n\n".join(f"## {dim}\n\n" for dim in missing)
        self.editor.set_value(
            text.rstrip() + ("\n\n" if text.strip() else "") + sections
        )

    def save(self) -> None:
        try:
            path = service.save_guideline_text(self.review, self.editor.value or "")
        except OSError as exc:
            show_error("Cannot save the guideline", exc, expected=True)
            return
        ui.notify(f"Guideline saved: {path}" if path else "Guideline removed")
