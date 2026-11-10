"""Overview screen: the first page of a review, a visual summary of its state."""

from __future__ import annotations

from datetime import datetime

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.services import overview as service
from scilex.gui.services.workspace import Review
from scilex.gui.state import AppContext

# Reference palette of the dataviz method (validated; light mode).
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
TEXT_PRIMARY, TEXT_SECONDARY, GRID = "#0b0b0b", "#52514e", "#e4e3de"
MAX_BARS = 12  # longer category lists fold into "Other"

_AXIS = {
    "axisLine": {"lineStyle": {"color": GRID}},
    "axisTick": {"show": False},
    "axisLabel": {"color": TEXT_SECONDARY},
    "splitLine": {"lineStyle": {"color": GRID}},
}


def _fold(counts: dict[str, int], limit: int = MAX_BARS) -> dict[str, int]:
    """Keep the ``limit - 1`` largest categories and sum the rest into "Other"."""
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    if len(items) <= limit:
        return dict(items)
    head, tail = items[: limit - 1], items[limit - 1 :]
    return {**dict(head), "Other": sum(v for _, v in tail)}


def _hbar(counts: dict[str, int], total: int | None = None) -> dict:
    """Horizontal bars, one hue (the axis labels carry identity), largest on top."""
    counts = _fold(counts)
    labels = list(counts)[::-1]
    values = [counts[k] for k in labels]
    suffix = f" / {total}" if total else ""
    return {
        "grid": {"left": 8, "right": 48, "top": 8, "bottom": 8, "containLabel": True},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c}" + suffix},
        "xAxis": {"type": "value", **_AXIS, "max": total} if total else {"type": "value", **_AXIS},
        "yAxis": {
            "type": "category",
            "data": labels,
            **_AXIS,
            "splitLine": {"show": False},
            "axisLabel": {"color": TEXT_SECONDARY, "width": 220, "overflow": "truncate"},
        },
        "series": [
            {
                "type": "bar",
                "data": values,
                "itemStyle": {"color": BLUE, "borderRadius": [0, 4, 4, 0]},
                "barMaxWidth": 18,
                "label": {"show": True, "position": "right", "color": TEXT_SECONDARY},
                "emphasis": {"itemStyle": {"color": "#256abf"}},
            }
        ],
    }


def _years(by_year: dict[int, int]) -> dict:
    years = list(range(min(by_year), max(by_year) + 1)) if by_year else []
    return {
        "grid": {"left": 8, "right": 8, "top": 16, "bottom": 8, "containLabel": True},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "category", "data": [str(y) for y in years], **_AXIS,
                  "splitLine": {"show": False}},
        "yAxis": {"type": "value", **_AXIS, "minInterval": 1},
        "series": [
            {
                "name": "Papers",
                "type": "bar",
                "data": [by_year.get(y, 0) for y in years],
                "itemStyle": {"color": BLUE, "borderRadius": [4, 4, 0, 0]},
                "barMaxWidth": 24,
            }
        ],
    }


def _screening(counts: dict[str, int]) -> dict:
    """One 100 % bar split by decision (legend + direct labels, 2px surface gaps)."""
    colors = [AQUA, YELLOW, ORANGE, "#c3c2b7"]
    total = max(sum(counts.values()), 1)
    return {
        "grid": {"left": 8, "right": 8, "top": 40, "bottom": 8, "containLabel": True},
        "legend": {"top": 0, "textStyle": {"color": TEXT_SECONDARY}, "itemWidth": 12},
        "tooltip": {"trigger": "item", "formatter": "{a}: {c} papers"},
        "xAxis": {"type": "value", "max": total, "show": False},
        "yAxis": {"type": "category", "data": [""], "show": False},
        "series": [
            {
                "name": label,
                "type": "bar",
                "stack": "decisions",
                "data": [value],
                "barWidth": 28,
                "itemStyle": {"color": color, "borderColor": "#fcfcfb", "borderWidth": 2},
                "label": {
                    "show": value / total >= 0.08,
                    "color": TEXT_PRIMARY,
                    "formatter": f"{value}",
                },
            }
            for (label, value), color in zip(counts.items(), colors, strict=False)
        ],
    }


def _history(history: list[service.Snapshot]) -> dict:
    """Annotated vs still-pending papers over time (two series: legend + end labels)."""

    def point(snapshot, value):
        return [snapshot.at, value]

    def series(name, color, key):
        return {
            "name": name,
            "type": "line",
            "step": "end",
            "data": [point(s, getattr(s, key)) for s in history],
            "lineStyle": {"width": 2, "color": color},
            "itemStyle": {"color": color},
            "symbolSize": 8,
            "endLabel": {"show": True, "color": TEXT_SECONDARY, "formatter": "{a}: {@[1]}"},
        }

    return {
        "grid": {"left": 8, "right": 150, "top": 40, "bottom": 8, "containLabel": True},
        "legend": {"top": 0, "textStyle": {"color": TEXT_SECONDARY}},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "time", **_AXIS, "splitLine": {"show": False}},
        "yAxis": {"type": "value", **_AXIS, "minInterval": 1, "name": "papers",
                  "nameTextStyle": {"color": TEXT_SECONDARY}},
        "series": [
            series("Annotated", BLUE, "annotated"),
            series("Still to annotate (DIMENSION:?)", ORANGE, "pending"),
        ],
    }


def _tile(label: str, value: str, detail: str = "", marker: str = "") -> None:
    with ui.card().classes("min-w-40 gap-0").mark(marker or f"tile-{label}"):
        ui.label(value).classes("text-3xl font-bold")
        ui.label(label).classes("text-sm text-gray-600")
        if detail:
            ui.label(detail).classes("text-xs text-gray-500")


def _chart_card(title: str, options: dict, height: int = 260, note: str = "") -> None:
    with ui.card().classes("w-full gap-1"):
        ui.label(title).classes("font-bold")
        if note:
            ui.label(note).classes("text-xs text-gray-500")
        ui.echart(options).classes("w-full").style(f"height: {height}px")


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def render(ctx: AppContext, review: Review) -> None:
    """Draw the Overview of ``review``."""
    ui.label("Overview").classes("text-2xl font-bold")
    body = ui.column().classes("w-full gap-3")

    async def load() -> None:
        try:
            data = await run.io_bound(service.compute, review)
        except Exception as exc:
            with body:
                show_error("Cannot read the review", exc)
            return
        body.clear()
        with body:
            _draw(review, data)

    with body:
        ui.spinner()
    ui.timer(0, load, once=True)


def _draw(review: Review, data: service.Overview) -> None:
    if not data.papers:
        with ui.card().classes("w-full").mark("overview-empty"):
            ui.label("No papers yet.").classes("font-bold")
            ui.label(
                "Collect them in ② Collect, or create the review from a Zotero library."
            ).classes("text-sm text-gray-600")
            ui.button(
                "Go to ② Collect",
                icon="travel_explore",
                on_click=lambda: ui.navigate.to(f"/review/{review.id}/collect"),
            ).props("outline")
        if not data.history:
            return

    latest = data.history[-1] if data.history else None
    screened = data.papers - data.screening.get("Not screened", data.papers)
    with ui.row().classes("gap-3").mark("overview-tiles"):
        _tile("papers", f"{data.papers:,}", marker="tile-papers")
        _tile(
            "collections (sub-corpora)",
            str(len(data.by_collection)),
            "from Zotero" if data.by_collection else "none",
            marker="tile-collections",
        )
        if data.papers:
            _tile(
                "screened",
                f"{100 * screened // data.papers} %",
                f"{data.screening.get('Included', 0)} included",
                marker="tile-screened",
            )
        if latest:
            _tile(
                "annotated papers",
                f"{latest.annotated} / {latest.papers}",
                f"{latest.pending} still to annotate · {_when(latest.at)}",
                marker="tile-annotated",
            )

    with ui.grid(columns="repeat(auto-fit, minmax(380px, 1fr))").classes("w-full gap-3"):
        if data.by_year:
            _chart_card("Papers per year", _years(data.by_year))
        if data.by_source:
            _chart_card("Papers per source", _hbar(data.by_source))
        if data.by_collection:
            _chart_card(
                "Papers per Zotero collection",
                _hbar(data.by_collection),
                height=max(220, 28 * min(len(data.by_collection), MAX_BARS)),
                note="A paper in several collections counts in each.",
            )
        if data.papers:
            _chart_card("Screening", _screening(data.screening), height=130)
        if data.enrichment:
            _chart_card(
                "Papers enriched, per source",
                _hbar(data.enrichment, total=data.papers),
                height=max(180, 36 * len(data.enrichment)),
            )
        if latest and latest.by_dimension:
            _chart_card(
                "Papers coded per dimension (latest snapshot)",
                _hbar(latest.by_dimension, total=latest.papers),
                height=max(220, 28 * min(len(latest.by_dimension), MAX_BARS)),
            )

    with ui.card().classes("w-full gap-1").mark("overview-history"):
        ui.label("Annotation history").classes("font-bold")
        if len(data.history) >= 1:
            ui.echart(_history(data.history)).classes("w-full").style("height: 280px")
            with ui.expansion("Snapshots (table)").classes("w-full"):
                ui.table(
                    columns=[
                        {"name": c, "label": label, "field": c, "align": "left"}
                        for c, label in (
                            ("at", "When"), ("origin", "Read during"), ("papers", "Papers"),
                            ("annotated", "Annotated"), ("pending", "Still to annotate"),
                            ("values", "Codes"),
                        )
                    ],
                    rows=[
                        {**s.__dict__, "at": _when(s.at)} for s in reversed(data.history)
                    ],
                    row_key="at",
                ).props("dense flat").classes("w-full")
        else:
            ui.label(
                "No snapshot yet. SciLEx records the annotation state each time it reads "
                "it from Zotero: when the review is imported, when you build the report in "
                "⑥ Annotate, and when you export the knowledge graph in ⑦ Export."
            ).classes("text-sm text-gray-600")
