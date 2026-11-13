"""Every extension of a review gets its own Zotero collection.

When an extension (new collect, BibTeX import, snowballing, papers from
another Zotero library) adds papers to a review that has a Zotero group, a
new collection is created in that group, under the review's collection when
it uses one: ``Extension <n> · <mode> · <date>``. The new papers are pushed
into it and get it as sub-corpus (``zotero_collections``), so each extension
stays visible, comparable and reversible in Zotero.

Instead of a new collection, the user can choose an existing collection of
the group on the Extend page (:class:`Target`, saved in
``extension_target.yml`` so the background jobs follow the choice).

Papers already in the group (same DOI, else same title and year) are not
pushed again: their Zotero item is added to the collection.

The Extend page refuses to extend a review without a Zotero group
(:func:`group_required`). When Zotero cannot be reached, the extension
itself is kept: only the collection is missing, and the message says why.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import yaml

from scilex.gui.services.workspace import Review

logger = logging.getLogger(__name__)

JOURNAL_ACTION = "extension-collection"
SEPARATOR = " · "
TARGET_FILENAME = "extension_target.yml"


@dataclass(frozen=True)
class Target:
    """Where the papers of the next extensions go in the review's Zotero group."""

    key: str = ""  # existing collection; "" creates a new one
    path: str = ""  # its path (``Parent / Child``)
    name: str = ""  # name of the new collection; "" for the automatic one

    @property
    def is_new(self) -> bool:
        return not self.key


def save_target(review: Review, target: Target) -> None:
    """Remember the collection of the next extensions (the Extend page's choice)."""
    path = Path(review.folder) / TARGET_FILENAME
    path.write_text(yaml.safe_dump(asdict(target), allow_unicode=True), "utf-8")


def load_target(review: Review) -> Target:
    """The chosen collection; a new collection when nothing was chosen."""
    path = Path(review.folder) / TARGET_FILENAME
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Target(**{k: str(data.get(k) or "") for k in ("key", "path", "name")})
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return Target()


def candidate_collections(review: Review, api=None) -> list:
    """Collections of the review's group an extension can go into.

    When the review uses one collection of the group, only it and its
    sub-collections: papers elsewhere would not be part of the review.

    Raises:
        ZoteroNotConfiguredError, ConnectionError: Zotero is not reachable.
    """
    from scilex.gui.services import zotero_library
    from scilex.gui.services.keys_editor import effective_keys

    source = zotero_library.load_source(review.folder)
    if source is None or source.library_type != "group":
        return []
    if api is None:
        api = zotero_library.client(effective_keys(review.folder), library=source)
    collections = zotero_library.list_collections(api)
    if not source.collection_key:
        return collections
    parent = {c.key: c.parent for c in collections}

    def inside(key: str | None) -> bool:
        seen = set()
        while key and key not in seen:
            if key == source.collection_key:
                return True
            seen.add(key)
            key = parent.get(key)
        return False

    return [c for c in collections if inside(c.key)]


@dataclass
class ExtensionCollection:
    """What :func:`publish` did."""

    name: str = ""
    path: str = ""
    key: str = ""
    existing: bool = False  # pushed into an existing collection
    papers: int = 0
    pushed: int = 0
    linked: int = 0  # already in the group: added to the collection
    failed: int = 0
    skipped: str = ""  # why no collection was made ("" when one was)

    def message(self) -> str:
        if self.skipped:
            return f"No Zotero collection for this extension: {self.skipped}"
        kind = "Existing Zotero collection" if self.existing else "Zotero collection"
        text = f"{kind} '{self.path}': {self.pushed} papers pushed"
        if self.linked:
            text += f", {self.linked} already in the group added to it"
        if self.failed:
            text += f", {self.failed} failed"
        return text + "."


class ExtensionNeedsGroupError(RuntimeError):
    """An extension was started on a review without a Zotero group."""


def group_required(review: Review) -> None:
    """Refuse an extension of ``review`` when its papers could get no collection.

    Raises:
        ExtensionNeedsGroupError: The review has no Zotero group.
    """
    from scilex.gui.services import zotero_library

    source = zotero_library.load_source(review.folder)
    if source is None or source.library_type != "group":
        raise ExtensionNeedsGroupError(
            "Every extension goes into a Zotero collection: choose the review's "
            "Zotero group first (Zotero group page)."
        )


def _group_items(api) -> dict[str, dict]:
    """The papers of the review's group by identity key (empty when unreadable)."""
    from scilex.gui.services import zotero_library
    from scilex.gui.services.screening import paper_key

    try:
        items = zotero_library.fetch_papers(api, None)
    except Exception:  # unreadable: every new paper is pushed
        logger.warning("Cannot list the papers of the group", exc_info=True)
        return {}
    return {
        paper_key(zotero_library.item_to_row(item)): item
        for item in items
        if item.get("key")
    }


def _link(api, items: list[dict], collection: str) -> tuple[int, int]:
    """Add the existing Zotero ``items`` to ``collection``: (linked, failed)."""
    updates = {}
    for item in items:
        data = item.get("data", {})
        current = list(data.get("collections") or [])
        if collection not in current:
            updates[item["key"]] = (
                item.get("version", data.get("version", 0)),
                [*current, collection],
            )
    if not updates:
        return len(items), 0
    counts = api.update_item_collections(updates)
    failed = int(counts.get("failed", 0))
    return len(items) - failed, failed


def paper_keys(data: pd.DataFrame | None) -> set[str]:
    """Identity keys of the papers of ``data`` (DOI, else title and year)."""
    from scilex.gui.services.screening import paper_key

    if data is None:
        return set()
    return {paper_key(row) for row in data.to_dict("records")}


def review_keys(review: Review) -> set[str]:
    """Identity keys of the review's papers now (empty without results)."""
    from scilex.gui.services.extend import read_results

    try:
        return paper_keys(read_results(review.results_path))
    except (OSError, ValueError):
        return set()


def collection_name(review: Review, mode: str, when: dt.date | None = None) -> str:
    """``Extension <n> · <mode> · <date>``, n counting the earlier ones."""
    from scilex.gui.services import journal

    try:
        done = sum(
            1
            for e in journal.load(review.folder)
            if e.get("activity") == JOURNAL_ACTION
        )
    except Exception:  # an unreadable journal must not block the extension
        done = 0
    when = when or dt.date.today()
    return SEPARATOR.join((f"Extension {done + 1}", mode, when.isoformat()))


def publish(
    review: Review,
    before: set[str],
    mode: str,
    *,
    api=None,
    progress: Callable[[int, str], None] | None = None,
    target: Target | None = None,
) -> ExtensionCollection:
    """Push the papers added since ``before`` into the extension's collection.

    The collection is ``target`` (default: the Extend page's choice): an
    existing collection, or a new one, created here. Never raises for Zotero
    problems: they are reported in the summary.
    """
    from scilex import review_tags
    from scilex.gui.services import journal, results_store, zotero_library
    from scilex.gui.services.extend import read_results
    from scilex.gui.services.keys_editor import effective_keys
    from scilex.gui.services.screening import paper_key

    summary = ExtensionCollection()
    source = zotero_library.load_source(review.folder)
    if source is None or source.library_type != "group":
        summary.skipped = "the review has no Zotero group (Zotero group page)."
        return summary
    data = read_results(review.results_path)
    if data is None:
        summary.skipped = "the review has no papers."
        return summary
    new_index = [
        index
        for index, row in zip(data.index, data.to_dict("records"), strict=True)
        if paper_key(row) not in before
    ]
    summary.papers = len(new_index)
    if not new_index:
        summary.skipped = "no new paper."
        return summary
    target = target if target is not None else load_target(review)
    if target.is_new:
        summary.name = target.name.strip() or collection_name(review, mode)
        summary.path = (
            f"{source.collection_name} / {summary.name}"
            if source.collection_key
            else summary.name
        )
    else:
        summary.existing = True
        summary.key, summary.path = target.key, target.path
        summary.name = target.path.split(" / ")[-1]
    if progress:
        progress(90, f"Zotero collection '{summary.name}'…")
    try:
        if api is None:
            api = zotero_library.client(effective_keys(review.folder), library=source)
        if target.is_new:
            created = api.create_collection(summary.name, parent=source.collection_key)
            if not created:
                summary.skipped = (
                    "Zotero refused to create the collection (key rights?)."
                )
                return summary
            summary.key = created.get("key") or created.get("data", {}).get("key", "")
        from scilex.push_to_zotero import prefetch_templates, push_new_items_to_zotero

        in_group = _group_items(api) if hasattr(api, "update_item_collections") else {}
        to_link = [
            in_group[key]
            for key in (paper_key(data.loc[i].to_dict()) for i in new_index)
            if key in in_group
        ]
        if to_link:
            summary.linked, link_failed = _link(api, to_link, summary.key)
            summary.failed += link_failed
        to_push = [
            i for i in new_index if paper_key(data.loc[i].to_dict()) not in in_group
        ]
        new_rows = data.loc[to_push].drop(columns=["paper_key"], errors="ignore")
        counts = push_new_items_to_zotero(
            new_rows,
            api,
            summary.key,
            set(),
            prefetch_templates(new_rows),
            {
                "output_dir": str(review.output_root),
                "collect_name": review.name,
                "_collect_dir": str(review.collection_dir),
            },
        )
    except (zotero_library.ZoteroNotConfiguredError, ConnectionError) as exc:
        summary.skipped = str(exc)
        return summary
    except Exception as exc:  # the extension is done; only Zotero failed
        logger.warning("Extension collection failed", exc_info=True)
        summary.skipped = f"Zotero failed ({type(exc).__name__}: {exc})."
        return summary
    summary.pushed = int(counts.get("success", 0))
    summary.failed += int(counts.get("failed", 0))

    # The new papers form a sub-corpus: the extension's collection.
    after = data.copy()
    if "zotero_collections" not in after.columns:
        after["zotero_collections"] = ""
    after["zotero_collections"] = after["zotero_collections"].astype(object)
    for index in new_index:
        parts = review_tags.split_tags(after.at[index, "zotero_collections"])
        after.at[index, "zotero_collections"] = ";".join([*parts, summary.path])
    before_frame = data.copy()
    if "zotero_collections" not in before_frame.columns:
        before_frame["zotero_collections"] = ""
    results_store.write_changes(review.results_path, before_frame, after)
    journal.append(
        review.folder,
        JOURNAL_ACTION,
        used={"zotero": journal.library_of(source)},
        # The extension itself is journaled apart.
        params={"mode": mode, "existing_collection": summary.existing},
        generated={
            "collection": summary.path,
            "papers": summary.papers,
            "pushed": summary.pushed,
            "linked": summary.linked,
            "failed": summary.failed,
        },
        message=summary.message(),
    )
    return summary
