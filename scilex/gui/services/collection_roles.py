"""Roles of the Zotero collections of a review: automatic or screened results.

A review's Zotero group holds two kinds of collections:

- **automatic** ones, filled by SciLEx: the first collect, each extension
  (``Extension_Collect_…``, ``Extension N · BibTeX · …``);
- **screened results**: the collections people fill by hand after reading the
  papers (e.g. ``surveys``, ``benchmark``, ``models``, ``datasets``). Each may
  give a paper type (:mod:`scilex.paper_types`).

The roles are saved in ``collection_roles.yml`` (review folder). Once a review
has a screened collection:

- Explore and the Dashboard show the screened papers by default
  (:func:`filter_scope`, with Automatic / All for checking);
- :func:`apply` makes the ``PAPER_TYPE:`` tags of a screened paper those of its
  collections, and tags it ``KEEP:screened``: a person's choice wins over the
  eligibility criteria (their ``DELETED_BY:filter:`` tags stay as a warning
  but no longer discard the paper, see :mod:`scilex.review_tags`);
- the PRISMA flow ends with the screened collections (:mod:`.prisma`).

A paper's collections are the ``zotero_collections`` column (paths such as
``models / Website``); :func:`refresh_from_zotero` reads them again from the
group, since moving a paper between collections in Zotero changes no field.
A sub-collection without its own role takes its parent's.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import yaml

from scilex import paper_types, review_tags

FILENAME = "collection_roles.yml"
AUTOMATIC, SCREENED = "automatic", "screened"
ROLES = {AUTOMATIC: "Automatic", SCREENED: "Screened results"}
SCOPE_SCREENED, SCOPE_AUTOMATIC, SCOPE_ALL = "screened", "automatic", "all"
SCOPES = {
    SCOPE_SCREENED: "Screened results",
    SCOPE_AUTOMATIC: "Automatic only",
    SCOPE_ALL: "All papers",
}
COLUMN = "zotero_collections"

# Names of the collections SciLEx creates (collect, extensions).
_AUTOMATIC_NAME = re.compile(
    r"^(extension\b|extension_|collect|aggregat|snowball|import\b|.*\bbibtex\b)",
    re.IGNORECASE,
)
_TYPE_CUES = (
    (re.compile(r"survey|review|state[- ]of[- ]the[- ]art|sota", re.I), "REVIEW"),
    (re.compile(r"bench", re.I), "BENCHMARK"),
    (re.compile(r"data ?set|corpus|corpora", re.I), "DATASET"),
    (re.compile(r"model|method|approach|system", re.I), "MODEL"),
)


@dataclass
class CollectionRole:
    """The role of one collection (``path`` as ``Parent / Child``)."""

    key: str
    path: str
    role: str = AUTOMATIC
    paper_type: str | None = None  # a value of paper_types.TYPES, screened only


def path_of(folder: Path) -> Path:
    return Path(folder) / FILENAME


def guess_role(path: str, review_name: str = "") -> str:
    """Default role from the name: SciLEx's own collections are automatic."""
    top = path.split(" / ")[0].strip()
    if _AUTOMATIC_NAME.match(top) or (review_name and top == review_name):
        return AUTOMATIC
    return SCREENED


def guess_type(path: str) -> str | None:
    """Paper type a collection name suggests (``surveys`` -> Review…)."""
    top = path.split(" / ")[0]
    for pattern, name in _TYPE_CUES:
        if pattern.search(top):
            return getattr(paper_types, name)
    return None


def load(folder: Path) -> dict[str, CollectionRole]:
    """Saved roles by collection path (empty: roles never set)."""
    path = path_of(folder)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    roles: dict[str, CollectionRole] = {}
    for entry in data.get("collections") or []:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        role = entry.get("role") if entry.get("role") in ROLES else AUTOMATIC
        kind = entry.get("paper_type")
        roles[str(entry["path"])] = CollectionRole(
            key=str(entry.get("key") or ""),
            path=str(entry["path"]),
            role=role,
            paper_type=kind if role == SCREENED and kind in paper_types.TYPES else None,
        )
    return roles


def save(folder: Path, roles: list[CollectionRole]) -> Path:
    path = path_of(folder)
    body = {
        "collections": [
            {k: v for k, v in asdict(r).items() if v is not None} for r in roles
        ]
    }
    path.write_text(
        "# Roles of the review's Zotero collections (SciLEx, Zotero group page).\n"
        + yaml.safe_dump(body, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def proposal(
    collections, saved: dict[str, CollectionRole], review_name: str = ""
) -> list[CollectionRole]:
    """A role for each collection of the library: saved, else guessed.

    ``collections``: :class:`~.zotero_library.ZoteroCollection` objects.
    """
    found = []
    for collection in collections:
        known = saved.get(collection.path)
        if known is None:
            role = guess_role(collection.path, review_name)
            known = CollectionRole(
                key=collection.key,
                path=collection.path,
                role=role,
                paper_type=guess_type(collection.path) if role == SCREENED else None,
            )
        found.append(known)
    return found


def configured(roles: dict[str, CollectionRole]) -> bool:
    """True once at least one collection holds screened results."""
    return any(r.role == SCREENED for r in roles.values())


def _role_for(path: str, roles: dict[str, CollectionRole]) -> CollectionRole | None:
    """The role of ``path``, else of its nearest parent with one."""
    parts = path.split(" / ")
    for end in range(len(parts), 0, -1):
        found = roles.get(" / ".join(parts[:end]))
        if found is not None:
            return found
    return None


def screened_collections(row, roles: dict[str, CollectionRole]) -> list[str]:
    """The screened collections of a results row (paths)."""
    found = []
    for path in review_tags.split_tags(row.get(COLUMN)):
        role = _role_for(path, roles)
        if role is not None and role.role == SCREENED:
            found.append(path)
    return found


def types_of(row, roles: dict[str, CollectionRole]) -> list[str]:
    """The paper types the screened collections of a row give, in type order."""
    kinds = set()
    for path in screened_collections(row, roles):
        role = _role_for(path, roles)
        if role and role.paper_type:
            kinds.add(role.paper_type)
    return [t for t in paper_types.TYPES if t in kinds]


def scope_mask(data: pd.DataFrame, roles: dict[str, CollectionRole]) -> pd.Series:
    """True for the rows in a screened collection."""
    if COLUMN not in data.columns:
        return pd.Series(False, index=data.index)
    return pd.Series(
        [bool(screened_collections(r, roles)) for r in data.to_dict("records")],
        index=data.index,
    )


def filter_scope(
    data: pd.DataFrame, roles: dict[str, CollectionRole], scope: str
) -> pd.DataFrame:
    """The rows of ``scope`` (all rows while no collection is screened)."""
    if scope == SCOPE_ALL or not configured(roles):
        return data
    mask = scope_mask(data, roles)
    return data[mask] if scope == SCOPE_SCREENED else data[~mask]


def default_scope(roles: dict[str, CollectionRole]) -> str:
    return SCOPE_SCREENED if configured(roles) else SCOPE_ALL


# ---------------------------------------------------------------------------
# Writing: collections from Zotero, then types and KEEP:screened tags
# ---------------------------------------------------------------------------


def _match_keys(record: dict) -> list[str]:
    """DOI and normalized title of a row or a Zotero item's data."""
    from scilex.gui.services.zotero_sync import _match_key

    return [k for k in _match_key(record) if not k.startswith("url:")]


def merge_collections(
    data: pd.DataFrame,
    items: list[dict],
    paths: dict[str, str],
    roles: dict[str, CollectionRole] | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """``data`` with each row's collections read from the Zotero ``items``.

    A row gets the collections of its linked item (``zotero_key``) and of the
    copies of the same paper (same DOI or title) no row is linked to: a person
    often files a second copy of a paper in a screened collection. A copy goes
    to one row only. A linked item gone from
    the library leaves the row without collections. With ``roles``, the
    papers of a screened collection SciLEx does not have are added.

    Returns the new table and counts: ``changed``, ``gone``, ``added``.
    """
    from scilex.gui.services.zotero_library import item_to_row

    data = data.copy()
    if COLUMN not in data.columns:
        data[COLUMN] = ""
    data[COLUMN] = data[COLUMN].astype(object)
    if "zotero_key" not in data.columns:
        data["zotero_key"] = ""

    def collections_of(item: dict) -> list[str]:
        member = item.get("data", {}).get("collections") or []
        return sorted(paths[k] for k in member if k in paths)

    by_key = {item["key"]: item for item in items}
    by_match: dict[str, list[dict]] = {}
    for item in items:
        for key in _match_keys(item.get("data", {})):
            by_match.setdefault(key, []).append(item)
    counts = {"changed": 0, "gone": 0, "added": 0}
    linked = {k.strip() for k in data["zotero_key"] if isinstance(k, str) and k.strip()}
    covered: set[str] = set()  # Zotero items that have a row
    for index, row in zip(data.index, data.to_dict("records"), strict=True):
        key = row.get("zotero_key")
        key = key.strip() if isinstance(key, str) else ""
        same = [by_key[key]] if key in by_key else []
        # A copy no row is linked to belongs to the first row of its paper
        # only: a paper SciLEx holds twice is not counted twice.
        for match in _match_keys(row):
            same += [
                item
                for item in by_match.get(match, [])
                if item["key"] not in linked and item["key"] not in covered
            ]
        if not same and not key:
            continue  # never in Zotero: left as it is
        if key and key not in by_key:
            counts["gone"] += 1
        found: set[str] = set()
        for item in same:
            covered.add(item["key"])
            found.update(collections_of(item))
        value = ";".join(sorted(found))
        old = row.get(COLUMN)
        if (old if isinstance(old, str) else "") != value:
            data.at[index, COLUMN] = value
            counts["changed"] += 1
    if roles and configured(roles):
        new_rows = []
        for item in items:
            if item["key"] in covered:
                continue
            item_paths = collections_of(item)
            if not screened_collections({COLUMN: ";".join(item_paths)}, roles):
                continue
            covered.update(
                i["key"]
                for k in _match_keys(item.get("data", {}))
                for i in by_match.get(k, [])
            )
            item = {**item, "_scilex_collections": item_paths}
            new_rows.append(item_to_row(item))
        if new_rows:
            data = pd.concat([data, pd.DataFrame(new_rows)], ignore_index=True)
            counts["added"] = len(new_rows)
    return data, counts


def refresh_from_zotero(
    review, roles: dict[str, CollectionRole] | None = None
) -> dict[str, int]:
    """Read every paper's collections from the group (:func:`merge_collections`).

    Papers no longer in the library (deleted or in the trash) lose their
    collections, so they leave the screened results; the screened papers
    missing in SciLEx are added (``roles``: default, the saved ones).
    """
    from scilex.gui.services import journal, results_store, zotero_library
    from scilex.gui.services.extend import read_results, write_results
    from scilex.gui.services.keys_editor import effective_keys

    source = zotero_library.load_source(review.folder)
    if source is None:
        raise ValueError("The review has no Zotero group yet.")
    roles = load(review.folder) if roles is None else roles
    api = zotero_library.client(effective_keys(review.folder), library=source)
    collections = zotero_library.list_collections(api)
    paths = {c.key: c.path for c in collections}
    items = zotero_library.fetch_papers(api, None)
    with results_store.lock_for(review.results_path):
        data = read_results(review.results_path)
        if data is None:
            return {"changed": 0, "gone": 0, "added": 0}
        merged, counts = merge_collections(data, items, paths, roles)
        if counts["changed"] or counts["added"]:
            write_results(merged, review.results_path)
    if counts["added"]:
        journal.append(
            review.folder,
            "papers-added",
            params={"category": "screening", "source": "screened collections"},
            generated={"added": counts["added"]},
            message=(
                f"{counts['added']} papers of the screened collections added "
                "from Zotero."
            ),
        )
    return counts


def apply(review, roles: dict[str, CollectionRole] | None = None) -> dict[str, int]:
    """Tag the screened papers: their collections' types and ``KEEP:screened``.

    A paper that left every screened collection loses ``KEEP:screened`` (its
    types stay). Returns ``{"screened", "typed", "kept_tagged", "untagged"}``.
    """
    from scilex.gui.services import journal, results_store
    from scilex.gui.services.extend import read_results

    roles = load(review.folder) if roles is None else roles
    data = read_results(review.results_path)
    counts = {"screened": 0, "typed": 0, "kept_tagged": 0, "untagged": 0}
    if data is None:
        return counts
    before = data.copy()
    if "tags" not in data.columns:
        data["tags"] = ""
        before["tags"] = ""
    data["tags"] = data["tags"].astype(object)
    keep = review_tags.SCREENED_KEEP
    for index, row in zip(data.index, data.to_dict("records"), strict=True):
        tags = review_tags.split_tags(row.get("tags"))
        has_keep = keep.casefold() in {t.casefold() for t in tags}
        if screened_collections(row, roles):
            counts["screened"] += 1
            add, remove = [], []
            kinds = types_of(row, roles)
            if kinds:
                add, remove = paper_types.tag_changes(row, kinds)
                counts["typed"] += bool(add or remove)
                if add or remove:
                    paper_types.set_origin(data, index, paper_types.COLLECTION_ROLE)
            if not has_keep:
                add.append(keep)
                counts["kept_tagged"] += 1
            if add or remove:
                data.at[index, "tags"] = review_tags.with_tags(
                    row.get("tags"), add, remove
                )
        elif has_keep:
            data.at[index, "tags"] = review_tags.with_tags(row.get("tags"), (), [keep])
            counts["untagged"] += 1
    if counts["typed"] or counts["kept_tagged"] or counts["untagged"]:
        results_store.write_changes(review.results_path, before, data)
    journal.append(
        review.folder,
        "collection-roles",
        params={
            "category": "screening",
            "screened_collections": sorted(
                p for p, r in roles.items() if r.role == SCREENED
            ),
        },
        generated=counts,
        message=(
            f"Screened results: {counts['screened']} papers; "
            f"{counts['typed']} paper types set from their collections."
        ),
    )
    return counts


def summary(data: pd.DataFrame, roles: dict[str, CollectionRole]) -> dict:
    """Counts for the workflow: per screened collection, per type, totals."""
    per_collection: dict[str, int] = {}
    per_type: dict[str, int] = {}
    screened = 0
    with_filter_tag = 0
    for row in data.to_dict("records"):
        found = screened_collections(row, roles)
        if not found:
            continue
        screened += 1
        for path in found:
            per_collection[path] = per_collection.get(path, 0) + 1
        for kind in types_of(row, roles) or paper_types.types_of(row):
            per_type[kind] = per_type.get(kind, 0) + 1
        if any(
            who.startswith(review_tags.FILTER_PREFIX)
            for who in review_tags.workflow(row.get("tags")).deleted_by
        ):
            with_filter_tag += 1
    return {
        "screened": screened,
        "automatic": len(data) - screened,
        "per_collection": per_collection,
        "per_type": per_type,
        "with_filter_tag": with_filter_tag,
    }
