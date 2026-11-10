"""Provenance of a review, summarized from its workflow journal (Overview card).

Answers: where the corpus comes from, who created it and when, how it was
extended (by whom, when, how many papers), enriched (source, by whom, when,
papers updated), how the annotation grew, and who contributed — SciLEx users
(the ORCID iD of each event) and Zotero users (who added or modified items in
the review's Zotero library, read at each Zotero import, link or pull).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scilex.gui.services import journal


@dataclass
class Step:
    """One extension or enrichment of the corpus."""

    at: str
    who: str
    what: str  # mode (extension) or source (enrichment)
    papers: int | None = None  # papers added (extension) or updated (enrichment)
    status: str = "completed"
    inferred: bool = False


@dataclass
class ReviewCard:
    """What the Overview's Review card shows."""

    origin: str = journal.EMPTY
    origin_detail: str = ""
    created_at: str = ""
    created_by: str = ""
    extensions: list[Step] = field(default_factory=list)
    enrichments: list[Step] = field(default_factory=list)
    # (time, annotated papers, codes), oldest first.
    annotation: list[tuple[str, int, int]] = field(default_factory=list)
    scilex_users: dict[str, int] = field(default_factory=dict)  # name -> events
    zotero_users: dict[str, int] = field(
        default_factory=dict
    )  # username -> items changed

    @property
    def origin_label(self) -> str:
        """Readable origin type."""
        return journal.ORIGIN_LABELS.get(self.origin, self.origin)


def _detail(event: dict) -> str:
    params, used = event.get("params") or {}, event.get("used") or {}
    library = used.get("zotero") or {}
    if library.get("library_id"):
        where = library.get("collection_name") or "whole library"
        name = (
            library.get("library_name")
            or f"{library.get('library_type')} {library['library_id']}"
        )
        return f"{name} — {where}"
    search = params if params.get("keywords") else params.get("search") or {}
    if search.get("keywords"):
        groups = search["keywords"]
        if groups and isinstance(groups[0], list):
            keywords = " AND ".join("(" + " | ".join(map(str, g)) + ")" for g in groups)
        else:
            keywords = " | ".join(map(str, groups))
        years = search.get("years") or []
        span = f", {min(years)}–{max(years)}" if years else ""
        apis = ", ".join(search.get("apis") or [])
        return f"{keywords}{span}" + (f" on {apis}" if apis else "")
    return str(used.get("source") or used.get("file") or "")


def _added(event: dict) -> int | None:
    generated = event.get("generated") or {}
    if generated.get("added") is not None:
        return int(generated["added"])
    after, before = generated.get("results_rows"), generated.get("results_rows_before")
    if after is not None and before is not None:
        return int(after) - int(before)
    return None


def review_card(folder: Path) -> ReviewCard:
    """Summarize the journal of the review in ``folder``."""
    from scilex.gui.services.overview import load_history

    events = journal.load(folder)
    card = ReviewCard()
    created = next((e for e in events if e.get("activity") == "created"), None)
    if created is not None:
        card.origin = (created.get("params") or {}).get("origin") or journal.EMPTY
        card.origin_detail = _detail(created)
        card.created_at = str(created.get("at", ""))
        card.created_by = journal.agent_name(created)
    if card.origin == journal.EMPTY:
        # An empty review takes the origin of its first papers.
        first = next(
            (
                e
                for e in events
                if e.get("activity")
                in ("job:pipeline", "import-bibtex", "extend-zotero")
                and e.get("status", "completed") == "completed"
            ),
            None,
        )
        if first is not None:
            card.origin = {
                "job:pipeline": journal.SCILEX_COLLECT,
                "import-bibtex": journal.BIBTEX_IMPORT,
                "extend-zotero": journal.ZOTERO_IMPORT,
            }[first["activity"]]
            card.origin_detail = card.origin_detail or _detail(first)

    for event in events:
        params = event.get("params") or {}
        who = journal.agent_name(event)
        if not event.get("inferred"):
            card.scilex_users[who] = card.scilex_users.get(who, 0) + 1
        for user, counts in (event.get("zotero_actors") or {}).items():
            changed = int(counts.get("created", 0)) + int(counts.get("modified", 0))
            card.zotero_users[user] = card.zotero_users.get(user, 0) + changed
        category = params.get("category")
        step = Step(
            at=str(event.get("at", "")),
            who=who,
            what=str(
                params.get("mode") or params.get("source") or journal.label(event)
            ),
            status=str(event.get("status", "completed")),
            inferred=bool(event.get("inferred")),
        )
        if category == "extension":
            step.papers = _added(event)
            card.extensions.append(step)
        elif category == "enrichment":
            updated = (event.get("generated") or {}).get("papers_updated")
            step.papers = int(updated) if updated is not None else None
            card.enrichments.append(step)
        state = event.get("annotation")
        if isinstance(state, dict) and state.get("papers") is not None:
            card.annotation.append(
                (step.at, int(state.get("annotated", 0)), int(state.get("codes", 0)))
            )
    for snap in load_history(folder):
        card.annotation.append((snap.at, snap.annotated, snap.values))
    card.annotation = sorted(dict.fromkeys(card.annotation))
    return card
