"""Validate tab of ④ Annotate: people resolve the LLM proposals.

Each ``DIMENSION-AUTO:value`` proposal is shown with the models' evidence,
confidence and rationale (and the guideline section of the dimension). Accept
writes the proposed values as ``DIMENSION:value`` codes, Correct writes other
values, Reject removes the proposal and keeps ``DIMENSION:?``. See
:func:`scilex.gui.services.llm_annotator.decide`.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.services import annotations, campaigns, llm_annotator
from scilex.gui.services.extend import read_results
from scilex.gui.services.workspace import Review
from scilex.tagging.grid import dimension_values

ALL = "__all__"
PAGE = 15
LIVE_SECONDS = 2.0  # how often the tab looks for newly imported proposals
CONFIDENCE_COLOURS = {"high": "positive", "medium": "warning", "low": "negative"}


class ValidateQueue:
    """Filters, one card per pending proposal, and bulk actions."""

    def __init__(self, review: Review, grid: Callable):
        self.review, self.grid = review, grid
        self.items: list[llm_annotator.Proposal] = []
        self.page = 0
        with ui.card().classes("w-full gap-2").mark("validate-card"):
            with ui.row().classes("items-center w-full"):
                ui.label("LLM proposals to validate").classes("text-lg font-bold")
                ui.space()
                ui.button(
                    "Check Zotero edits", icon="sync", on_click=self.reconcile
                ).props("flat dense no-caps").tooltip(
                    "Log the proposals people resolved directly in Zotero (after a "
                    "sync), and remove the proposals left on dimensions a person coded."
                ).mark("validate-reconcile")
            ui.label(
                "A proposal is a DIMENSION-AUTO:value tag. Accepting or correcting it "
                "writes your DIMENSION:value code; rejecting it keeps DIMENSION:?. You "
                "can also do it in Zotero: replace DIMENSION:? with your code and "
                "delete the -AUTO tag. Sync with Zotero to share your decisions."
            ).classes("text-sm text-gray-500")
            with ui.row().classes("items-center gap-3 flex-wrap"):
                store = campaigns.load(review.folder)
                self.campaign = (
                    ui.select(
                        {
                            ALL: "All campaigns",
                            **{c.id: c.label for c in store.campaigns},
                        },
                        value=ALL,
                        label="Campaign",
                        on_change=lambda _: self.load(),
                    )
                    .props("dense outlined")
                    .classes("w-56")
                    .mark("validate-campaign")
                )
                self.dimension = (
                    ui.select(
                        {ALL: "All dimensions"},
                        value=ALL,
                        label="Dimension",
                        on_change=lambda _: self.show_page(0),
                    )
                    .props("dense outlined")
                    .classes("w-56")
                    .mark("validate-dimension")
                )
                self.confidence = (
                    ui.select(
                        {
                            ALL: "Any confidence",
                            "high": "High",
                            "medium": "Medium",
                            "low": "Low",
                        },
                        value=ALL,
                        label="Confidence",
                        on_change=lambda _: self.show_page(0),
                    )
                    .props("dense outlined")
                    .classes("w-40")
                )
                self.evidence = ui.checkbox(
                    "Every quote found in the text",
                    value=False,
                    on_change=lambda _: self.show_page(0),
                )
            self.summary = ui.label().classes("text-sm").mark("validate-summary")
            self.list = ui.column().classes("w-full gap-2")
            with ui.row().classes("items-center gap-2"):
                self.prev = ui.button(
                    icon="chevron_left", on_click=lambda: self.show_page(self.page - 1)
                ).props("flat dense round")
                self.page_label = ui.label().classes("text-sm")
                self.next = ui.button(
                    icon="chevron_right", on_click=lambda: self.show_page(self.page + 1)
                ).props("flat dense round")
                ui.space()
                ui.button(
                    "Accept all shown", icon="done_all", on_click=self.accept_all
                ).props("outline dense no-caps").mark("validate-accept-all")
        self.drawn: list[tuple] = []
        self.signature = llm_annotator.store_signature(review)
        self.load()
        # Live: proposals imported by a running LLM campaign appear on their own.
        ui.timer(LIVE_SECONDS, self.follow)

    def follow(self) -> None:
        """Reload when LLM answers were imported or decided since the last look."""
        signature = llm_annotator.store_signature(self.review)
        if signature != self.signature:
            self.signature = signature
            self.load(keep_page=True)

    # -- data --------------------------------------------------------------

    def load(self, keep_page: bool = False) -> None:
        store = campaigns.load(self.review.folder)
        chosen = [c for c in store.campaigns if self.campaign.value in (ALL, c.id)]
        try:
            data = read_results(self.review.results_path)
        except Exception:
            data = None
        self.items = (
            llm_annotator.pending(self.review, data, chosen, self.grid())
            if data is not None and chosen
            else []
        )
        dims = sorted({p.dimension for p in self.items})
        self.dimension.set_options(
            {ALL: "All dimensions", **{d: d for d in dims}},
            value=self.dimension.value if self.dimension.value in dims else ALL,
        )
        self.guideline = annotations.review_guideline(self.review, self.grid())
        self.show_page(self.page if keep_page else 0)

    def shown(self) -> list[llm_annotator.Proposal]:
        return [
            p
            for p in self.items
            if self.dimension.value in (ALL, p.dimension)
            and self.confidence.value in (ALL, p.confidence)
            and (not self.evidence.value or p.evidence_found)
        ]

    # -- drawing ---------------------------------------------------------------

    def show_page(self, page: int) -> None:
        items = self.shown()
        pages = max(1, -(-len(items) // PAGE))
        self.page = max(0, min(page, pages - 1))
        self.summary.set_text(
            f"{len(items)} proposals shown ({len(self.items)} pending)."
            if self.items
            else "No proposal to validate."
        )
        self.page_label.set_text(f"Page {self.page + 1} / {pages}")
        self.prev.set_enabled(self.page > 0)
        self.next.set_enabled(self.page < pages - 1)
        page = items[self.page * PAGE : (self.page + 1) * PAGE]
        ids = [(p.paper_key, p.dimension, tuple(p.values), len(p.answers)) for p in page]
        if ids == self.drawn:
            return  # same cards: keep them (and any correction being typed)
        self.drawn = ids
        self.list.clear()
        with self.list:
            for proposal in page:
                self._card(proposal)

    def _card(self, proposal: llm_annotator.Proposal) -> None:
        with (
            ui.card()
            .classes("w-full gap-1")
            .props("flat bordered")
            .mark("validate-item")
        ):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.badge(proposal.dimension).props("color=primary")
                ui.label(proposal.title).classes("font-medium text-sm grow")
            with ui.row().classes("items-center gap-1 flex-wrap"):
                ui.label("Proposed:").classes("text-xs text-gray-500")
                for value in proposal.values:
                    ui.chip(value, icon="smart_toy").props("dense color=purple outline")
            for answer in proposal.answers:
                with (
                    ui.expansion(
                        f"{answer.get('model', '?')} · {answer.get('confidence') or '?'} "
                        f"confidence · {', '.join(answer.get('values') or []) or 'not addressed'}",
                        icon="smart_toy",
                    )
                    .classes("w-full text-sm")
                    .props("dense")
                ):
                    if answer.get("rationale"):
                        ui.label(answer["rationale"]).classes("text-sm italic")
                    for quote in answer.get("evidence") or []:
                        with ui.row().classes("items-start gap-1 no-wrap"):
                            ui.icon(
                                "check_circle" if quote.get("found") else "help",
                                color="positive" if quote.get("found") else "warning",
                            ).tooltip(
                                "Found in the text"
                                if quote.get("found")
                                else "Not found in the text: check it"
                            )
                            ui.label(f"“{quote.get('quote', '')}”").classes("text-xs")
                    if answer.get("text_source") == "abstract":
                        ui.label("Answered from the abstract only.").classes(
                            "text-xs text-warning"
                        )
            section = self.guideline.for_dimension(proposal.dimension)
            if section:
                with (
                    ui.expansion("Guideline", icon="menu_book")
                    .classes("w-full text-sm")
                    .props("dense")
                ):
                    ui.markdown(section).classes("text-sm")
            with ui.row().classes("items-center gap-2"):
                ui.button(
                    "Accept",
                    icon="check",
                    on_click=lambda p=proposal: self.decide(p, llm_annotator.ACCEPTED),
                ).props("dense no-caps color=positive").mark("validate-accept")
                options = list(
                    dict.fromkeys(
                        proposal.values
                        + dimension_values(self.grid(), proposal.dimension)
                    )
                )
                correction = (
                    ui.select(
                        options,
                        multiple=True,
                        value=[],
                        label="Your values",
                        new_value_mode="add-unique",
                    )
                    .props("dense outlined use-chips")
                    .classes("min-w-56")
                    .mark("validate-values")
                )
                ui.button(
                    "Correct",
                    icon="edit",
                    on_click=lambda p=proposal, c=correction: self.decide(
                        p, llm_annotator.CORRECTED, list(c.value or [])
                    ),
                ).props("dense outline no-caps").mark("validate-correct")
                ui.button(
                    "Reject",
                    icon="close",
                    on_click=lambda p=proposal: self.decide(p, llm_annotator.REJECTED),
                ).props("dense flat no-caps color=negative").mark("validate-reject")

    # -- actions ----------------------------------------------------------------

    async def decide(
        self, proposal, outcome: str, values: list[str] | None = None
    ) -> None:
        if outcome == llm_annotator.CORRECTED and not values:
            ui.notify("Choose or type your values first", type="warning")
            return
        try:
            await run.io_bound(
                llm_annotator.decide, self.review, proposal, outcome, values
            )
        except Exception as exc:
            show_error(
                "Cannot save the decision", exc, expected=isinstance(exc, ValueError)
            )
            return
        self.items.remove(proposal)
        self.show_page(self.page)
        ui.notify(f"{proposal.dimension}: {outcome}", type="positive")

    def accept_all(self) -> None:
        items = self.shown()
        if not items:
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Accept the {len(items)} proposals shown?").classes("font-bold")
            ui.label(
                "Their values become your codes. Narrow the filters first (dimension, "
                "high confidence, quotes found) to accept only what you checked."
            ).classes("text-sm")

            async def confirm() -> None:
                try:
                    await run.io_bound(
                        llm_annotator.decide_many,
                        self.review,
                        [(p, llm_annotator.ACCEPTED, None) for p in items],
                    )
                except Exception as exc:
                    show_error("Cannot save the decisions", exc)
                    return
                dialog.close()
                ui.notify(f"{len(items)} proposals accepted", type="positive")
                self.load()

            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Accept", icon="done_all", on_click=confirm).props(
                    "no-caps color=positive"
                ).mark("validate-accept-all-confirm")
        dialog.open()

    async def reconcile(self) -> None:
        try:
            counts = await run.io_bound(llm_annotator.reconcile, self.review)
        except Exception as exc:
            show_error("Cannot check the Zotero edits", exc)
            return
        ui.notify(
            ", ".join(f"{n} {what}" for what, n in counts.items())
            if counts
            else "No proposal was resolved outside SciLEx"
        )
        self.load()
