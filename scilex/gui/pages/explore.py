"""Explore screen: browse the corpus, filter it, and read the notice of each paper.

Screening decisions are taken in ③ Screen; a notice can mark the paper as
validated against the grid or discard it (``ANNOT_VALID_BY`` / ``DELETED_BY``
tags with the user's ORCID iD, see :mod:`scilex.review_tags`). The filters are those of Screen
(document type, origin, import date, source, Zotero collection, keywords,
tags, LPWC and ORKG terms); a bar chart breaks the selection down by any of
them, and clicking a bar (or a value in a notice) filters on it.
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
from nicegui import events, run, ui

from scilex import review_tags
from scilex.constants import doi_to_url, is_valid
from scilex.gui.components.errors import show_error
from scilex.gui.pages.overview import _hbar
from scilex.gui.services import members
from scilex.gui.services.screening import (
    DECISION_LABELS,
    EXCLUDE,
    FACETS,
    FILTER_ALL,
    FILTER_UNDECIDED,
    INCLUDE,
    MAYBE,
    NONE_VALUE,
    ReviewFileError,
    ScreeningSession,
)
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext

DECISION_OPTIONS = {
    FILTER_ALL: "All",
    FILTER_UNDECIDED: "Undecided",
    INCLUDE: "Included",
    EXCLUDE: "Excluded",
    MAYBE: "Maybe",
}
COLUMN_DEFS = [
    {
        "field": "title",
        "headerName": "Title",
        "flex": 4,
        "minWidth": 160,
        "tooltipField": "title",
    },
    {
        "field": "year",
        "headerName": "Year",
        "width": 80,
        "filter": "agNumberColumnFilter",
    },
    {"field": "venue", "headerName": "Venue", "flex": 1, "minWidth": 100},
    {"field": "item_type", "headerName": "Type", "width": 130},
    {
        "field": "citations",
        "headerName": "Cited",
        "width": 90,
        "filter": "agNumberColumnFilter",
    },
    {"field": "decision", "headerName": "Decision", "width": 110},
]
# Notice sections: (label, facet) shown as clickable chips.
NOTICE_FACETS = (
    ("Search keywords", "collect_keywords"),
    ("Tasks (LPWC)", "lpwc_tasks"),
    ("Datasets (LPWC)", "lpwc_datasets"),
    ("Research problems (ORKG)", "orkg_problems"),
    ("Research fields (ORKG)", "orkg_fields"),
    ("Zotero collection", "collection"),
    ("Sources", "source"),
)
# Notice links: (label, column).
NOTICE_LINKS = (
    ("Papers with Code", "pwc_url"),
    ("Code", "github_repo"),
    ("Linked Papers With Code", "lpwc_paper"),
    ("ORKG", "orkg_paper"),
    ("PDF", "pdf_url"),
)
# Notice counts: (label, column).
NOTICE_COUNTS = (
    ("Citations", "nb_citation"),
    ("Semantic Scholar citations", "ss_citation_count"),
    ("Crossref citations", "crossref_cited_by"),
    ("References", "ss_reference_count"),
)
SELECTION_FILENAME = "explore_selection.csv"


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Explore screen of ``review``."""
    ui.label("Explore").classes("text-2xl font-bold")
    ui.label(
        "Browse the papers of the review: filter them, break the selection down by "
        "any property, and open the full notice of a paper. Click a bar or a value "
        "of a notice to filter on it."
    ).classes("text-gray-500")
    container = ui.column().classes("w-full gap-3")
    with container, ui.row().classes("items-center gap-2") as loading:
        ui.spinner()
        ui.label("Loading papers…")

    async def load() -> None:
        try:
            session = await run.io_bound(ScreeningSession, review)
        except Exception as exc:
            if container.is_deleted:
                return
            loading.delete()
            with container:
                show_error(
                    "Cannot load the results",
                    exc,
                    expected=isinstance(exc, ReviewFileError),
                )
            return
        if container.is_deleted:
            return
        loading.delete()
        with container:
            ExplorePage(review, session, ctx.profile).build()

    ui.timer(0, load, once=True)


def _split_tag(tag: str) -> tuple[str, str]:
    """``"TASK:Ner"`` -> ``("TASK", "Ner")``; a plain tag has no dimension."""
    dimension, sep, value = tag.partition(":")
    return (dimension, value) if sep and dimension and value else ("", tag)


class ExplorePage:
    """UI state of the Explore screen."""

    def __init__(self, review: Review, session: ScreeningSession, profile=None):
        """Bind the page to the papers of ``review``; ``profile``: the app user."""
        self.review = review
        self.me = getattr(profile, "orcid", "") or ""
        self.session = session
        self.options = session.facet_options()
        self.decision_filter = FILTER_ALL
        self.query = ""
        self.filters: dict[str, set[str]] = {}
        self.selects: dict[str, ui.select] = {}
        self.order: list[str] = []
        self.current: str | None = None
        self.breakdown = next(iter(self.options), None)
        self._quiet = False

    # -- layout ---------------------------------------------------------

    def build(self) -> None:
        """Create all elements."""
        with ui.row().classes("items-center gap-3 w-full"):
            ui.select(
                DECISION_OPTIONS,
                value=FILTER_ALL,
                label="Decision",
                on_change=self.on_decision,
            ).props("dense outlined").classes("w-36").mark("explore-decision")
            ui.input(
                placeholder="Search title or abstract", on_change=self.on_search
            ).props("dense outlined clearable debounce=300").classes("grow").mark(
                "explore-search"
            )
            self.count = ui.label().classes("text-sm font-medium").mark("explore-count")
            ui.button(
                "Clear filters", icon="filter_list_off", on_click=self.clear
            ).props("flat dense no-caps").mark("explore-clear")
            ui.button(
                "Save selection", icon="download", on_click=self.save_selection
            ).props("outline dense no-caps").tooltip(
                f"Write the selected papers to {SELECTION_FILENAME}"
            ).mark("explore-save")
        self.filter_grid()
        with ui.card().classes("w-full gap-1"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Break down by").classes("text-sm font-medium")
                ui.select(
                    {facet: FACETS[facet] for facet in self.options},
                    value=self.breakdown,
                    on_change=self.on_breakdown,
                ).props("dense outlined").classes("w-64").mark("explore-breakdown")
            self.chart = (
                ui.echart(_hbar({}), on_point_click=self.on_bar_click)
                .classes("w-full")
                .style("height: 280px")
                .mark("explore-chart")
            )
        with ui.element("div").classes("w-full grid gap-3 lg:grid-cols-5"):
            with ui.element("div").classes("lg:col-span-3 min-w-0"):
                self.grid = (
                    ui.aggrid(
                        {
                            "columnDefs": COLUMN_DEFS,
                            "rowData": [],
                            ":getRowId": "(params) => params.data.paper_key",
                            "rowSelection": {
                                "mode": "singleRow",
                                "checkboxes": False,
                                "enableClickSelection": True,
                            },
                            "defaultColDef": {"sortable": True, "resizable": True},
                            "tooltipShowDelay": 500,
                        }
                    )
                    .classes("w-full")
                    .style("height: max(320px, 60vh)")
                    .mark("explore-grid")
                )
                self.grid.on("selectionChanged", self.on_grid_selection)
            with ui.element("div").classes("lg:col-span-2 min-w-0"):
                self.notice()
        self.refill()

    def filter_grid(self) -> None:
        """One multi-select per facet that has values in this review."""
        if not self.options:
            return
        with (
            ui.element("div")
            .classes("grid gap-2 w-full")
            .style("grid-template-columns: repeat(auto-fill, minmax(230px, 1fr))")
        ):
            for facet, values in self.options.items():
                self.selects[facet] = (
                    ui.select(
                        {value: f"{value} ({count})" for value, count in values},
                        multiple=True,
                        label=FACETS[facet],
                        with_input=True,
                        clearable=True,
                        on_change=lambda e, f=facet: self.on_facet(f, e.value),
                    )
                    .props("dense outlined use-chips")
                    .classes("w-full")
                    .mark(f"explore-facet-{facet}")
                )

    @ui.refreshable_method
    def notice(self) -> None:
        """Full record of the current paper."""
        if self.current is None:
            with ui.card().classes("w-full"):
                ui.label("Select a paper to read its notice.").classes("text-gray-500")
            return
        key = self.current
        record = self.session.record(key)
        detail = self.session.detail(key)
        facets = self.session.facets_of(key)
        decision = self.session.decision_of(key)
        with ui.card().classes("w-full gap-2").mark("explore-notice"):
            with ui.row().classes("items-center gap-1 w-full"):
                ui.button(icon="chevron_left", on_click=lambda: self.move(-1)).props(
                    "flat dense round"
                ).tooltip("Previous paper").mark("explore-prev")
                position = self.order.index(key) + 1 if key in self.order else 0
                ui.label(f"{position} / {len(self.order)}").classes(
                    "text-xs text-gray-500"
                )
                ui.button(icon="chevron_right", on_click=lambda: self.move(1)).props(
                    "flat dense round"
                ).tooltip("Next paper").mark("explore-next")
                ui.space()
                if decision:
                    ui.badge(DECISION_LABELS[decision.decision]).props("outline")
            ui.label(detail["title"] or "(no title)").classes("text-lg font-bold")
            if detail["authors"]:
                ui.label(detail["authors"]).classes("text-sm")
            meta = [
                str(detail["year"] or ""),
                detail["venue"],
                next(iter(facets["item_type"])),
            ]
            ui.label(" · ".join(m for m in meta if m and m != NONE_VALUE)).classes(
                "text-sm text-gray-600"
            )
            with ui.row().classes("gap-3"):
                if detail["doi"] and doi_to_url(detail["doi"]):
                    ui.link(
                        detail["doi"], doi_to_url(detail["doi"]), new_tab=True
                    ).classes("text-sm")
                url = record.get("url")
                if is_valid(url) and str(url).startswith("http"):
                    ui.link("Web page", str(url), new_tab=True).classes("text-sm")
                for label, column in NOTICE_LINKS:
                    value = record.get(column)
                    if is_valid(value) and str(value).startswith("http"):
                        ui.link(label, str(value).split(";")[0], new_tab=True).classes(
                            "text-sm"
                        )
            origin = detail["origin"] + (
                f", imported on {detail['imported']}" if detail["imported"] else ""
            )
            ui.label(f"Origin: {origin}").classes("text-xs text-gray-500")
            self._workflow_row(key, record.get("tags"))
            counts = [
                f"{label}: {int(float(record[column]))}"
                for label, column in NOTICE_COUNTS
                if is_valid(record.get(column)) and _is_number(record[column])
            ]
            if counts:
                ui.label(" · ".join(counts)).classes("text-xs text-gray-500")
            with ui.expansion("Abstract", value=True).classes("w-full").props("dense"):
                ui.label(detail["abstract"] or "No abstract.").classes(
                    "text-sm whitespace-pre-wrap"
                )
            for label, facet in NOTICE_FACETS:
                values = sorted(facets[facet] - {NONE_VALUE})
                if values:
                    self._chips(label, facet, values)
            tags = sorted(facets["tags"] - {NONE_VALUE})
            if tags:
                self._tag_table(tags)
            if decision and decision.note:
                ui.label(f"Screening note: {decision.note}").classes("text-sm italic")

    def _workflow_row(self, key: str, tags) -> None:
        """Who annotates / validated / discarded the paper, and the user's actions."""
        state = review_tags.workflow(tags)
        with ui.row().classes("items-center gap-2").mark("explore-workflow"):
            ui.badge(state.status).props("outline").mark("explore-status")
            parts = []
            if state.assigned:
                parts.append("assigned to " + ", ".join(state.assigned))
            if state.validated_by:
                parts.append("validated by " + ", ".join(state.validated_by))
            if state.deleted_by:
                parts.append("discarded by " + ", ".join(state.deleted_by))
            if parts:
                ui.label("; ".join(parts)).classes("text-xs text-gray-600")
            if not self.me:
                return
            mine_valid = review_tags.tag(review_tags.VALIDATED, self.me)
            mine_deleted = review_tags.tag(review_tags.DELETED, self.me)
            validated = self.me in state.validated_by
            ui.button(
                "Unvalidate" if validated else "Validated by me",
                icon="task_alt",
                on_click=lambda: self.change_tags(
                    key,
                    [] if validated else [mine_valid],
                    [mine_valid] if validated else [],
                ),
            ).props("flat dense no-caps").mark("explore-validate")
            deleted = self.me in state.deleted_by
            ui.button(
                "Restore" if deleted else "Discard",
                icon="restore_from_trash" if deleted else "delete_outline",
                on_click=lambda: self.change_tags(
                    key,
                    [] if deleted else [mine_deleted],
                    [mine_deleted] if deleted else [],
                ),
            ).props("flat dense no-caps").tooltip(
                "Discarded papers stay in the corpus but leave the analyses (DELETED_BY tag)"
            ).mark("explore-discard")

    async def change_tags(self, key: str, add: list[str], remove: list[str]) -> None:
        """Write workflow tags of one paper (pushed to Zotero by the sync)."""
        try:
            new = await run.io_bound(
                members.apply_tags_by_key, self.review, {key: (add, remove)}
            )
        except Exception as exc:
            show_error("Cannot change the tags", exc)
            return
        if key in new:
            self.session.set_tags(key, new[key])
        self.notice.refresh()

    def _chips(self, label: str, facet: str, values: list[str]) -> None:
        with ui.column().classes("gap-0"):
            ui.label(label).classes("text-xs font-medium text-gray-600")
            with ui.row().classes("gap-1"):
                for value in values:
                    ui.chip(
                        value,
                        on_click=lambda _, f=facet, v=value: self.add_filter(f, v),
                    ).props("dense outline clickable").tooltip("Filter on this value")

    def _tag_table(self, tags: list[str]) -> None:
        """Tags grouped by annotation dimension (``DIMENSION:value``)."""
        grouped: dict[str, list[str]] = {}
        for tag in tags:
            dimension, _ = _split_tag(tag)
            grouped.setdefault(dimension, []).append(tag)
        with (
            ui.expansion(f"Tags ({len(tags)})", value=True)
            .classes("w-full")
            .props("dense")
        ):
            for dimension in sorted(grouped, key=lambda d: (d == "", d)):
                with ui.row().classes("items-center gap-1"):
                    ui.label(dimension or "Other").classes(
                        "text-xs font-medium text-gray-600 w-40"
                    )
                    for tag in grouped[dimension]:
                        ui.chip(
                            _split_tag(tag)[1],
                            on_click=lambda _, t=tag: self.add_filter("tags", t),
                        ).props("dense outline clickable").tooltip(tag)

    # -- filters --------------------------------------------------------

    def refill(self) -> None:
        """Apply the filters to the grid, the counter and the chart."""
        rows = self.session.visible_rows(self.decision_filter, self.query, self.filters)
        self.order = [row["paper_key"] for row in rows]
        self.grid.options["rowData"] = rows
        self.grid.update()
        total = len(self.session.rows)
        self.count.set_text(f"{len(rows)} of {total} papers")
        self.draw_chart()
        if self.current not in self.order:
            self.current = self.order[0] if self.order else None
        self.notice.refresh()

    def draw_chart(self) -> None:
        if self.breakdown is None:
            self.chart.set_visibility(False)
            return
        counts = dict(self.session.facet_counts(self.order, self.breakdown))
        self.chart.options.clear()
        self.chart.options.update(_hbar(counts, total=None))
        self.chart.update()

    def on_decision(self, event: events.ValueChangeEventArguments) -> None:
        self.decision_filter = event.value
        self.refill()

    def on_search(self, event: events.ValueChangeEventArguments) -> None:
        self.query = event.value or ""
        self.refill()

    def on_facet(self, facet: str, value) -> None:
        self.filters[facet] = set(value or [])
        if not self._quiet:
            self.refill()

    def on_breakdown(self, event: events.ValueChangeEventArguments) -> None:
        self.breakdown = event.value
        self.draw_chart()

    def on_bar_click(self, event: events.EChartPointClickEventArguments) -> None:
        if self.breakdown and event.name != "Other":
            self.add_filter(self.breakdown, event.name)

    def add_filter(self, facet: str, value: str) -> None:
        """Add ``value`` to the filter of ``facet`` (from a bar or a chip)."""
        select = self.selects.get(facet)
        if select is None:  # facet hidden: one value for all papers
            return
        chosen = list(select.value or [])
        if value not in chosen:
            select.set_value([*chosen, value])  # triggers on_facet

    def clear(self) -> None:
        self._quiet = True
        try:
            for select in self.selects.values():
                select.set_value([])
        finally:
            self._quiet = False
        self.refill()

    # -- navigation -----------------------------------------------------

    async def on_grid_selection(self, _: events.GenericEventArguments) -> None:
        row = await self.grid.get_selected_row()
        if row and row["paper_key"] != self.current:
            self.current = row["paper_key"]
            self.notice.refresh()

    def move(self, step: int) -> None:
        if not self.order:
            return
        index = self.order.index(self.current) if self.current in self.order else -1
        self.current = self.order[min(max(index + step, 0), len(self.order) - 1)]
        self.notice.refresh()
        script = (
            f"const g = getElement({self.grid.id}).api;"
            f"const n = g.getRowNode({json.dumps(self.current)});"
            "if (n) { n.setSelected(true); g.ensureNodeVisible(n); }"
        )
        ui.run_javascript(script)

    # -- export ---------------------------------------------------------

    def save_selection(self) -> None:
        """Write the selected papers (all columns) next to the results."""
        if not self.order:
            ui.notify("No paper selected.", type="warning")
            return
        frame = pd.DataFrame([self.session.record(key) for key in self.order])
        path = self.review.collection_dir / SELECTION_FILENAME
        try:
            frame.to_csv(path, sep=";", index=False)
        except OSError as exc:
            show_error("Cannot write the selection", exc, expected=True)
            return
        stamp = datetime.now().strftime("%H:%M")
        ui.notify(f"{len(frame)} papers written to {path} ({stamp})", type="positive")


def _is_number(value) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
