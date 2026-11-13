"""Annotators card of ④ Annotate: members of the review and their papers.

Members come from the review's Zotero library (owner, admins, members and
everyone who edited items) and are kept in ``members.yml``; add each one's
ORCID iD, or add people by hand. Papers are then spread over the chosen
annotators as ``ANNOT:<id>`` tags (pushed to Zotero by the sync).
"""

from __future__ import annotations

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.services import members as service
from scilex.gui.services.extend import read_results
from scilex.gui.services.workspace import Review

ALL = "__all__"


class AnnotatorsCard:
    """Members table, assignment form and progress table."""

    def __init__(self, review: Review, *, show_assign: bool = True):
        """``show_assign=False``: no assignment form (campaigns assign papers)."""
        self.review = review
        self.members = service.load(review.folder)
        with ui.card().classes("w-full gap-2").mark("annotators-card"):
            ui.label("Annotators").classes("text-lg font-bold")
            ui.label(
                "Members of the review's Zotero library, identified in tags by their "
                "ORCID iD (else their Zotero user name). Papers are assigned as "
                "ANNOT:<id> tags; an annotator marks a finished paper "
                "ANNOT_VALID_BY:<id>, and DELETED_BY:<id> discards one."
            ).classes("text-sm text-gray-500")
            with ui.row().classes("gap-2"):
                ui.button("Find in Zotero", icon="group", on_click=self.discover).props(
                    "outline dense no-caps"
                ).mark("annotators-discover")
                ui.button("Add a person", icon="person_add", on_click=self.add).props(
                    "flat dense no-caps"
                ).mark("annotators-add")
            self.table()
            if show_assign:
                self.assign_form()
            self.progress()

    # -- members ----------------------------------------------------------

    @ui.refreshable_method
    def table(self) -> None:
        if not self.members:
            ui.label("No member yet: find them in Zotero or add a person.").classes(
                "text-sm text-gray-500"
            )
            return
        self.inputs = []
        for member in self.members:
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.label(member.name or member.username or "(no name)").classes(
                    "w-48 text-sm"
                )
                ui.label(member.username or "—").classes("w-40 text-xs text-gray-500")
                ui.badge(member.role).props("outline")
                orcid = (
                    ui.input("ORCID iD", value=member.orcid)
                    .props("dense outlined")
                    .classes("w-52")
                    .mark("annotators-orcid")
                )
                name = (
                    ui.input("Name", value=member.name)
                    .props("dense outlined")
                    .classes("w-48")
                )
                consent = (
                    ui.checkbox("Named in public dumps", value=member.consent_public)
                    .tooltip(
                        "The person agrees to be named, with their ORCID iD, in a "
                        "knowledge graph shared publicly (⑧ Export). Without it, a "
                        "public dump shows them as agent/<n>."
                    )
                    .mark("annotators-consent")
                )
                self.inputs.append((member, orcid, name, consent))
        ui.button("Save members", icon="save", on_click=self.save).props(
            "dense no-caps"
        ).mark("annotators-save")

    def save(self) -> None:
        for member, orcid, name, consent in self.inputs:
            member.orcid = (orcid.value or "").strip()
            member.name = (name.value or "").strip()
            member.consent_public = bool(consent.value)
        try:
            service.save(self.review.folder, self.members)
        except ValueError as exc:
            show_error("Cannot save the members", exc, expected=True)
            return
        ui.notify("Members saved", type="positive")
        self.assign_form.refresh()

    def add(self) -> None:
        self.members.append(service.Member(name="New annotator", role="manual"))
        self.table.refresh()

    async def discover(self) -> None:
        try:
            self.members = await run.io_bound(service.discover, self.review)
        except Exception as exc:
            show_error(
                "Cannot read the members from Zotero",
                exc,
                expected=isinstance(exc, (ValueError, ConnectionError)),
            )
            return
        ui.notify(f"{len(self.members)} members", type="positive")
        self.table.refresh()
        self.assign_form.refresh()

    # -- assignment -------------------------------------------------------

    @ui.refreshable_method
    def assign_form(self) -> None:
        people = {m.identifier: m.label for m in self.members if m.identifier}
        if not people:
            return
        ui.label("Assign papers").classes("font-medium")
        try:
            data = read_results(self.review.results_path)
        except Exception:
            data = None
        corpora = {ALL: "All papers"}
        if data is not None and "zotero_collections" in data:
            for value in data["zotero_collections"].dropna().astype(str):
                for path in value.split(";"):
                    top = path.split("/")[0].strip()
                    if top:
                        corpora.setdefault(top, top)
        with ui.row().classes("items-center gap-3"):
            self.who = (
                ui.select(people, multiple=True, label="Annotators", value=list(people))
                .props("dense outlined use-chips")
                .classes("min-w-72")
                .mark("annotators-who")
            )
            self.corpus = (
                ui.select(corpora, value=ALL, label="Papers")
                .props("dense outlined")
                .classes("w-48")
                .mark("annotators-corpus")
            )
            self.per_paper = (
                ui.number("Annotators per paper", value=1, min=1, max=5, precision=0)
                .props("dense outlined")
                .classes("w-44")
                .mark("annotators-per-paper")
            )
            self.only_new = ui.checkbox(
                "Only papers not assigned yet", value=True
            ).mark("annotators-only-new")
        self.preview_label = ui.label().classes("text-sm").mark("annotators-preview")
        with ui.row().classes("gap-2"):
            ui.button("Preview", icon="preview", on_click=self.preview).props(
                "outline dense no-caps"
            ).mark("annotators-preview-button")
            self.apply_button = (
                ui.button("Assign", icon="assignment_ind", on_click=self.apply)
                .props("dense no-caps")
                .mark("annotators-apply")
            )
            self.apply_button.set_enabled(False)
        self.plan = None

    def _plan(self) -> service.Assignment:
        data = read_results(self.review.results_path)
        return service.plan_assignment(
            data,
            list(self.who.value or []),
            per_paper=int(self.per_paper.value or 1),
            only_unassigned=self.only_new.value,
            sub_corpus=None if self.corpus.value == ALL else self.corpus.value,
        )

    def preview(self) -> None:
        try:
            self.plan = self._plan()
        except ValueError as exc:
            show_error("Cannot plan the assignment", exc, expected=True)
            return
        self.preview_label.set_text(self.plan.message())
        self.apply_button.set_enabled(bool(self.plan.plan))

    async def apply(self) -> None:
        if not self.plan:
            return
        try:
            count = await run.io_bound(service.assign, self.review, self.plan)
        except Exception as exc:
            show_error("Cannot assign the papers", exc)
            return
        self.plan = None
        self.apply_button.set_enabled(False)
        ui.notify(
            f"{count} papers assigned. Sync with Zotero (icon at the top) to share the tags.",
            type="positive",
        )
        self.progress.refresh()

    # -- progress ---------------------------------------------------------

    @ui.refreshable_method
    def progress(self) -> None:
        try:
            data = read_results(self.review.results_path)
        except Exception:
            return
        rows = service.progress(data) if data is not None else []
        if not rows:
            return
        ui.label("Progress").classes("font-medium")
        ui.table(
            columns=[
                {
                    "name": "annotator",
                    "label": "Annotator",
                    "field": "annotator",
                    "align": "left",
                },
                {"name": "assigned", "label": "Assigned", "field": "assigned"},
                {"name": "validated", "label": "Validated", "field": "validated"},
                {"name": "deleted", "label": "Discarded", "field": "deleted"},
                {
                    "name": "validated_by_them",
                    "label": "Validated by them",
                    "field": "validated_by_them",
                },
            ],
            rows=rows,
        ).props("dense flat").classes("w-full").mark("annotators-progress")
