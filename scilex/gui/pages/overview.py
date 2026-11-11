"""Overview screen: the first page of a review, a visual summary of its state."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from nicegui import run, ui

from scilex.gui.components.errors import show_error
from scilex.gui.services import consistency, journal, prisma, provenance
from scilex.gui.services import overview as service
from scilex.gui.services.workspace import Review, Workspace, adopt_folder
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
        "xAxis": {"type": "value", **_AXIS, "max": total}
        if total
        else {"type": "value", **_AXIS},
        "yAxis": {
            "type": "category",
            "data": labels,
            **_AXIS,
            "splitLine": {"show": False},
            "axisLabel": {
                "color": TEXT_SECONDARY,
                "width": 220,
                "overflow": "truncate",
            },
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
        "xAxis": {
            "type": "category",
            "data": [str(y) for y in years],
            **_AXIS,
            "splitLine": {"show": False},
        },
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


TYPE_COLORS = (BLUE, AQUA, YELLOW, ORANGE, "#9c6b4e", "#a463f2")


def _type_colors(types) -> dict[str, str]:
    return {t: TYPE_COLORS[i % len(TYPE_COLORS)] for i, t in enumerate(types)}


def _types_per_year(data: service.Overview) -> dict:
    """Papers per year, stacked by paper type."""
    years = sorted({y for per in data.type_by_year.values() for y in per})
    years = list(range(years[0], years[-1] + 1)) if years else []
    colors = _type_colors(data.by_type)
    return {
        "grid": {"left": 8, "right": 8, "top": 36, "bottom": 8, "containLabel": True},
        "legend": {"top": 0, "textStyle": {"color": TEXT_SECONDARY}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {
            "type": "category",
            "data": [str(y) for y in years],
            **_AXIS,
            "splitLine": {"show": False},
        },
        "yAxis": {"type": "value", **_AXIS, "minInterval": 1},
        "series": [
            {
                "name": kind,
                "type": "bar",
                "stack": "types",
                "data": [data.type_by_year.get(kind, {}).get(y, 0) for y in years],
                "itemStyle": {"color": colors[kind]},
                "barMaxWidth": 24,
            }
            for kind in data.by_type
        ],
    }


def _types_per_collection(data: service.Overview) -> dict:
    """Share of each paper type in each Zotero collection (100 % bars)."""
    collections = list(_fold(data.by_collection))[::-1]
    collections = [c for c in collections if c in data.type_by_collection]
    colors = _type_colors(data.by_type)

    def share(collection: str, kind: str) -> float:
        counts = data.type_by_collection.get(collection, {})
        total = sum(counts.values()) or 1
        return round(100 * counts.get(kind, 0) / total, 1)

    return {
        "grid": {"left": 8, "right": 16, "top": 36, "bottom": 8, "containLabel": True},
        "legend": {"top": 0, "textStyle": {"color": TEXT_SECONDARY}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "value", "max": 100, **_AXIS},
        "yAxis": {
            "type": "category",
            "data": collections,
            **_AXIS,
            "splitLine": {"show": False},
            "axisLabel": {
                "color": TEXT_SECONDARY,
                "width": 200,
                "overflow": "truncate",
            },
        },
        "series": [
            {
                "name": kind,
                "type": "bar",
                "stack": "share",
                "data": [share(c, kind) for c in collections],
                "itemStyle": {"color": colors[kind]},
                "barMaxWidth": 18,
            }
            for kind in data.by_type
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
                "itemStyle": {
                    "color": color,
                    "borderColor": "#fcfcfb",
                    "borderWidth": 2,
                },
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
            "endLabel": {
                "show": True,
                "color": TEXT_SECONDARY,
                "formatter": "{a}: {@[1]}",
            },
        }

    return {
        "grid": {"left": 8, "right": 150, "top": 40, "bottom": 8, "containLabel": True},
        "legend": {"top": 0, "textStyle": {"color": TEXT_SECONDARY}},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "time", **_AXIS, "splitLine": {"show": False}},
        "yAxis": {
            "type": "value",
            **_AXIS,
            "minInterval": 1,
            "name": "papers",
            "nameTextStyle": {"color": TEXT_SECONDARY},
        },
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
            data, issues, events, card, flow = await run.io_bound(_gather, review)
        except Exception as exc:
            with body:
                show_error("Cannot read the review", exc)
            return
        body.clear()
        with body:
            _prisma(review, flow)
            _review_card(card)
            _issues(review, issues)
            _draw(review, data)
            _timeline(events)

    with body:
        ui.spinner()
    ui.timer(0, load, once=True)


def _gather(review: Review):
    """Overview data, consistency issues and journal events (off the event loop)."""
    try:
        main = Workspace.load_config(review).main
    except Exception:  # an invalid scilex.yml is reported by the other steps
        main = None
    journal.backfill(review.folder)
    return (
        service.compute(review),
        consistency.check(review, main),
        journal.load(review.folder),
        provenance.review_card(review.folder),
        prisma.compute(review, main),
    )


PHASE_CLASSES = "text-xs font-bold uppercase tracking-wide text-primary self-center"


def _box(box: prisma.Box, marker: str, tone: str = "") -> None:
    with ui.card().classes(f"w-full gap-0 p-3 {tone}").mark(marker):
        with ui.row().classes("items-baseline gap-2 no-wrap"):
            ui.label(box.title).classes("text-sm font-medium")
            ui.label("—" if box.count is None else f"n = {box.count:,}").classes(
                "text-sm font-bold"
            )
        for line in box.lines:
            ui.label(line).classes("text-xs text-gray-600")


def _arrow() -> None:
    ui.icon("south").classes("text-gray-400 justify-self-center")


def _prisma(review: Review, flow: prisma.Prisma) -> None:
    """The PRISMA flow diagram: identification, screening, inclusion, enrichment."""

    async def export() -> None:
        try:
            files = await run.io_bound(
                prisma.export_figure, flow, review.collection_dir
            )
        except Exception as exc:
            show_error("Cannot export the PRISMA flow", exc)
            return
        for path in files:
            ui.download(path, path.name)
        ui.notify(
            f"PRISMA flow saved: {', '.join(p.name for p in files)} in "
            f"{review.collection_dir}",
            type="positive",
            multi_line=True,
        )

    with ui.card().classes("w-full gap-2").mark("overview-prisma"):
        with ui.row().classes("w-full items-center"):
            ui.label("PRISMA flow").classes("font-bold")
            ui.space()
            if not flow.empty:
                ui.button("Export (SVG, PNG)", icon="download", on_click=export).props(
                    "flat dense no-caps"
                ).mark("prisma-export")
        if flow.empty:
            ui.label(
                "Nothing to show yet: the flow fills in with the collect, the "
                "extensions, the filters, the screening and the enrichments."
            ).classes("text-sm text-gray-600")
            return
        with ui.grid(columns="7rem 1fr 1fr").classes("w-full gap-2 items-stretch"):
            ui.label("Identification").classes(PHASE_CLASSES)
            _box(flow.identification, "prisma-identification")
            _box(flow.other_sources, "prisma-extensions")
            ui.label("")
            _arrow()
            _box(flow.removed_before, "prisma-removed", "bg-gray-50")
            ui.label("Screening").classes(PHASE_CLASSES)
            _box(flow.screened, "prisma-screened")
            _box(flow.excluded, "prisma-excluded", "bg-gray-50")
            ui.label("")
            _arrow()
            ui.label("")
            ui.label("Included").classes(PHASE_CLASSES)
            _box(flow.included, "prisma-included", "bg-green-50")
            _box(flow.pending, "prisma-pending")
            ui.label("Enrichment").classes(PHASE_CLASSES)
            with ui.element("div").classes("col-span-2"):
                _box(flow.enrichment, "prisma-enrichment", "border-dashed")


def _short(iso: str) -> str:
    return _when(iso)[:10] if iso else "?"


def _steps(title: str, steps: list[provenance.Step], unit: str, marker: str) -> None:
    ui.label(title).classes("text-xs font-medium text-gray-600")
    if not steps:
        ui.label("none yet").classes("text-xs text-gray-500")
        return
    with ui.column().classes("gap-0").mark(marker):
        for step in reversed(steps[-6:]):
            count = (
                f" — {'+' if unit == 'added' and step.papers > 0 else ''}{step.papers} {unit}"
                if step.papers is not None
                else ""
            )
            failed = "" if step.status == "completed" else f" ({step.status})"
            ui.label(
                f"{_short(step.at)} · {step.what}{count}{failed} · {step.who}"
            ).classes("text-xs")
        if len(steps) > 6:
            ui.label(f"… and {len(steps) - 6} earlier (see History)").classes(
                "text-xs text-gray-500"
            )


def _review_card(card: provenance.ReviewCard) -> None:
    """Origin, growth and contributors of the review, from its journal."""
    with ui.card().classes("w-full gap-2").mark("review-card"):
        with ui.row().classes("items-baseline gap-2 w-full"):
            ui.label("Review").classes("font-bold")
            ui.badge(card.origin_label).props("outline").mark("review-origin")
            if card.created_at:
                ui.label(
                    f"created {_short(card.created_at)} by {card.created_by}"
                ).classes("text-xs text-gray-600")
        if card.origin_detail:
            ui.label(card.origin_detail).classes("text-sm").style(
                "overflow-wrap: anywhere"
            )
        with ui.element("div").classes("grid gap-3 w-full md:grid-cols-2"):
            with ui.column().classes("gap-1"):
                _steps("Extensions", card.extensions, "added", "review-extensions")
            with ui.column().classes("gap-1"):
                _steps(
                    "Enrichments",
                    card.enrichments,
                    "papers updated",
                    "review-enrichments",
                )
        if card.annotation:
            first, last = card.annotation[0], card.annotation[-1]
            ui.label(
                f"Annotation: {last[1]} papers annotated, {last[2]} codes "
                f"(first record: {first[1]} papers, {first[2]} codes, {_short(first[0])})"
            ).classes("text-sm").mark("review-annotation")
            if len(card.annotation) > 1:
                ui.echart(
                    {
                        "grid": {
                            "left": 8,
                            "right": 8,
                            "top": 8,
                            "bottom": 8,
                            "containLabel": True,
                        },
                        "tooltip": {"trigger": "axis"},
                        "xAxis": {"type": "time", **_AXIS},
                        "yAxis": {"type": "value", **_AXIS, "minInterval": 1},
                        "series": [
                            {
                                "type": "line",
                                "name": "annotated papers",
                                "data": [
                                    [at, annotated]
                                    for at, annotated, _ in card.annotation
                                ],
                                "itemStyle": {"color": BLUE},
                                "showSymbol": True,
                            }
                        ],
                    }
                ).classes("w-full").style("height: 140px")
        people = [
            f"{name} ({n})"
            for name, n in sorted(card.scilex_users.items(), key=lambda kv: -kv[1])
        ]
        zotero = [
            f"{name} ({n})"
            for name, n in sorted(card.zotero_users.items(), key=lambda kv: -kv[1])
        ]
        ui.label(
            "Contributors — SciLEx: "
            + (", ".join(people) or "none recorded")
            + " · Zotero: "
            + (", ".join(zotero) or "none recorded")
        ).classes("text-xs text-gray-600").mark("review-contributors")


def _issues(review: Review, issues: list[consistency.Issue]) -> None:
    """Banner of what looks inconsistent, each with its fix."""
    if not issues:
        return
    with ui.card().classes("w-full gap-2 bg-amber-50").mark("overview-issues"):
        ui.label("Things to check").classes("font-bold")
        for issue in issues:
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.icon("warning").classes("text-warning")
                ui.label(issue.message).classes("text-sm grow")
                if issue.adopt:

                    def adopt(_, folder=issue.adopt) -> None:
                        adopt_folder(
                            review.folder, Path(folder), "chosen on the Overview"
                        )
                        ui.notify(
                            f"Results folder: {Path(folder).name}", type="positive"
                        )
                        ui.navigate.reload()

                    ui.button(
                        "Use this folder", icon="folder_open", on_click=adopt
                    ).props("outline dense no-caps").mark(f"issue-{issue.kind}")
                elif issue.step:
                    ui.button(
                        "Open",
                        icon="arrow_forward",
                        on_click=lambda _, s=issue.step: ui.navigate.to(
                            f"/review/{review.id}/{s}"
                        ),
                    ).props("outline dense no-caps").mark(f"issue-{issue.kind}")


def _event_details(event: dict) -> str:
    parts = []
    for section in ("params", "used", "generated"):
        for key, value in (event.get(section) or {}).items():
            if value in (None, "", {}, []):
                continue
            if isinstance(value, dict):
                value = ", ".join(
                    f"{k}: {v}" for k, v in value.items() if v not in (None, "")
                )
            parts.append(f"{key}: {value}")
    return " · ".join(parts)


def _timeline(events: list[dict]) -> None:
    """The review's workflow journal, most recent first."""
    with ui.card().classes("w-full gap-1").mark("overview-journal"):
        ui.label(f"History ({len(events)} events)").classes("font-bold")
        if not events:
            ui.label("Nothing recorded yet.").classes("text-sm text-gray-600")
            return
        with (
            ui.expansion("Show the history", value=False)
            .classes("w-full")
            .props("dense")
        ):
            for event in reversed(events):
                with ui.row().classes("items-start gap-2 w-full no-wrap"):
                    ui.label(_when(str(event.get("at", "")))).classes(
                        "text-xs text-gray-500 w-32 shrink-0"
                    )
                    with ui.column().classes("gap-0 grow"):
                        title = journal.label(event)
                        if event.get("status") not in (None, "completed"):
                            title += f" ({event['status']})"
                        if event.get("inferred"):
                            title += " · reconstructed"
                        ui.label(title).classes("text-sm font-medium").mark(
                            "journal-event"
                        )
                        text = event.get("message") or _event_details(event)
                        if text:
                            ui.label(text).classes("text-xs text-gray-600")
                        ui.label(journal.agent_name(event)).classes(
                            "text-xs text-gray-400"
                        )


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
            if latest.validated or latest.assigned:
                _tile(
                    "validated papers",
                    f"{latest.validated} / {latest.papers}",
                    f"{latest.assigned} assigned to an annotator (ANNOT_VALID_BY / ANNOT tags)",
                    marker="tile-validated",
                )
            if latest.discarded:
                _tile(
                    "discarded papers",
                    f"{latest.discarded}",
                    "DELETED_BY tag: kept in the corpus, left out of the counts and analyses",
                    marker="tile-discarded",
                )

    with ui.grid(columns="repeat(auto-fit, minmax(380px, 1fr))").classes(
        "w-full gap-3"
    ):
        if data.by_year:
            _chart_card("Papers per year", _years(data.by_year))
        if data.by_source:
            _chart_card("Papers per source", _hbar(data.by_source))
        if data.by_type:
            _chart_card(
                "Papers per type",
                _hbar(data.by_type),
                height=max(160, 36 * len(data.by_type)),
                note="PAPER_TYPE tag, else the default type (⑥ Enrich > Paper types "
                "writes the tags).",
            )
        if data.type_by_year:
            _chart_card("Paper types per year", _types_per_year(data))
        if data.type_by_collection:
            _chart_card(
                "Paper types per Zotero collection (%)",
                _types_per_collection(data),
                height=max(220, 30 * min(len(data.type_by_collection), MAX_BARS) + 40),
            )
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
                            ("at", "When"),
                            ("origin", "Read during"),
                            ("papers", "Papers"),
                            ("annotated", "Annotated"),
                            ("pending", "Still to annotate"),
                            ("values", "Codes"),
                        )
                    ],
                    rows=[
                        {**s.__dict__, "at": _when(s.at)}
                        for s in reversed(data.history)
                    ],
                    row_key="at",
                ).props("dense flat").classes("w-full")
        else:
            ui.label(
                "No snapshot yet. SciLEx records the annotation state each time it reads "
                "it from Zotero: when the review is imported, when you build the report in "
                "④ Annotate, and when you export the knowledge graph in ⑧ Export."
            ).classes("text-sm text-gray-600")
