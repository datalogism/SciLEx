"""Eligibility of one paper: each criterion's verdict, and exceptions in one click.

Shown in ③ Screen and Explore. For each enabled criterion: passes, excluded
(with the cause; tagged ``DELETED_BY:filter:<id>`` once the criteria are
applied) or kept by an exception. "Keep as exception" tags the paper
``KEEP:<id>`` (shared through Zotero); applying the criteria again then
lifts its exclusion.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from nicegui import ui

from scilex import review_tags
from scilex.gui.services import criteria as service


def verdicts(
    record: dict,
    items: list[service.Criterion],
    included: bool = False,
    live: dict[str, tuple[str, str]] | None = None,
):
    """``[(criterion, state, text)]``; state: ``pass``, ``excluded``, ``kept``, ``tagged``.

    ``live``: the paper's verdicts judged on the whole corpus
    (:func:`service.eligibility`); without it, rules that need the corpus
    (duplicates, top % of a metric) rely on the applied tags.
    """
    tags = review_tags.split_tags(record.get("tags"))
    tagged = {
        cid: tag
        for tag in tags
        if tag.casefold().startswith(review_tags.filter_tag("").casefold())
        for cid in [tag.split(":", 2)[-1].split(" ")[0]]
    }
    found = []
    for criterion in items:
        if not criterion.enabled:
            continue
        if live is not None:
            state, cause = live.get(criterion.id, (service.PASS, None))
            exception = (
                service.exception_of(criterion, record, included)
                if state == service.KEPT
                else None
            )
        else:
            cause = service.cause_of(criterion, record)
            exception = service.exception_of(criterion, record, included)
        if cause and exception:
            found.append((criterion, "kept", f"{cause} — kept: {exception}"))
        elif cause:
            found.append((criterion, "excluded", cause))
        elif criterion.id in tagged:
            # Duplicates are judged on the whole corpus: the tag tells.
            found.append((criterion, "tagged", tagged[criterion.id]))
        else:
            found.append((criterion, "pass", criterion.inclusion or "passes"))
    return found


STATE_STYLE = {
    "pass": ("check_circle", "text-positive"),
    "excluded": ("cancel", "text-negative"),
    "tagged": ("cancel", "text-negative"),
    "kept": ("shield", "text-warning"),
}


def render_criteria(
    record: dict,
    items: list[service.Criterion],
    on_tags: Callable[[list[str], list[str]], Awaitable[None]] | None = None,
    included: bool = False,
    live: dict[str, tuple[str, str]] | None = None,
) -> None:
    """The eligibility of ``record``; ``on_tags(add, remove)`` writes its tags."""
    found = verdicts(record, items, included, live)
    if not found:
        return
    failing = sum(1 for _, state, _ in found if state in ("excluded", "tagged"))
    tags = {t.casefold() for t in review_tags.split_tags(record.get("tags"))}
    with (
        ui.expansion(
            f"Eligibility criteria ({failing} not met)"
            if failing
            else "Eligibility criteria (all met)",
            value=bool(failing),
        )
        .classes("w-full")
        .props("dense")
        .mark("paper-criteria")
    ):
        for criterion, state, text in found:
            icon, color = STATE_STYLE[state]
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.icon(icon).classes(color)
                ui.label(f"{criterion.id} – {criterion.name}").classes(
                    "text-xs font-medium w-44 shrink-0"
                )
                ui.label(text).classes("text-xs text-gray-600 grow")
                keep = f"{service.KEEP}:{criterion.id}"
                if on_tags is None:
                    continue
                if state in ("excluded", "tagged"):
                    ui.button(
                        "Keep as exception",
                        icon="shield",
                        on_click=lambda _, k=keep: on_tags([k], []),
                    ).props("flat dense no-caps size=sm").mark(
                        f"criteria-keep-{criterion.id}"
                    )
                elif keep.casefold() in tags:
                    ui.button(
                        "Remove exception",
                        on_click=lambda _, k=keep: on_tags([], [k]),
                    ).props("flat dense no-caps size=sm").mark(
                        f"criteria-unkeep-{criterion.id}"
                    )


def load_criteria(review) -> list:
    """The review's eligibility criteria (none when they cannot be read)."""
    from scilex.gui.services import criteria
    from scilex.gui.services.workspace import Workspace

    try:
        main = Workspace.load_config(review).main
    except Exception:
        main = {}
    try:
        return criteria.load(review.folder, main)
    except Exception:  # a damaged criteria.yml: the panel is left out
        return []


async def write_tags(
    review, session, key: str, add: list[str], remove: list[str]
) -> bool:
    """Write tags of one paper (pushed to Zotero by the sync); True when done."""
    from nicegui import run

    from scilex.gui.components.errors import show_error
    from scilex.gui.services import members

    try:
        new = await run.io_bound(
            members.apply_tags_by_key, review, {key: (add, remove)}
        )
    except Exception as exc:
        show_error("Cannot change the tags", exc)
        return False
    if key in new:
        session.set_tags(key, new[key])
    return True
