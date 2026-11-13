"""Screen step: table of papers, detail panel and include / exclude / maybe decisions."""

import contextlib
import json

from nicegui import background_tasks, events, run, ui

from scilex import paper_types, review_tags
from scilex.constants import doi_to_url
from scilex.gui.components import criteria_panel
from scilex.gui.components import eligibility_filter as elig
from scilex.gui.components.errors import show_error
from scilex.gui.services import criteria as criteria_service
from scilex.gui.services import members
from scilex.gui.services.screening import (
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

FILTER_OPTIONS = {
    FILTER_ALL: "All",
    FILTER_UNDECIDED: "Undecided",
    INCLUDE: "Included",
    EXCLUDE: "Excluded",
    MAYBE: "Maybe",
}
DECISION_COLOURS = {INCLUDE: "positive", EXCLUDE: "negative", MAYBE: "warning"}
KEY_DECISIONS = {"i": INCLUDE, "e": EXCLUDE, "m": MAYBE}
# Keys 1-4 set the paper type (PAPER_TYPE tag).
KEY_TYPES = {str(n): kind for n, kind in enumerate(paper_types.TYPES, start=1)}

# Bulk actions on the ticked papers: (label, icon, tag kind, add, button props).
BULK_ACTIONS = (
    ("Validate", "task_alt", review_tags.VALIDATED, True, "dense no-caps"),
    ("Unvalidate", "remove_done", review_tags.VALIDATED, False, "flat dense no-caps"),
    (
        "Delete",
        "delete_outline",
        review_tags.DELETED,
        True,
        "dense no-caps color=negative",
    ),
    ("Restore", "restore_from_trash", review_tags.DELETED, False, "flat dense no-caps"),
)
BULK_VERBS = {
    (review_tags.VALIDATED, True): "validated",
    (review_tags.VALIDATED, False): "unvalidated",
    (review_tags.DELETED, True): "deleted",
    (review_tags.DELETED, False): "restored",
}

COLLECTION = "collection"  # facet with its own toolbar selector
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
        "minWidth": 80,
        "filter": "agNumberColumnFilter",
    },
    {"field": "venue", "headerName": "Venue", "flex": 1, "minWidth": 100},
    {"field": "item_type", "headerName": "Type", "width": 130, "minWidth": 100},
    {
        "field": "paper_type",
        "headerName": "Paper type",
        "width": 150,
        "minWidth": 110,
        "headerTooltip": "PAPER_TYPE tag (else the default type); keys 1-4 change it",
    },
    {
        "field": "imported",
        "headerName": "Imported",
        "width": 120,
        "minWidth": 110,
        "headerTooltip": "Date the paper entered the review (empty: before tracking)",
    },
    {
        "field": "score",
        "headerName": "Score",
        # Room for the sort arrow and filter icon, or the header reads "S…".
        "width": 110,
        "minWidth": 110,
        "filter": "agNumberColumnFilter",
        "sort": "desc",
    },
    {
        "field": "citations",
        "headerName": "Cited",
        "width": 90,
        "minWidth": 90,
        "filter": "agNumberColumnFilter",
    },
    elig.CRITERIA_COLUMN,
    {
        "field": "status",
        "headerName": "Status",
        "width": 120,
        "minWidth": 100,
        "headerTooltip": "Annotation status: validated, deleted (discarded)…",
    },
    {
        "field": "decision",
        "headerName": "Decision",
        "width": 120,
        "minWidth": 110,
        ":cellClassRules": json.dumps(
            {
                "decision-include": "x === 'Include'",
                "decision-exclude": "x === 'Exclude'",
                "decision-maybe": "x === 'Maybe'",
            }
        ),
    },
]

GRID_CSS = """
.decision-include { color: #16a34a; font-weight: 600; }
.decision-exclude { color: #dc2626; font-weight: 600; }
.decision-maybe { color: #d97706; font-weight: 600; }
"""


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Screen step of ``review``."""
    ui.label("Screen").classes("text-2xl font-bold")
    container = ui.column().classes("w-full gap-3")
    with container, ui.row().classes("items-center gap-2") as loading:
        ui.spinner()
        ui.label("Loading papers…")

    async def load_and_build() -> None:
        # Reading the CSV and computing the paper keys must not block the loop.
        try:
            session = await run.io_bound(ScreeningSession, review)
            items = criteria_panel.load_criteria(review)
            verdicts = await run.io_bound(elig.compute_eligibility, session, items)
        except Exception as exc:
            if container.is_deleted:
                return  # the user left the page while the file was loading
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
            ui.add_css(GRID_CSS)
            ScreenPage(
                session,
                eligibility=(items, verdicts),
                me=getattr(ctx.profile, "orcid", "") or "",
            ).build()

    ui.timer(0, load_and_build, once=True)


class ScreenPage:
    """UI state of the Screen step; all decisions go through the session."""

    def __init__(
        self,
        session: ScreeningSession,
        eligibility: tuple[list, dict] | None = None,
        me: str = "",
    ):
        """Bind the page to an in-memory screening session.

        ``eligibility``: ``(criteria, verdicts)`` already computed (else here).
        ``me``: the user's ORCID iD, written by the bulk validate / delete.
        """
        self.session = session
        self.me = me
        self.checked: list[str] = []  # keys ticked in the grid
        self.decision_filter = FILTER_ALL
        self.query = ""
        self.facet_filters: dict[str, set[str]] = {}
        self.facet_selects: dict[str, ui.select] = {}
        self.facet_box: ui.expansion | None = None
        self._clearing = False
        self.current: str | None = None
        self.order: list[str] = []  # keys in the grid's displayed order
        if eligibility is None:
            self.criteria = criteria_panel.load_criteria(session.review)
            self.verdicts = elig.compute_eligibility(session, self.criteria)
        else:
            self.criteria, self.verdicts = eligibility
        self.eligibility_filter = elig.ELIGIBLE_ALL

    # -- layout ---------------------------------------------------------

    def build(self) -> None:
        """Create all elements."""
        self.counters = ui.label().classes("text-sm").mark("screen-counters")
        self.progress = ui.linear_progress(show_value=False).classes("w-full")
        with ui.row().classes("items-center gap-4 w-full"):
            ui.select(FILTER_OPTIONS, value=FILTER_ALL, on_change=self.on_filter).props(
                "dense outlined label=Decision"
            ).classes("w-40").mark("decision-filter").on(
                # Give the keys back to the shortcuts once a filter is chosen.
                "popup-hide",
                js_handler="() => document.activeElement?.blur()",
            )
            self.collection_filter()
            if elig.enabled(self.criteria):
                keys = [row["paper_key"] for row in self.session.rows]
                ui.select(
                    elig.options(keys, self.criteria, self.verdicts),
                    value=elig.ELIGIBLE_ALL,
                    label="Eligibility",
                    on_change=self.on_eligibility,
                ).props("dense outlined").classes("w-72").mark("screen-eligibility").on(
                    "popup-hide", js_handler="() => document.activeElement?.blur()"
                )
            ui.input(
                placeholder="Search title or abstract",
                on_change=self.on_search,
            ).props("dense outlined clearable debounce=300").classes("grow").mark(
                "text-search"
            )
        self.facet_panel()
        self.bulk_bar()
        ui.label(
            "Shortcuts: I include, E exclude, M maybe (then jump to the next "
            "undecided paper), "
            + ", ".join(f"{n} {kind}" for n, kind in KEY_TYPES.items())
            + " (switch a paper type on or off), ↑/↓ or K/J previous/next (disabled while typing "
            "in the note)"
        ).classes("text-xs text-gray-500")

        rows = self.filtered_rows()
        self.order = [row["paper_key"] for row in rows]
        self.grid = (
            ui.aggrid(
                {
                    "columnDefs": COLUMN_DEFS,
                    "rowData": rows,
                    ":getRowId": "(params) => params.data.paper_key",
                    # Checkboxes pick papers for the bulk actions; a click
                    # on a row opens it in the detail panel.
                    "rowSelection": {
                        "mode": "multiRow",
                        "checkboxes": True,
                        "headerCheckbox": True,
                        "selectAll": "filtered",
                        "enableClickSelection": False,
                    },
                    "defaultColDef": {
                        "sortable": True,
                        "filter": True,
                        "resizable": True,
                    },
                    "tooltipShowDelay": 500,
                }
            )
            .classes("w-full max-w-full")
            .style("height: max(260px, 42vh)")  # detail stays visible on small screens
            .mark("screen-grid")
        )
        self.grid.on("selectionChanged", self.on_checked)
        self.grid.on("cellClicked", self.on_row_click)
        self.grid.on("sortChanged", self.sync_order)
        self.grid.on("filterChanged", self.sync_order)

        self.detail_panel()
        self.orphans_panel()
        ui.keyboard(on_key=self.on_key, repeating=False)
        self.update_counters()
        if self.order:
            self.select(self.order[0])

    def collection_filter(self) -> None:
        """Zotero collection selector of the toolbar (a parent takes its subtree)."""
        options = self.session.collection_options()
        if not options:
            return
        labels = {
            path: ("No collection" if path == NONE_VALUE else path.replace("/", " › "))
            + f" ({count})"
            for path, count in options
        }
        select = (
            ui.select(
                labels,
                multiple=True,
                label="Zotero collection",
                with_input=True,
                clearable=True,
                on_change=lambda e: self.on_facet(COLLECTION, e.value),
            )
            .props("dense outlined use-chips")
            .classes("w-72")
            .tooltip("A collection includes its subcollections")
            .mark("collection-filter")
        )
        select.on("popup-hide", js_handler="() => document.activeElement?.blur()")
        self.facet_selects[COLLECTION] = select

    def facet_panel(self) -> None:
        """Filters on paper properties: type, origin, import date, keywords, tags…"""
        # Collections have their own selector in the toolbar.
        options = {
            facet: values
            for facet, values in self.session.facet_options().items()
            if facet != COLLECTION
        }
        if not options:
            return
        with (
            ui.expansion("Filters", icon="filter_list")
            .classes("w-full")
            .props("dense")
            .mark("facet-filters") as self.facet_box
        ):
            with (
                ui.element("div")
                .classes("grid gap-2 w-full")
                .style("grid-template-columns: repeat(auto-fill, minmax(230px, 1fr))")
            ):
                for facet, values in options.items():
                    select = (
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
                        .mark(f"facet-{facet}")
                    )
                    # Give the keys back to the shortcuts once values are chosen.
                    select.on(
                        "popup-hide", js_handler="() => document.activeElement?.blur()"
                    )
                    self.facet_selects[facet] = select
            ui.label(
                "Several values of one filter: any of them. Several filters: all of them."
            ).classes("text-xs text-gray-500")
            ui.button(
                "Clear filters", icon="filter_list_off", on_click=self.clear_facets
            ).props("flat dense").mark("clear-filters")

    @ui.refreshable_method
    def detail_panel(self) -> None:
        """Detail of the current paper with decision buttons and note."""
        if self.current is None:
            ui.label("No paper to show.").classes("text-gray-500")
            return
        detail = self.session.detail(self.current)
        decision = self.session.decision_of(self.current)
        with ui.card().classes("w-full gap-2").mark("detail-panel"):
            ui.label(detail["title"]).classes("text-lg font-bold")
            meta = [str(detail["year"] or ""), detail["venue"], detail["item_type"]]
            ui.label(" · ".join(part for part in meta if part)).classes(
                "text-sm text-gray-600"
            )
            if detail["authors"]:
                ui.label(detail["authors"]).classes("text-sm")
            url = doi_to_url(detail["doi"]) if detail["doi"] else None
            if url:
                ui.link(detail["doi"], url, new_tab=True).classes("text-sm")
            origin = detail["origin"] + (
                f", imported on {detail['imported']}" if detail["imported"] else ""
            )
            ui.label(f"Origin: {origin}").classes("text-xs text-gray-500")
            if detail["tags"]:
                ui.label(f"Tags: {detail['tags']}").classes("text-xs text-gray-500")
            self.type_picker(self.current)
            ui.label(detail["abstract"] or "No abstract.").classes(
                "text-sm whitespace-pre-wrap max-h-48 overflow-auto"
            )
            if self.criteria:
                key = self.current

                async def change(add: list[str], remove: list[str]) -> None:
                    if not await criteria_panel.write_tags(
                        self.session.review, self.session, key, add, remove
                    ):
                        return
                    if any(
                        t.startswith(f"{criteria_service.KEEP}:") for t in add + remove
                    ):
                        # An exception changed: judge the corpus again.
                        self.verdicts = await run.io_bound(
                            elig.compute_eligibility, self.session, self.criteria
                        )
                        self.refill(force=True)
                    self.detail_panel.refresh()

                criteria_panel.render_criteria(
                    self.session.record(key),
                    self.criteria,
                    change,
                    included=bool(decision and decision.decision == INCLUDE),
                )
            with ui.row().classes("items-center gap-2"):
                for label, value, marker in (
                    ("Include (I)", INCLUDE, "decide-include"),
                    ("Exclude (E)", EXCLUDE, "decide-exclude"),
                    ("Maybe (M)", MAYBE, "decide-maybe"),
                ):
                    button = ui.button(
                        label, on_click=lambda _, v=value: self.decide(v)
                    ).props(f"color={DECISION_COLOURS[value]}")
                    if not decision or decision.decision != value:
                        button.props("outline")
                    button.mark(marker)
                ui.button("Clear", on_click=lambda: self.decide(None)).props(
                    "flat"
                ).mark("decide-clear")
            self.note = (
                ui.textarea(
                    "Note (saved with the decision)",
                    value=decision.note if decision else "",
                )
                .props("outlined autogrow")
                .classes("w-full")
                .mark("decision-note")
            )
            self.note.on("blur", self.save_note)

    def type_picker(self, key: str) -> None:
        """Paper types of ``key``: one button per type, several can be on.

        Without a PAPER_TYPE tag, the default type is shown outlined; the first
        click sets the clicked type.
        """
        record = self.session.record(key)
        tagged = paper_types.types_of(record)
        default = None if tagged else paper_types.effective_type(record)
        with ui.row().classes("items-center gap-1").mark("paper-type-picker"):
            ui.label("Paper type").classes("text-sm font-medium")
            for n, kind in KEY_TYPES.items():
                button = (
                    ui.button(
                        f"{kind} ({n})",
                        on_click=lambda _, k=key, t=kind: self.toggle_type(k, t),
                    )
                    .props("dense no-caps size=sm")
                    .mark(f"paper-type-{n}")
                )
                if kind not in tagged:
                    button.props("outline" if kind == default else "flat")
                if kind == default:
                    button.tooltip("Default type (no PAPER_TYPE tag yet)")
            ui.label("several types allowed").classes("text-xs text-gray-500")

    async def toggle_type(self, key: str, kind: str) -> None:
        """Switch type ``kind`` of paper ``key`` on or off (PAPER_TYPE tags)."""
        record = self.session.record(key)
        tagged = paper_types.types_of(record)
        if not tagged:
            wanted = [kind]  # the first choice replaces the default
        elif kind in tagged:
            wanted = [t for t in tagged if t != kind]  # none left: the default
        else:
            wanted = [*tagged, kind]
        add, remove = paper_types.tag_changes(record, wanted)
        if not (add or remove):
            return
        if not await criteria_panel.write_tags(
            self.session.review, self.session, key, add, remove
        ):
            return
        self.grid.run_row_method(
            key, "setDataValue", "paper_type", self.session.row(key)["paper_type"]
        )
        if key == self.current:
            self.detail_panel.refresh()

    @ui.refreshable_method
    def orphans_panel(self) -> None:
        """Decisions whose paper is no longer in the results."""
        if not self.session.orphans:
            return
        with (
            ui.expansion(
                f"{len(self.session.orphans)} decision(s) on papers no longer in the results",
                icon="warning",
            )
            .classes("w-full")
            .mark("orphans")
        ):
            for key in list(self.session.orphans):
                decision = self.session.decision_of(key)
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{key} — {decision.decision}").classes("text-sm")
                    ui.button("Forget", on_click=lambda _, k=key: self.forget(k)).props(
                        "flat dense"
                    )

    # -- state updates --------------------------------------------------

    def update_counters(self) -> None:
        """Refresh the counters line and the progress bar."""
        counts = self.session.counts()
        self.counters.set_text(
            f"Included {counts[INCLUDE]} · Excluded {counts[EXCLUDE]} · "
            f"Maybe {counts[MAYBE]} · Undecided {counts['undecided']}"
        )
        if len(self.order) != counts["total"]:
            self.counters.set_text(
                self.counters.text
                + f" — showing {len(self.order)} of {counts['total']}"
            )
        total = counts["total"] or 1
        self.progress.set_value((counts["total"] - counts["undecided"]) / total)

    def select(self, key: str | None) -> None:
        """Make ``key`` the current paper (detail panel and grid selection)."""
        if key is None or key == self.current:
            return
        self.current = key
        self.detail_panel.refresh()
        script = (
            f"const g = getElement({self.grid.id}).api; const n = g.getRowNode({json.dumps(key)});"
            "if (n) { g.ensureNodeVisible(n);"
            " g.setFocusedCell(n.rowIndex, 'title'); }"
        )
        ui.run_javascript(script)

    def on_row_click(self, event: events.GenericEventArguments) -> None:
        """A row was clicked in the grid (not its checkbox): show it."""
        args = event.args or {}
        if str(args.get("colId", "")).startswith("ag-Grid-"):
            return  # the selection checkbox
        key = (args.get("data") or {}).get("paper_key")
        if key and key != self.current:
            self.save_note()
            self.current = key
            self.detail_panel.refresh()

    async def on_checked(self, _: events.GenericEventArguments) -> None:
        """The ticked papers changed."""
        rows = await self.grid.get_selected_rows()
        self.checked = [row["paper_key"] for row in rows]
        self.bulk_bar.refresh()

    # -- bulk actions -----------------------------------------------------

    @ui.refreshable_method
    def bulk_bar(self) -> None:
        """Validate or delete the ticked papers at once (with the user's ORCID)."""
        count = len(self.checked)
        with ui.row().classes("items-center gap-2 w-full").mark("bulk-bar"):
            ui.label(
                f"{count} paper(s) ticked"
                if count
                else "Tick papers to validate or delete several at once"
            ).classes("text-sm" + ("" if count else " text-gray-500")).mark(
                "bulk-count"
            )
            if not count:
                return
            for label, icon, kind, add, props in BULK_ACTIONS:
                button = (
                    ui.button(
                        label,
                        icon=icon,
                        on_click=lambda _, k=kind, a=add: self.bulk(k, a),
                    )
                    .props(props)
                    .mark(f"bulk-{label.lower()}")
                )
                if not self.me:
                    button.disable()
                    button.tooltip("Set your ORCID iD in your profile first")
            ui.button(
                "Untick all",
                on_click=lambda: self.grid.run_grid_method("deselectAll"),
            ).props("flat dense no-caps").mark("bulk-untick")
            ui.label(
                "Deleted papers stay in the corpus but leave the analyses "
                "(DELETED_BY tag); validation writes ANNOT_VALID_BY."
            ).classes("text-xs text-gray-500")

    async def bulk(self, kind: str, add: bool) -> None:
        """Add (or remove) ``<kind>:<my ORCID>`` on every ticked paper."""
        keys = list(self.checked)
        if not keys or not self.me:
            return
        mine = review_tags.tag(kind, self.me)
        changes = {key: ([mine], []) if add else ([], [mine]) for key in keys}
        try:
            new = await run.io_bound(
                members.apply_tags_by_key, self.session.review, changes
            )
        except Exception as exc:
            show_error("Cannot change the tags", exc)
            return
        for key, tags in new.items():
            self.session.set_tags(key, tags)
            self.grid.run_row_method(
                key, "setDataValue", "status", self.session.row(key)["status"]
            )
        ui.notify(f"{len(new)} paper(s) {BULK_VERBS[kind, add]}", type="positive")
        if self.current in new:
            self.detail_panel.refresh()

    async def sync_order(self, _: events.GenericEventArguments) -> None:
        """Remember the grid's displayed order (after sort / column filter)."""
        script = (
            f"const ids = []; getElement({self.grid.id}).api"
            ".forEachNodeAfterFilterAndSort((n) => ids.push(n.id)); return ids;"
        )
        with contextlib.suppress(TimeoutError):
            self.order = await ui.run_javascript(script)
            self.update_counters()

    def save_note(self, _=None) -> None:
        """Save the note of the current paper if it has a decision."""
        if self.current is None:
            return
        note = self.note.value or ""
        if self.session.update_note(self.current, note):
            ui.notify("Note saved", timeout=1000)
        elif note.strip() and self.session.decision_of(self.current) is None:
            # A note is stored with a decision: say so before it is lost.
            ui.notify(
                "Note not saved: choose Include, Exclude or Maybe first.",
                type="warning",
            )

    def decide(self, decision: str | None) -> None:
        """Apply ``decision`` to the current paper and go to the next undecided one."""
        key = self.current
        if key is None:
            return
        try:
            row = self.session.decide(key, decision, self.note.value or "")
        except Exception as exc:
            show_error("Cannot save the decision", exc)
            return
        self.update_counters()
        successor = self.session.next_undecided(self.order, key) if decision else None
        hidden = not (
            self.decision_filter == FILTER_ALL
            or self.decision_filter == (decision or FILTER_UNDECIDED)
        )
        if hidden:
            self.grid.run_grid_method(
                "applyTransaction", {"remove": [{"paper_key": key}]}
            )
            self.order = [k for k in self.order if k != key]
            self.update_counters()
        else:
            self.grid.run_row_method(key, "setDataValue", "decision", row["decision"])
        if successor is not None and successor != key:
            self.current = None  # force the detail panel to follow
            self.select(successor)
        else:
            self.detail_panel.refresh()
            if decision and self.session.counts()["undecided"] == 0:
                ui.notify("All papers are screened")

    def forget(self, key: str) -> None:
        """Delete an orphan decision."""
        self.session.forget(key)
        self.orphans_panel.refresh()

    # -- filters and keyboard -------------------------------------------

    def filtered_rows(self) -> list[dict]:
        """Grid rows passing every filter, with their Criteria column."""
        return [
            elig.criteria_cells(row, self.verdicts.get(row["paper_key"], {}))
            for row in self.session.visible_rows(
                self.decision_filter, self.query, self.facet_filters
            )
            if elig.matches(
                self.eligibility_filter, self.verdicts.get(row["paper_key"], {})
            )
        ]

    def refill(self, force: bool = False) -> None:
        """Reload the grid rows from the current filters."""
        rows = self.filtered_rows()
        order = [row["paper_key"] for row in rows]
        if order == self.order and not force:
            return  # same papers shown: do not resend every row to the browser
        self.order = order
        self.grid.options["rowData"] = rows
        self.grid.update()
        self.update_counters()
        if self.current not in self.order:
            self.current = None
            self.select(self.order[0] if self.order else None)
            if not self.order:
                self.detail_panel.refresh()

    def on_filter(self, event: events.ValueChangeEventArguments) -> None:
        """Decision filter changed."""
        self.decision_filter = event.value
        self.refill()

    def on_eligibility(self, event: events.ValueChangeEventArguments) -> None:
        """Eligibility filter changed."""
        self.eligibility_filter = event.value or elig.ELIGIBLE_ALL
        self.refill()

    def on_facet(self, facet: str, value) -> None:
        """A facet filter changed."""
        self.facet_filters[facet] = set(value or [])
        active = sum(
            1
            for name, chosen in self.facet_filters.items()
            if chosen and name != COLLECTION
        )
        if self.facet_box is not None:
            self.facet_box.text = f"Filters ({active} active)" if active else "Filters"
        if not self._clearing:
            self.refill()

    def clear_facets(self) -> None:
        """Remove every facet filter."""
        self._clearing = True
        try:
            for select in self.facet_selects.values():
                select.set_value([])
        finally:
            self._clearing = False
        self.refill()

    def on_search(self, event: events.ValueChangeEventArguments) -> None:
        """Search text changed."""
        self.query = event.value or ""
        self.refill()

    def move(self, step: int) -> None:
        """Select the previous (-1) or next (+1) paper."""
        if not self.order:
            return
        index = self.order.index(self.current) if self.current in self.order else -1
        target = self.order[min(max(index + step, 0), len(self.order) - 1)]
        self.save_note()
        self.select(target)

    def on_key(self, event: events.KeyEventArguments) -> None:
        """Keyboard shortcuts (the keyboard element ignores text inputs)."""
        if not event.action.keydown:
            return
        key = str(event.key.name).lower()
        if key in KEY_DECISIONS:
            self.decide(KEY_DECISIONS[key])
        elif key in KEY_TYPES and self.current is not None:
            background_tasks.create(self.toggle_type(self.current, KEY_TYPES[key]))
        elif key in ("arrowdown", "j"):
            self.move(1)
        elif key in ("arrowup", "k"):
            self.move(-1)
