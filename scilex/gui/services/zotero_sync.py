"""Two-way synchronisation of a review with its Zotero collection.

Papers, their metadata and their annotations change on both sides: annotators
tag and correct papers in Zotero; SciLEx enriches the papers (abstracts,
dates...) and records the screening decisions. This module tells which side
changed what since the last sync, and applies the changes in either direction.

**Baselines.** ``zotero_sync_state.json`` (review folder) keeps, for every
linked paper (``zotero_key`` column of ``aggregated_results.csv``), the state of
both sides at the last sync: ``zotero`` (the item) and ``local`` (the row). A
side changed a value when it differs from *its own* baseline, so the two sides
never need to write values identically, and a change is never attributed to
the wrong side. The same value changed differently on both sides is a conflict,
resolved by the user.

**Synced data.** The fields of :data:`FIELDS` and the tags. In SciLEx a paper's
tags are its ``tags`` and ``collect_keywords`` columns plus its screening
decision, written in Zotero as ``SCREEN:Include`` / ``SCREEN:Exclude`` /
``SCREEN:Maybe``. Tags merge as sets: what one side added or removed is added
or removed on the other.

**Cheap checks.** Zotero numbers every change of a library. The state keeps the
library version of the last sync; a check asks for the items changed since
(one request when nothing changed) and only reads those.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from scilex.constants import is_missing, split_semicolon_field
from scilex.gui.services import screening
from scilex.gui.services.workspace import Review

logger = logging.getLogger(__name__)

STATE_FILENAME = "zotero_sync_state.json"
KEY_COLUMN = "zotero_key"
# Results column -> Zotero field.
FIELDS: dict[str, str] = {
    "title": "title",
    "abstract": "abstractNote",
    "date": "date",
    "DOI": "DOI",
    "url": "url",
    "volume": "volume",
    "issue": "issue",
    "pages": "pages",
    "shortTitle": "shortTitle",
}
SCREEN_PREFIX = "SCREEN:"
SCREEN_TAGS = {
    screening.INCLUDE: "SCREEN:Include",
    screening.EXCLUDE: "SCREEN:Exclude",
    screening.MAYBE: "SCREEN:Maybe",
}
SCREEN_DECISIONS = {tag.casefold(): decision for decision, tag in SCREEN_TAGS.items()}
COLLECT_KEYWORD = re.compile(r"^Collect_KW\d*:")
BATCH = 50
CACHE_SECONDS = 90


class SyncError(Exception):
    """A user-facing problem: no Zotero collection, no key, Zotero unreachable."""


# ---------------------------------------------------------------------------
# Records: what is compared on each side
# ---------------------------------------------------------------------------


def _text(value) -> str:
    return "" if is_missing(value) else str(value).strip()


def local_record(row: dict, decision: str | None) -> dict:
    """Synced data of a results row (with its screening decision)."""
    tags = set(split_semicolon_field(row.get("tags")))
    tags |= set(split_semicolon_field(row.get("collect_keywords")))
    tags = {t for t in tags if not t.upper().startswith(SCREEN_PREFIX)}
    if decision in SCREEN_TAGS:
        tags.add(SCREEN_TAGS[decision])
    return {
        "fields": {name: _text(row.get(name)) for name in FIELDS},
        "tags": sorted(tags),
    }


def zotero_record(item: dict) -> dict:
    """Synced data of a Zotero item."""
    data = item.get("data", {})
    return {
        "fields": {name: _text(data.get(zname)) for name, zname in FIELDS.items()},
        "tags": sorted(
            {str(t.get("tag", "")).strip() for t in data.get("tags", [])} - {""}
        ),
    }


def _item_version(item: dict) -> int:
    return int(item.get("version", item.get("data", {}).get("version", 0)) or 0)


def _item_collections(item: dict) -> set[str]:
    return set(item.get("data", {}).get("collections") or [])


def _is_paper(item: dict) -> bool:
    data = item.get("data", {})
    return (
        data.get("itemType") not in ("attachment", "note", "annotation")
        and "title" in data
    )


@dataclass
class Change:
    """What one side changed on one paper since the last sync."""

    key: str
    title: str
    fields: dict[str, tuple[str, str]] = field(
        default_factory=dict
    )  # name -> (old, new)
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return not (self.fields or self.added or self.removed)

    def describe(self) -> str:
        parts = [f"{name} changed" for name in self.fields]
        if self.added:
            parts.append("+" + ", +".join(sorted(self.added)))
        if self.removed:
            parts.append("−" + ", −".join(sorted(self.removed)))
        return "; ".join(parts)


def diff(key: str, title: str, base: dict, now: dict) -> Change:
    """Changes of ``now`` against ``base`` (two records)."""
    change = Change(key, title)
    for name in FIELDS:
        old, new = base["fields"].get(name, ""), now["fields"].get(name, "")
        if old != new:
            change.fields[name] = (old, new)
    change.added = set(now["tags"]) - set(base["tags"])
    change.removed = set(base["tags"]) - set(now["tags"])
    return change


@dataclass
class Conflict:
    """A value both sides changed differently since the last sync."""

    key: str
    title: str
    what: str  # a field name, or "tag <tag>"
    local: str
    zotero: str


def conflicts_between(local: Change, remote: Change) -> list[Conflict]:
    """Values ``local`` and ``remote`` (same paper) changed in different ways."""
    found = [
        Conflict(
            local.key, local.title, name, local.fields[name][1], remote.fields[name][1]
        )
        for name in set(local.fields) & set(remote.fields)
        if local.fields[name][1] != remote.fields[name][1]
    ]
    # Screening: one decision per paper; two different new decisions conflict.
    local_screen = {t for t in local.added if t.upper().startswith(SCREEN_PREFIX)}
    remote_screen = {t for t in remote.added if t.upper().startswith(SCREEN_PREFIX)}
    if local_screen and remote_screen and local_screen != remote_screen:
        found.append(
            Conflict(
                local.key,
                local.title,
                "screening",
                ", ".join(sorted(local_screen)),
                ", ".join(sorted(remote_screen)),
            )
        )
    return found


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class SyncState:
    """Baselines of the last sync (``zotero_sync_state.json``)."""

    library_version: int = 0
    synced_at: str = ""
    collections: list[str] | None = None  # None: the whole library
    papers: dict[str, dict] = field(
        default_factory=dict
    )  # key -> {version, zotero, local}
    # Papers whose Zotero side must be re-read at each check (open conflicts).
    pending: list[str] = field(default_factory=list)


def state_path(review: Review) -> Path:
    return review.folder / STATE_FILENAME


def load_state(review: Review) -> SyncState | None:
    """The state of the last sync, None if the review was never synced."""
    path = state_path(review)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SyncState(**raw)
    except (ValueError, TypeError) as exc:
        logger.warning(f"Ignoring a damaged {path.name}: {exc}")
        return None


def save_state(review: Review, state: SyncState) -> None:
    path = state_path(review)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Results file
# ---------------------------------------------------------------------------


def _read_results(review: Review) -> pd.DataFrame:
    from scilex.gui.services.extend import read_results

    data = read_results(review.results_path)
    if data is None:
        raise SyncError("No aggregated results yet: collect or import papers first.")
    if KEY_COLUMN not in data.columns:
        data[KEY_COLUMN] = ""
    return data


def _write_results(review: Review, data: pd.DataFrame) -> None:
    from scilex.gui.services.extend import backup, write_results

    backup(review.results_path)
    write_results(data, review.results_path)
    from scilex.gui.services import paper_log

    paper_log.update(review.folder, data, when=datetime.now().date())


def _row_key(row: dict) -> str:
    return _text(row.get(KEY_COLUMN))


def _decisions(review: Review) -> dict[str, str]:
    return {k: d.decision for k, d in screening.load_decisions(review).items()}


# ---------------------------------------------------------------------------
# Zotero access
# ---------------------------------------------------------------------------


def _api(review: Review):
    from scilex.gui.services import zotero_library
    from scilex.gui.services.keys_editor import effective_keys

    source = zotero_library.load_source(review.folder)
    if source is None:
        raise SyncError(
            "Not linked to Zotero: choose the review's Zotero collection in ⑧ Export."
        )
    try:
        api = zotero_library.client(effective_keys(review.folder), library=source)
    except zotero_library.ZoteroNotConfiguredError as exc:
        raise SyncError(str(exc)) from exc
    return api, source


def _get_json(api, path: str, params: dict) -> tuple[object, int]:
    response = api._get(path, params=params)
    if response is None:
        raise SyncError("Zotero cannot be reached (offline, or the key was refused).")
    version = int(response.headers.get("Last-Modified-Version", 0) or 0)
    return response.json(), version


def _fetch_items(api, keys: list[str]) -> dict[str, dict]:
    items: dict[str, dict] = {}
    for start in range(0, len(keys), BATCH):
        batch = keys[start : start + BATCH]
        found, _ = _get_json(
            api, "/items", {"itemKey": ",".join(batch), "limit": BATCH}
        )
        for item in found or []:
            items[item["key"]] = item
    return items


def _fetch_all(review: Review, api, source) -> tuple[list[dict], list[str] | None]:
    """Every paper of the review's collection(s), and the collection keys used."""
    from scilex.gui.services import zotero_library

    try:
        collections = zotero_library.list_collections(api)
        items = zotero_library.fetch_source_papers(api, source, collections)
    except ConnectionError as exc:
        raise SyncError(f"Cannot read the Zotero collection: {exc}") from exc
    if source.whole_library:
        return items, None
    keys = (
        zotero_library.descendant_keys(collections, source.collection_key)
        if source.include_subcollections
        else [source.collection_key]
    )
    return items, keys


def _library_version(api) -> int:
    # Only the header is needed. (``format=keys`` answers plain text, not JSON:
    # parsing it failed on every first link.)
    response = api._get("/items/top", params={"limit": 1, "format": "keys"})
    if response is None:
        raise SyncError("Zotero cannot be reached (offline, or the key was refused).")
    return int(response.headers.get("Last-Modified-Version", 0) or 0)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@dataclass
class SyncStatus:
    """What changed on each side since the last sync."""

    linked: int = 0
    never_synced: bool = False
    zotero_changed: list[Change] = field(default_factory=list)
    zotero_new: list[dict] = field(default_factory=list)  # Zotero items not in SciLEx
    zotero_removed: list[str] = field(default_factory=list)  # keys gone from Zotero
    local_changed: list[Change] = field(default_factory=list)
    local_unlinked: int = 0  # SciLEx papers not in Zotero
    conflicts: list[Conflict] = field(default_factory=list)
    library_version: int = 0
    checked_at: float = field(default_factory=time.time)
    error: str | None = None
    # Zotero items read by the check (reused by a pull).
    items: dict[str, dict] = field(default_factory=dict, repr=False)

    @property
    def zotero_count(self) -> int:
        return (
            len(self.zotero_changed) + len(self.zotero_new) + len(self.zotero_removed)
        )

    @property
    def local_count(self) -> int:
        return len(self.local_changed)

    @property
    def state(self) -> str:
        """``error``, ``unlinked``, ``conflict``, ``both``, ``pull``, ``push`` or ``synced``."""
        if self.error:
            return "error"
        if self.never_synced:
            return "unlinked"
        if self.conflicts:
            return "conflict"
        if self.zotero_count and self.local_count:
            return "both"
        if self.zotero_count:
            return "pull"
        if self.local_count:
            return "push"
        return "synced"


def _title(row_or_item: dict) -> str:
    data = row_or_item.get("data", row_or_item)
    return _text(data.get("title"))[:120] or "(untitled)"


def _local_changes(review: Review, state: SyncState) -> tuple[dict[str, Change], int]:
    data = _read_results(review)
    decisions = _decisions(review)
    changes: dict[str, Change] = {}
    unlinked = 0
    for row in data.to_dict("records"):
        key = _row_key(row)
        if not key or key not in state.papers:
            unlinked += 1
            continue
        now = local_record(row, decisions.get(screening.paper_key(row)))
        change = diff(key, _title(row), state.papers[key]["local"], now)
        if not change.empty:
            changes[key] = change
    return changes, unlinked


def check(review: Review) -> SyncStatus:
    """Compare both sides with the baselines of the last sync (reads Zotero)."""
    state = load_state(review)
    api, source = _api(review)
    if state is None:
        data = _read_results(review)
        return SyncStatus(never_synced=True, local_unlinked=len(data))

    payload, version = _get_json(
        api, "/items/top", {"since": state.library_version, "format": "versions"}
    )
    changed = set(payload or {}) | set(state.pending)
    deleted_payload, _ = _get_json(api, "/deleted", {"since": state.library_version})
    deleted = set((deleted_payload or {}).get("items", [])) & set(state.papers)
    items = _fetch_items(api, sorted(changed - deleted)) if changed - deleted else {}

    status = SyncStatus(linked=len(state.papers), library_version=version, items=items)
    wanted = None if state.collections is None else set(state.collections)
    remote: dict[str, Change] = {}
    for key, item in items.items():
        if not _is_paper(item):
            continue
        in_scope = wanted is None or bool(_item_collections(item) & wanted)
        if key in state.papers:
            if not in_scope or item.get("data", {}).get("deleted"):
                status.zotero_removed.append(key)
                continue
            change = diff(
                key, _title(item), state.papers[key]["zotero"], zotero_record(item)
            )
            if not change.empty:
                remote[key] = change
        elif in_scope and not item.get("data", {}).get("deleted"):
            status.zotero_new.append(item)
    status.zotero_removed += sorted(deleted)

    local, status.local_unlinked = _local_changes(review, state)
    # New Zotero papers SciLEx already has (pushed without their key) are not new.
    status.zotero_new = [i for i in status.zotero_new if i["key"] not in state.papers]
    for key in set(local) & set(remote):
        status.conflicts += conflicts_between(local[key], remote[key])
    status.zotero_changed = list(remote.values())
    status.local_changed = list(local.values())
    return status


# A check per review at most every CACHE_SECONDS (each page draws the icon).
_cache: dict[str, SyncStatus] = {}
_cache_lock = threading.Lock()


def cached_check(review: Review, force: bool = False) -> SyncStatus:
    """:func:`check`, reusing a recent result; errors become a status."""
    key = str(review.folder)
    with _cache_lock:
        cached = _cache.get(key)
    if cached and not force and time.time() - cached.checked_at < CACHE_SECONDS:
        return cached
    try:
        status = check(review)
    except SyncError as exc:
        status = SyncStatus(error=str(exc))
    except Exception as exc:  # network, damaged files: the icon must not break the page
        logger.exception("Zotero sync check failed")
        status = SyncStatus(error=f"Cannot check Zotero: {exc}")
    with _cache_lock:
        _cache[key] = status
    return status


def forget_cache(review: Review) -> None:
    with _cache_lock:
        _cache.pop(str(review.folder), None)


# ---------------------------------------------------------------------------
# Link (first sync)
# ---------------------------------------------------------------------------


def _match_key(record: dict) -> list[str]:
    """Keys a paper can be matched by: DOI, URL, normalized title + year."""
    keys = []
    doi = _text(record.get("DOI")).lower()
    if doi:
        keys.append("doi:" + re.sub(r"^https?://(dx\.)?doi\.org/", "", doi))
    url = _text(record.get("url")).lower().rstrip("/")
    if url:
        keys.append("url:" + url)
    title = re.sub(r"[^0-9a-z]+", " ", _text(record.get("title")).lower()).strip()
    if title:
        keys.append("title:" + title)
    return keys


def _required_subcorpora(review: Review) -> list[str]:
    """``subcorpora.required`` of the review's scilex.yml (empty if unreadable)."""
    from scilex.gui.services.workspace import Workspace

    try:
        return list(Workspace.load_config(review).main.get("required_subcorpora") or [])
    except Exception:  # an invalid scilex.yml must not prevent linking
        return []


def link(review: Review, required: list[str] | None = None) -> dict[str, int]:
    """First sync: match the SciLEx papers with the Zotero items, record baselines.

    Papers are matched by ``zotero_key`` when present, else DOI, URL, title.
    Each row gets its own item: a paper kept twice on purpose (e.g. once in a
    "models" and once in a "datasets" collection) is linked to the item of its
    own sub-corpus, never to the item of the other copy.
    Both sides are taken as they are now (nothing is pushed or pulled).
    """
    api, source = _api(review)
    items, collections = _fetch_all(review, api, source)
    papers = [i for i in items if _is_paper(i)]
    item_for = _matcher(review, papers, required)
    by_key = {item["key"]: item for item in papers}

    data = _read_results(review)
    decisions = _decisions(review)
    state = SyncState(
        library_version=_library_version(api),
        synced_at=datetime.now().isoformat(timespec="seconds"),
        collections=collections,
    )
    linked = 0
    keys = []
    if "zotero_collections" not in data.columns:
        data["zotero_collections"] = ""
    data["zotero_collections"] = data["zotero_collections"].astype(object)
    for position, row in zip(data.index, data.to_dict("records"), strict=True):
        key = item_for(row, set(state.papers))
        if key:
            _take_collections(data, position, row, by_key[key])
            linked += 1
            state.papers[key] = {
                "version": _item_version(by_key[key]),
                "zotero": zotero_record(by_key[key]),
                "local": local_record(row, decisions.get(screening.paper_key(row))),
            }
        keys.append(key)  # "" when every matching item is already linked
    data[KEY_COLUMN] = keys
    _write_results(review, data)
    save_state(review, state)
    forget_cache(review)
    from scilex.gui.services import journal

    journal.append(
        review.folder,
        "zotero-sync-link",
        used={"zotero_library_version": state.library_version},
        generated={"linked": linked, "papers": len(data), "zotero_items": len(papers)},
        annotation=journal.annotation_of_results(review.results_path),
        zotero_actors=journal.zotero_actors(
            papers, since=journal.last_zotero_time(review.folder)
        ),
    )
    return {"linked": linked, "papers": len(data), "zotero": len(papers)}


def _take_collections(data: pd.DataFrame, position, row: dict, item: dict) -> None:
    """The sub-corpora of a row are its item's collections in Zotero."""
    paths = item.get("_scilex_collections")
    if paths:
        data.at[position, "zotero_collections"] = ";".join(paths)
        row["zotero_collections"] = data.at[position, "zotero_collections"]


def link_new(review: Review) -> dict[str, int]:
    """Link the SciLEx papers not linked yet with their Zotero items.

    After the first :func:`link`, papers pushed to Zotero later (⑧ Export, an
    extension) or added to the collection by hand have no baseline: their
    screening decision, ``DELETED_BY:`` / ``ANNOT_VALID_BY:`` tags... never
    reach Zotero. This matches them like :func:`link` does, among the items not
    linked yet, and merges their tags: both baselines are the tags the two
    sides share, so the SciLEx-only tags are pushed at the next push and the
    Zotero-only tags pulled at the next pull. Fields are taken as they are.

    Returns:
        ``{"linked": newly linked papers, "unlinked": papers still not in Zotero}``.
    """
    state = load_state(review)
    if state is None:
        raise SyncError("Link the review with Zotero first.")
    data = _read_results(review)
    unlinked = [
        position
        for position, row in zip(data.index, data.to_dict("records"), strict=True)
        if _row_key(row) not in state.papers
    ]
    if not unlinked:
        return {"linked": 0, "unlinked": 0}
    api, source = _api(review)
    items, _ = _fetch_all(review, api, source)
    papers = [
        i
        for i in items
        if _is_paper(i)
        and i["key"] not in state.papers
        and not i.get("data", {}).get("deleted")
    ]
    item_for = _matcher(review, papers)
    by_key = {item["key"]: item for item in papers}
    decisions = _decisions(review)
    if "zotero_collections" not in data.columns:
        data["zotero_collections"] = ""
    data["zotero_collections"] = data["zotero_collections"].astype(object)
    if KEY_COLUMN not in data.columns:
        data[KEY_COLUMN] = ""
    data[KEY_COLUMN] = data[KEY_COLUMN].astype(object)
    taken = set(state.papers)
    linked = 0
    for position in unlinked:
        row = data.loc[position].to_dict()
        key = item_for(row, taken)
        if not key:
            continue
        item = by_key[key]
        taken.add(key)
        data.at[position, KEY_COLUMN] = key
        _take_collections(data, position, row, item)
        remote = zotero_record(item)
        local = local_record(row, decisions.get(screening.paper_key(row)))
        shared = sorted(set(remote["tags"]) & set(local["tags"]))
        state.papers[key] = {
            "version": _item_version(item),
            "zotero": {**remote, "tags": shared},
            "local": {**local, "tags": shared},
        }
        linked += 1
    if linked:
        _write_results(review, data)
        save_state(review, state)
        forget_cache(review)
        from scilex.gui.services import journal

        journal.append(
            review.folder,
            "zotero-sync-link",
            generated={"linked": linked, "unlinked": len(unlinked) - linked},
        )
    return {"linked": linked, "unlinked": len(unlinked) - linked}


def _matcher(review: Review, papers: list[dict], required: list[str] | None = None):
    """``item_for(row, taken)``: the free Zotero item of ``papers`` matching ``row``."""
    index: dict[str, list[str]] = {}
    for item in papers:
        data = item.get("data", {})
        for match in _match_key(
            {"DOI": data.get("DOI"), "url": data.get("url"), "title": data.get("title")}
        ):
            index.setdefault(match, []).append(item["key"])
    by_key = {item["key"]: item for item in papers}
    names = required if required is not None else _required_subcorpora(review)
    required = {name.casefold() for name in names}

    def item_for(row: dict, taken: set[str]) -> str:
        """The free item matching ``row``, from its own sub-corpus if possible."""
        own = _row_key(row)
        candidates = [own] if own in by_key and own not in taken else []
        candidates += [
            key
            for match in _match_key(row)
            for key in index.get(match, [])
            if key not in taken and key != own
        ]
        if not candidates:
            return ""
        corpora = {
            c.casefold() for c in split_semicolon_field(row.get("zotero_collections"))
        }

        def rank(key: str) -> tuple[bool, bool, bool]:
            """Items in a required sub-corpus first (not a stray import copy),
            then items in the row's own sub-corpus, then the item it had."""
            paths = [p.casefold() for p in by_key[key].get("_scilex_collections") or []]
            tops = {p.split("/")[0].strip() for p in paths}
            return (bool(tops & required), bool(corpora & set(paths)), key == own)

        return max(candidates, key=rank)  # max keeps the first of equals

    return item_for


# ---------------------------------------------------------------------------
# Pull: Zotero -> SciLEx
# ---------------------------------------------------------------------------


def _set_tags(data: pd.DataFrame, index, tags: set[str]) -> None:
    """Write ``tags`` into the ``tags`` / ``collect_keywords`` columns of a row."""
    keywords = sorted(t for t in tags if COLLECT_KEYWORD.match(t))
    others = sorted(
        t for t in tags if t not in keywords and not t.upper().startswith(SCREEN_PREFIX)
    )
    for column, values in (("tags", others), ("collect_keywords", keywords)):
        if column not in data.columns:
            data[column] = ""
        data.at[index, column] = ";".join(values)


def _screen_decision(tags: set[str]) -> str | None:
    for tag in tags:
        decision = SCREEN_DECISIONS.get(tag.casefold())
        if decision:
            return decision
    return None


def pull(review: Review, status: SyncStatus | None = None) -> dict[str, int]:
    """Apply the Zotero changes to SciLEx (conflicting values are left as they are).

    Changed fields and tags of linked papers are copied, new Zotero papers are
    added, a ``SCREEN:`` tag becomes the screening decision, and each paper's
    collections follow Zotero (``zotero_collections``). Papers removed from
    Zotero keep their row but lose their collections (they leave the screened
    results, see :mod:`.collection_roles`).
    """
    from scilex.gui.services.zotero_library import item_to_row

    if load_state(review) is None:
        raise SyncError("Link the review with Zotero first.")
    status = status or check(review)
    if status.zotero_new and status.local_unlinked:
        # New items may be SciLEx papers pushed by ⑧ Export: link, don't copy.
        link_new(review)
    state = load_state(review)
    status.zotero_new = [i for i in status.zotero_new if i["key"] not in state.papers]
    conflicted = {(c.key, c.what) for c in status.conflicts}
    data = _read_results(review)
    rows = {
        _row_key(r): i
        for i, r in zip(data.index, data.to_dict("records"), strict=True)
        if _row_key(r)
    }
    decisions = screening.load_decisions(review)
    updated = 0
    for change in status.zotero_changed:
        index = rows.get(change.key)
        item = status.items.get(change.key)
        if index is None or item is None:
            continue
        for name, (_, new) in change.fields.items():
            if (change.key, name) not in conflicted:
                if name not in data.columns:
                    data[name] = ""
                data.at[index, name] = new
        row = data.loc[index].to_dict()
        paper = screening.paper_key(row)
        current = set(
            local_record(row, getattr(decisions.get(paper), "decision", None))["tags"]
        )
        current |= change.added
        current -= change.removed
        _set_tags(data, index, current)
        if (change.key, "screening") not in conflicted and (
            change.added & set(SCREEN_TAGS.values())
            or change.removed & set(SCREEN_TAGS.values())
        ):
            decision = _screen_decision(current)
            note = getattr(decisions.get(paper), "note", "")
            screening.set_decision(review, paper, decision, note)
        updated += 1

    added = 0
    if status.zotero_new:
        new_rows = pd.DataFrame([item_to_row(item) for item in status.zotero_new])
        data = pd.concat([data, new_rows], ignore_index=True)
        added = len(new_rows)
        for item, row in zip(
            status.zotero_new, new_rows.to_dict("records"), strict=True
        ):
            decision = _screen_decision(set(zotero_record(item)["tags"]))
            if decision:
                screening.set_decision(review, screening.paper_key(row), decision)
    moved = _pull_collections(review, data, rows, status)
    _write_results(review, data)

    # New baselines for what was pulled (not for open conflicts).
    decisions = _decisions(review)
    records = {_row_key(r): r for r in data.to_dict("records") if _row_key(r)}
    keep_pending = {c.key for c in status.conflicts}
    for key in {c.key for c in status.zotero_changed} | {
        i["key"] for i in status.zotero_new
    }:
        item = status.items.get(key) or next(
            (i for i in status.zotero_new if i["key"] == key), None
        )
        row = records.get(key)
        if item is None or row is None:
            continue
        local_now = local_record(row, decisions.get(screening.paper_key(row)))
        previous = state.papers.get(key)
        if key in keep_pending and previous is not None:
            # Keep the old Zotero baseline so the conflict stays visible.
            continue
        state.papers[key] = {
            "version": _item_version(item),
            "zotero": zotero_record(item),
            # Local changes not yet pushed stay pending: rebase only what was pulled.
            "local": local_now
            if previous is None
            else _rebase_local(previous, local_now, status, key),
        }
    state.pending = sorted(keep_pending)
    state.library_version = status.library_version or state.library_version
    state.synced_at = datetime.now().isoformat(timespec="seconds")
    save_state(review, state)
    forget_cache(review)
    from scilex.gui.services import journal

    changed_items = list(status.items.values()) + list(status.zotero_new)
    journal.append(
        review.folder,
        "zotero-pull",
        used={"zotero_library_version": state.library_version},
        generated={
            "updated": updated,
            "added": added,
            "moved": moved,
            "removed": len(status.zotero_removed),
            "results_rows": len(data),
        },
        annotation=journal.annotation_of_results(review.results_path),
        zotero_actors=journal.zotero_actors(
            changed_items, since=journal.last_zotero_time(review.folder)
        ),
    )
    return {
        "updated": updated,
        "added": added,
        "moved": moved,
        "removed": len(status.zotero_removed),
    }


def _pull_collections(review: Review, data: pd.DataFrame, rows: dict, status) -> int:
    """Copy the collections of the changed items into ``zotero_collections``.

    Moving a paper between collections changes no field: only the item's
    version. A paper removed from Zotero (deleted, in the trash, out of the
    review's scope) loses its collections, so it leaves the screened results;
    its row stays. Returns the rows changed.
    """
    from scilex.gui.services import zotero_library

    if not status.items and not status.zotero_removed:
        return 0
    try:
        api, _ = _api(review)
        paths = {c.key: c.path for c in zotero_library.list_collections(api)}
    except (SyncError, ConnectionError) as exc:
        logger.warning("Zotero collections not read: %s", exc)
        return 0
    if "zotero_collections" not in data.columns:
        data["zotero_collections"] = ""
    data["zotero_collections"] = data["zotero_collections"].astype(object)
    wanted: dict[str, str] = {key: "" for key in status.zotero_removed}
    for key, item in status.items.items():
        if key in status.zotero_removed or not _is_paper(item):
            continue
        member = item.get("data", {}).get("collections") or []
        wanted[key] = ";".join(sorted(paths[k] for k in member if k in paths))
    moved = 0
    for key, value in wanted.items():
        index = rows.get(key)
        if index is None:
            continue
        old = data.at[index, "zotero_collections"]
        if (old if isinstance(old, str) else "") != value:
            data.at[index, "zotero_collections"] = value
            moved += 1
    return moved


def _rebase_local(
    previous: dict, local_now: dict, status: SyncStatus, key: str
) -> dict:
    """Local baseline after a pull: the old one plus what was pulled.

    Values SciLEx changed itself (to push) stay different from the baseline.
    """
    local_change = next((c for c in status.local_changed if c.key == key), None)
    base = {"fields": dict(local_now["fields"]), "tags": set(local_now["tags"])}
    if local_change is not None:
        for name, (old, _) in local_change.fields.items():
            base["fields"][name] = old
        base["tags"] -= local_change.added
        base["tags"] |= local_change.removed
    return {"fields": base["fields"], "tags": sorted(base["tags"])}


# ---------------------------------------------------------------------------
# Push: SciLEx -> Zotero
# ---------------------------------------------------------------------------


def push(review: Review, status: SyncStatus | None = None) -> dict[str, int]:
    """Write the SciLEx changes of linked papers to Zotero (not the conflicts).

    An item edited in Zotero meanwhile is refused by Zotero (version check)
    and comes back at the next check.
    """
    state = load_state(review)
    if state is None:
        raise SyncError("Link the review with Zotero first.")
    status = status or check(review)
    api, _ = _api(review)
    conflicted = {(c.key, c.what) for c in status.conflicts}
    payload = []
    for change in status.local_changed:
        base = state.papers[change.key]
        item = status.items.get(change.key)
        remote_tags = (
            set(zotero_record(item)["tags"]) if item else set(base["zotero"]["tags"])
        )
        version = _item_version(item) if item else base["version"]
        entry: dict = {"key": change.key, "version": version}
        for name, (_, new) in change.fields.items():
            if (change.key, name) not in conflicted:
                entry[FIELDS[name]] = new
        added, removed = set(change.added), set(change.removed)
        if (change.key, "screening") in conflicted:
            added = {t for t in added if not t.upper().startswith(SCREEN_PREFIX)}
            removed = {t for t in removed if not t.upper().startswith(SCREEN_PREFIX)}
        if added or removed:
            entry["tags"] = [
                {"tag": t} for t in sorted((remote_tags | added) - removed)
            ]
        if len(entry) > 2:
            payload.append(entry)

    totals = {"success": 0, "failed": 0}
    for start in range(0, len(payload), BATCH):
        batch = payload[start : start + BATCH]
        response = api._post("/items", batch)
        if response is None:
            totals["failed"] += len(batch)
            continue
        outcome = api._count_outcome(response, batch)
        totals["success"] += outcome["success"]
        totals["failed"] += outcome["failed"]

    # New baselines for the papers written: re-read them from Zotero.
    written = [entry["key"] for entry in payload]
    if written:
        fresh = _fetch_items(api, written)
        data = _read_results(review)
        decisions = _decisions(review)
        records = {_row_key(r): r for r in data.to_dict("records") if _row_key(r)}
        for key, item in fresh.items():
            if key in records and _item_version(item) != state.papers[key]["version"]:
                state.papers[key] = {
                    "version": _item_version(item),
                    "zotero": zotero_record(item),
                    "local": local_record(
                        records[key], decisions.get(screening.paper_key(records[key]))
                    ),
                }
        save_state(review, state)
    forget_cache(review)
    from scilex.gui.services import journal

    journal.append(review.folder, "zotero-push", generated=dict(totals))
    return totals


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


def resolve(review: Review, conflict: Conflict, keep: str) -> None:
    """Settle a conflict: ``keep="zotero"`` copies Zotero's value into SciLEx,
    ``keep="scilex"`` leaves SciLEx's value to be pushed at the next push.
    """
    state = load_state(review)
    if state is None or conflict.key not in state.papers:
        raise SyncError("This paper is no longer linked.")
    api, _ = _api(review)
    item = _fetch_items(api, [conflict.key]).get(conflict.key)
    if item is None:
        raise SyncError("This paper is no longer in Zotero.")
    paper = state.papers[conflict.key]
    if keep == "zotero":
        data = _read_results(review)
        index = next(
            i
            for i, r in zip(data.index, data.to_dict("records"), strict=True)
            if _row_key(r) == conflict.key
        )
        if conflict.what == "screening":
            row = data.loc[index].to_dict()
            decision = _screen_decision(set(zotero_record(item)["tags"]))
            screening.set_decision(review, screening.paper_key(row), decision)
        else:
            data.at[index, conflict.what] = zotero_record(item)["fields"][conflict.what]
            _write_results(review, data)
    # Zotero's value becomes the Zotero baseline for this value: the conflict is gone.
    remote = zotero_record(item)
    if conflict.what == "screening":
        screen = {t for t in remote["tags"] if t.upper().startswith(SCREEN_PREFIX)}
        others = {
            t
            for t in paper["zotero"]["tags"]
            if not t.upper().startswith(SCREEN_PREFIX)
        }
        paper["zotero"]["tags"] = sorted(others | screen)
    else:
        paper["zotero"]["fields"][conflict.what] = remote["fields"][conflict.what]
    if keep == "zotero":
        data = _read_results(review)
        decisions = _decisions(review)
        row = next(r for r in data.to_dict("records") if _row_key(r) == conflict.key)
        now = local_record(row, decisions.get(screening.paper_key(row)))
        if conflict.what == "screening":
            paper["local"]["tags"] = sorted(
                {
                    t
                    for t in paper["local"]["tags"]
                    if not t.upper().startswith(SCREEN_PREFIX)
                }
                | {t for t in now["tags"] if t.upper().startswith(SCREEN_PREFIX)}
            )
        else:
            paper["local"]["fields"][conflict.what] = now["fields"][conflict.what]
    save_state(review, state)
    forget_cache(review)
