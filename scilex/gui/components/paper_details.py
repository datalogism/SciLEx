"""Details of one paper, shared by ⑦ Analyses (network) and Explore.

- badges: paper type (tagged, or default), access, code, DOI;
- Zotero links: the item in the Zotero app, and on zotero.org (group);
- annotations: the DIMENSION:value tags grouped by dimension (pending ``?``
  values highlighted), who it is assigned to and who validated it.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from scilex import review_tags
from scilex.constants import doi_to_url, is_valid

ACCESS_COLORS = {
    "open (PDF)": "positive",
    "open": "positive",
    "restricted": "negative",
    "unknown": "grey",
}


def _text(record: dict, column: str) -> str:
    value = record.get(column)
    return str(value) if is_valid(value) else ""


def render_badges(record: dict) -> None:
    """Paper type, access, code and DOI of ``record`` (a results row)."""
    from scilex import paper_types
    from scilex.gui.services import coverage

    tagged = paper_types.type_of(record)
    kind = tagged or paper_types.effective_type(record)
    access = coverage.access_of(record)
    with ui.row().classes("items-center gap-1").mark("paper-badges"):
        ui.badge(kind, color="primary").props("outline").tooltip(
            "Paper type (PAPER_TYPE tag)"
            if tagged
            else "Default paper type (no PAPER_TYPE tag yet: ⑥ Enrich > Paper types)"
        ).mark("paper-type")
        ui.badge(access, color=ACCESS_COLORS.get(access, "grey")).props(
            "outline"
        ).tooltip("Access").mark("paper-access")
        if coverage.has_code(record):
            ui.badge("code", color="secondary").props("outline")
        if not _text(record, "DOI"):
            ui.badge("no DOI", color="warning").props("outline")


def render_links(record: dict, source=None) -> None:
    """DOI, Zotero item (app and zotero.org) and the other links of ``record``."""
    from scilex.gui.services import zotero_library

    links = []
    doi = _text(record, "DOI")
    if doi and doi_to_url(doi):
        links.append((doi, doi_to_url(doi)))
    links += zotero_library.item_links(source, _text(record, "zotero_key"))
    for label, column in (
        ("Web page", "url"),
        ("PDF", "pdf_url"),
        ("Code", "github_repo"),
    ):
        value = _text(record, column).split(";")[0]
        if value.startswith("http"):
            links.append((label, value))
    if not links:
        return
    with ui.row().classes("gap-3").mark("paper-links"):
        for label, url in links:
            ui.link(label, url, new_tab=not url.startswith("zotero:")).classes(
                "text-sm"
            )


def render_annotations(
    tags, on_click: Callable[[str], None] | None = None, title: str = "Annotations"
) -> None:
    """Annotation tags grouped by dimension, then who annotates and validated.

    ``on_click(tag)``: called when a value is clicked (e.g. to filter on it).
    """
    from scilex.tag_analysis import parse_annotation

    all_tags = review_tags.split_tags(tags)
    grouped: dict[str, list[tuple[str, str]]] = {}
    others: list[str] = []
    for tag in all_tags:
        if review_tags.is_workflow_tag(tag):
            continue
        parsed = parse_annotation(tag)
        if parsed:
            grouped.setdefault(parsed[0], []).append((parsed[1], tag))
        else:
            others.append(tag)
    state = review_tags.workflow(all_tags)
    pending = sum(1 for values in grouped.values() for v, _ in values if v == "?")
    header = f"{title} ({len(grouped)} dimensions" + (
        f", {pending} to fill)" if pending else ")"
    )
    with (
        ui.expansion(header, value=True)
        .classes("w-full")
        .props("dense")
        .mark("paper-annotations")
    ):
        who = []
        if state.assigned:
            who.append("assigned to " + ", ".join(state.assigned))
        if state.validated_by:
            who.append("validated by " + ", ".join(state.validated_by))
        if state.deleted_by:
            who.append("discarded by " + ", ".join(state.deleted_by))
        if who:
            ui.label("; ".join(who)).classes("text-xs text-gray-600")
        if not grouped:
            ui.label("No annotation yet.").classes("text-xs text-gray-500")
        for dimension in sorted(grouped):
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.label(dimension).classes("text-xs font-medium text-gray-600 w-40")
                with ui.row().classes("gap-1"):
                    for value, tag in grouped[dimension]:
                        chip = ui.chip(
                            "to fill" if value == "?" else value,
                            color="orange-2" if value == "?" else None,
                            on_click=(lambda _, t=tag: on_click(t))
                            if on_click
                            else None,
                        ).props("dense outline" + (" clickable" if on_click else ""))
                        chip.tooltip(tag)
        if others:
            with ui.row().classes("items-center gap-1"):
                ui.label("Other tags").classes("text-xs font-medium text-gray-600 w-40")
                for tag in sorted(others):
                    ui.chip(
                        tag,
                        on_click=(lambda _, t=tag: on_click(t)) if on_click else None,
                    ).props("dense outline" + (" clickable" if on_click else ""))


def render_paper(
    record: dict, source=None, on_tag: Callable[[str], None] | None = None
) -> None:
    """A compact notice: title, authors, year, badges, links, abstract, annotations."""
    ui.label(_text(record, "title") or "(no title)").classes("font-bold")
    meta = " · ".join(
        part
        for part in (
            _text(record, "authors").replace(";", ", ")[:160],
            _text(record, "date")[:4],
            _text(record, "journalAbbreviation") or _text(record, "conferenceName"),
        )
        if part
    )
    if meta:
        ui.label(meta).classes("text-sm text-gray-600")
    render_badges(record)
    collections = review_tags.split_tags(record.get("zotero_collections"))
    if collections:
        ui.label("Zotero collections: " + ", ".join(collections)).classes(
            "text-xs text-gray-500"
        )
    render_links(record, source)
    abstract = _text(record, "abstract")
    if abstract:
        with ui.expansion("Abstract").classes("w-full").props("dense"):
            ui.label(abstract).classes("text-sm whitespace-pre-wrap")
    render_annotations(record.get("tags"), on_tag)
