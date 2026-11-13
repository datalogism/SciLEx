"""Eligibility criteria: the review's inclusion / exclusion table, as testable filters.

Each criterion is one card: its exclusion (EC), inclusion (IC) and exception
(Ex) texts, as in the review's protocol, and the rule SciLEx checks. "Test"
shows the papers it would exclude; "Apply the criteria" tags them
``DELETED_BY:filter:<id> <cause>`` (kept in the corpus, left out of the
analyses). A person keeps a paper despite a criterion with ``KEEP:<id>``.
"""

from __future__ import annotations

from nicegui import run, ui

from scilex.gui.components.dialogs import one_shot_dialog
from scilex.gui.components.errors import show_error
from scilex.gui.services import criteria as service
from scilex.gui.services import screening
from scilex.gui.services.extend import read_results
from scilex.gui.services.workspace import Review, Workspace
from scilex.gui.state import AppContext

SAMPLE = 50  # papers listed per test


def _main(review: Review) -> dict:
    try:
        return Workspace.load_config(review).main
    except Exception:  # an invalid scilex.yml: defaults without its values
        return {}


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Eligibility criteria step."""
    ui.label("Eligibility criteria").classes("text-2xl font-bold")
    ui.label(
        "The inclusion and exclusion criteria of the review, as in its protocol, "
        "each with a rule SciLEx can check. Test a criterion to see the papers it "
        "excludes, then apply the criteria: excluded papers are tagged "
        "DELETED_BY:filter:<criterion> (kept in the corpus, left out of the "
        "analyses, shared through Zotero). Tag a paper KEEP:<criterion> to keep it "
        "as an exception; papers included in ③ Screen are never excluded."
    ).classes("text-gray-500")
    try:
        items = service.load(review.folder, _main(review))
    except Exception as exc:
        show_error("Cannot read criteria.yml", exc)
        return
    cards = ui.column().classes("w-full gap-3")

    def draw() -> None:
        cards.clear()
        with cards:
            for criterion in items:
                _card(review, criterion, items, draw)

    draw()

    def add() -> None:
        used = {c.id for c in items}
        number = next(n for n in range(1, 100) if f"C{n}" not in used)
        items.append(
            service.Criterion(
                f"C{number}", "New criterion", "text", params={"pattern": ""}
            )
        )
        draw()

    def save() -> bool:
        try:
            service.save(review.folder, items)
        except ValueError as exc:
            show_error("Cannot save the criteria", exc, expected=True)
            return False
        ui.notify("Criteria saved", type="positive")
        return True

    async def apply() -> None:
        if not save():
            return
        enabled = [c.id for c in items if c.enabled]
        with one_shot_dialog() as dialog, ui.card().mark("criteria-confirm"):
            ui.label(
                f"Apply {', '.join(enabled) or 'no criterion'}? Excluded papers get "
                "DELETED_BY:filter:<criterion>; papers that now pass lose that tag."
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def go() -> None:
                    dialog.close()
                    try:
                        counts = await run.io_bound(service.apply, review, items)
                    except Exception as exc:
                        show_error("Cannot apply the criteria", exc)
                        return
                    ui.notify(
                        "Excluded: "
                        + ", ".join(f"{cid} {n}" for cid, n in counts.items()),
                        type="positive",
                        multi_line=True,
                    )

                ui.button("Apply", on_click=go).mark("criteria-apply-confirm")
        dialog.open()

    def export() -> None:
        table = service.markdown_table(items)
        with one_shot_dialog() as dialog, ui.card().classes("w-[48rem]"):
            ui.label("Criteria table (Markdown)").classes("font-bold")
            ui.code(table, language="markdown").classes("w-full").mark("criteria-table")
            ui.button("Close", on_click=dialog.close).props("flat")
        dialog.open()

    with ui.row().classes("gap-2"):
        ui.button("Add a criterion", icon="add", on_click=add).props("outline").mark(
            "criteria-add"
        )
        ui.button("Save", icon="save", on_click=save).props("outline").mark(
            "criteria-save"
        )
        ui.button("Apply the criteria", icon="rule", on_click=apply).mark(
            "criteria-apply"
        )
        ui.button("Table for the paper", icon="table_view", on_click=export).props(
            "flat"
        ).mark("criteria-export")


def _card(review: Review, criterion: service.Criterion, items: list, redraw) -> None:
    with ui.card().classes("w-full gap-1").mark(f"criterion-{criterion.id}"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.switch(value=criterion.enabled).bind_value(criterion, "enabled").mark(
                f"criterion-enabled-{criterion.id}"
            )
            ui.input("Id").bind_value(criterion, "id").classes("w-20")
            ui.input("Criterion").bind_value(criterion, "name").classes("grow")
            ui.select(service.KINDS, label="Rule").bind_value(
                criterion, "kind"
            ).classes("w-72").on_value_change(lambda _: redraw())
            ui.button(
                icon="delete",
                on_click=lambda: (items.remove(criterion), redraw()),
            ).props("flat round dense")
        with ui.grid(columns=3).classes("w-full gap-2"):
            ui.textarea("Exclusion (EC)").bind_value(criterion, "exclusion").props(
                "autogrow dense"
            )
            ui.textarea("Inclusion (IC)").bind_value(criterion, "inclusion").props(
                "autogrow dense"
            )
            ui.textarea("Exceptions (Ex)").bind_value(criterion, "exceptions").props(
                "autogrow dense"
            )
        _params(criterion)
        result_area = ui.column().classes("w-full gap-1")

        async def run_test() -> None:
            try:
                data = await run.io_bound(read_results, review.results_path)
                included = {
                    key
                    for key, d in screening.load_decisions(review).items()
                    if d.decision == screening.INCLUDE
                }
                result = await run.io_bound(service.test, criterion, data, included)
            except Exception as exc:
                show_error("Cannot test this criterion", exc)
                return
            result_area.clear()
            with result_area:
                ui.label(result.message()).classes("text-sm font-bold").mark(
                    f"criterion-result-{criterion.id}"
                )
                for note in result.notes:
                    ui.label(note).classes("text-xs text-gray-600")
                for title, papers in (
                    ("Excluded", result.excluded),
                    ("Kept by an exception", result.spared),
                ):
                    if not papers:
                        continue
                    with ui.expansion(f"{title} ({len(papers)})").classes("w-full"):
                        for paper in papers[:SAMPLE]:
                            ui.label(f"{paper.title[:110]} — {paper.cause}").classes(
                                "text-xs"
                            )
                        if len(papers) > SAMPLE:
                            ui.label(f"… and {len(papers) - SAMPLE} more").classes(
                                "text-xs text-gray-500"
                            )

        ui.button("Test", icon="science", on_click=run_test).props(
            "outline dense"
        ).mark(f"criterion-test-{criterion.id}")


def _params(criterion: service.Criterion) -> None:
    """The settings of the criterion's rule."""
    params = criterion.params
    kind = criterion.kind
    with ui.row().classes("items-center gap-3"):
        if kind == "period":
            ui.number("From", precision=0).bind_value(params, "start")
            ui.number("To", precision=0).bind_value(params, "end")
            params.setdefault("exclude_unknown", False)
            ui.checkbox("Exclude papers without a year").bind_value(
                params, "exclude_unknown"
            )
        elif kind == "coherence":
            text = "\n".join(" OR ".join(g) for g in params.get("groups") or [])
            area = ui.textarea(
                "Term groups (one per line, terms separated by OR): each line "
                "must match",
                value=text,
            ).classes("w-[40rem]")

            def update(event) -> None:
                params["groups"] = [
                    [t.strip() for t in line.split(" OR ") if t.strip()]
                    for line in (event.value or "").splitlines()
                    if line.strip()
                ]

            area.on_value_change(update)
        elif kind == "language":
            ui.input(
                "Languages (codes, comma separated)",
                value=", ".join(params.get("languages") or ["en"]),
            ).on_value_change(
                lambda e: params.__setitem__(
                    "languages",
                    [x.strip() for x in (e.value or "").split(",") if x.strip()],
                )
            )
        elif kind == "access":
            params.setdefault("exclude_unknown", False)
            ui.checkbox("Also exclude papers whose access is unknown").bind_value(
                params, "exclude_unknown"
            )
        elif kind == "quality":
            rules = params.get("quality_filters") or {}
            active = [k for k, v in rules.items() if v not in (None, False, [], 0)]
            ui.label(
                "Rules of scilex.yml (quality_filters, edited in ① Configure): "
                + (", ".join(active) if active else "none set")
                + ". The year range is C1's job."
            ).classes("text-xs text-gray-600")
        elif kind == "metric":
            _metric_params(params)
        elif kind == "text":
            params.setdefault("pattern", "")
            ui.input("Pattern (regular expression)").bind_value(
                params, "pattern"
            ).classes("w-96")
        from scilex.paper_types import TYPES

        ui.select(
            list(TYPES), multiple=True, label="Exception: keep these paper types"
        ).bind_value(criterion, "keep_types").classes("w-80").props("use-chips")


def _metric_params(params: dict) -> None:
    """Conditions on metrics: citations, PageRank, quality, venue rank…"""
    params.setdefault("match", "all")
    params.setdefault("missing", "keep")
    params.setdefault("conditions", [])
    with ui.column().classes("w-full gap-1"):
        with ui.row().classes("items-center gap-3"):
            ui.select(
                {
                    "all": "Exclude when one condition fails",
                    "any": "Exclude when every condition fails",
                },
                label="Combine",
            ).bind_value(params, "match").classes("w-72")
            ui.select(
                {
                    "keep": "Keep papers whose metric is unknown",
                    "exclude": "Exclude papers whose metric is unknown",
                },
                label="Unknown values",
            ).bind_value(params, "missing").classes("w-80")

        @ui.refreshable
        def conditions() -> None:
            for condition in params["conditions"]:
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.select(
                        {k: label for k, (label, _) in service.METRICS.items()},
                        label="Metric",
                    ).bind_value(condition, "metric").classes("w-80").on_value_change(
                        lambda _: conditions.refresh()
                    )
                    if condition.get("metric") == "column":
                        condition.setdefault("column", "")
                        ui.input("Column").bind_value(condition, "column").classes(
                            "w-48"
                        )
                    ui.select(service.OPERATORS, label="Rule").bind_value(
                        condition, "op"
                    ).classes("w-72").on_value_change(lambda _: conditions.refresh())
                    if condition.get("op") != "age_aware":
                        label = {
                            "top_percent": "%",
                            "top_n": "N",
                        }.get(condition.get("op"), "Value")
                        ui.number(label).bind_value(condition, "value").classes("w-28")
                    ui.button(
                        icon="close",
                        on_click=lambda _, c=condition: (
                            params["conditions"].remove(c),
                            conditions.refresh(),
                        ),
                    ).props("flat round dense")
            ui.button(
                "Add a condition",
                icon="add",
                on_click=lambda: (
                    params["conditions"].append(
                        {"metric": "citations", "op": ">=", "value": 1}
                    ),
                    conditions.refresh(),
                ),
            ).props("flat dense no-caps").mark("criterion-add-condition")

        conditions()
        ui.label(
            "Citations come from the collection or Enrich › Citations; citations "
            "per year, from the corpus and PageRank from Enrich › Citation metrics. "
            '"Top %" is computed among the papers whose metric is known. '
            '"Enough for its age" asks 0 citations up to 18 months, then 1, 3, '
            "5-8, 10+ as the paper gets older."
        ).classes("text-xs text-gray-600")
