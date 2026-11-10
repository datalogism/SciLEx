"""⑤ Extend from Zotero: add the papers of a Zotero library or collection to a review.

Zotero is not a keyword search, so it is not a source of ② Collect: a review is
extended with what a library (yours or a group) or a collection holds, like a
BibTeX file. Papers the review already has (same DOI, else same title and year)
are not added again; they get the Zotero tags and sub-corpora they lack (tags
merge as sets, nothing is removed).

With ``link``, the library becomes the review's Zotero library (two-way sync,
push, knowledge-graph export): the choice is saved in ``zotero_source.yml`` and
every paper is matched with its Zotero item (:func:`zotero_sync.link`).
Without it, the papers are added but stay unlinked (their ``zotero_key``, which
only means something in the review's own library, is left empty).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import pandas as pd

from scilex.constants import is_valid
from scilex.gui.services.workspace import Review
from scilex.gui.services.zotero_library import ZoteroSource

logger = logging.getLogger(__name__)

ORIGIN_COLUMN = "extension_origin"  # same column as scilex.gui.services.extend
KEY_COLUMN = "zotero_key"
# Columns merged as ";"-separated sets into the papers the review already has.
MERGED_COLUMNS = ("tags", "collect_keywords", "zotero_collections")


@dataclass
class ZoteroExtension:
    """Outcome of :func:`extend_from_zotero`."""

    source: str
    fetched: int = 0
    added: int = 0
    already_there: int = 0
    enriched: int = 0  # existing papers that got tags or sub-corpora
    linked: int | None = None  # papers matched with their item (``link`` only)

    def message(self) -> str:
        """One-line summary for the user."""
        text = (
            f"{self.added} new papers added from {self.source} ({self.fetched} papers "
            f"there, {self.already_there} already in the review"
        )
        text += (
            f", {self.enriched} of them got new tags or sub-corpora)."
            if self.enriched
            else ")."
        )
        if self.linked is not None:
            text += f" Linked to this library: {self.linked} papers matched with their Zotero item."
        return text


def same_library(a: ZoteroSource | None, b: ZoteroSource | None) -> bool:
    """True when both sources are in the same Zotero library."""
    return (
        a is not None
        and b is not None
        and (a.library_type, str(a.library_id)) == (b.library_type, str(b.library_id))
    )


def _values(value) -> list[str]:
    if not is_valid(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _union(old, new) -> tuple[str, bool]:
    """``old`` + the values of ``new`` it lacks (";"-separated), and whether it grew."""
    merged = _values(old)
    known = {value.casefold() for value in merged}
    grew = False
    for value in _values(new):
        if value.casefold() not in known:
            merged.append(value)
            known.add(value.casefold())
            grew = True
    return ";".join(merged), grew


def describe(source: ZoteroSource) -> str:
    """Readable name of a library or collection."""
    library = source.library_name or f"{source.library_type} {source.library_id}"
    if source.collection_key:
        return f"'{source.collection_name}' ({library})"
    return f"the whole library {library}"


def extend_from_zotero(
    review: Review, source: ZoteroSource, *, link: bool, progress=None
) -> ZoteroExtension:
    """Add the papers of ``source`` the review lacks; see the module docstring.

    Raises:
        ZoteroNotConfiguredError, ConnectionError: Zotero cannot be read.
    """
    from scilex.gui.services import paper_log, zotero_library, zotero_sync
    from scilex.gui.services.extend import backup, read_results, write_results
    from scilex.gui.services.keys_editor import effective_keys
    from scilex.gui.services.screening import paper_key

    def say(percent: int, message: str) -> None:
        if progress is not None:
            progress(percent, message)

    summary = ZoteroExtension(source=describe(source))
    say(5, f"Reading {summary.source} from Zotero…")
    api = zotero_library.client(effective_keys(review.folder), library=source)
    collections = zotero_library.list_collections(api)
    items = zotero_library.fetch_source_papers(api, source, collections)
    incoming = zotero_library.items_to_results(items)
    summary.fetched = len(incoming)
    say(50, f"{summary.fetched} papers read; merging with the review…")

    previous = read_results(review.results_path)
    if previous is None:
        previous = pd.DataFrame(columns=["title", "itemType"])
    previous = previous.copy()
    for column in (*MERGED_COLUMNS, ORIGIN_COLUMN, KEY_COLUMN):
        if column not in previous.columns:
            previous[column] = ""
        previous[column] = previous[column].astype(object)
    index = {
        paper_key(r): i
        for i, r in zip(previous.index, previous.to_dict("records"), strict=True)
    }

    origin = f"zotero {summary.source} {dt.date.today().isoformat()}"
    new_rows = []
    added_keys: set[str] = set()
    for row in incoming.to_dict("records"):
        key = paper_key(row)
        if key in added_keys:  # the same paper twice in the library: added once
            continue
        if key in index:
            summary.already_there += 1
            target = index[key]
            grew_any = False
            for column in MERGED_COLUMNS:
                merged, grew = _union(previous.at[target, column], row.get(column))
                if grew:
                    previous.at[target, column] = merged
                    grew_any = True
            summary.enriched += grew_any
            continue
        added_keys.add(key)
        row[ORIGIN_COLUMN] = origin
        if not link:
            row[KEY_COLUMN] = ""
        new_rows.append(row)
    summary.added = len(new_rows)

    if not (new_rows or summary.enriched or link):
        return summary
    merged = (
        pd.concat([previous, pd.DataFrame(new_rows)], ignore_index=True)
        if new_rows
        else previous
    )
    if review.results_path.is_file():
        backup(review.results_path)
    else:
        review.collection_dir.mkdir(parents=True, exist_ok=True)
    write_results(merged, review.results_path)
    try:
        paper_log.update(review.folder, merged, when=dt.date.today())
    except OSError:
        logger.warning("Cannot update the paper log", exc_info=True)

    if link:
        say(75, "Linking the review with this Zotero library…")
        zotero_library.save_source(review.folder, source)
        summary.linked = zotero_sync.link(review)["linked"]
    say(100, summary.message())
    return summary
