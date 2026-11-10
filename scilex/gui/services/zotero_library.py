"""Read a Zotero library and start a review from an existing collection.

A review created this way skips the collection: the papers of the Zotero
collection become the review's aggregated results, so Screen, Export,
Analyses and Annotate work at once. The keywords, years and annotation grid
are deduced from the papers when no configuration file is given:

- keywords: the ``Collect_KW<n>:term`` tags SciLEx writes when pushing;
- years: the range of the papers' dates;
- annotation grid: the ``DIMENSION:Value`` tags annotators added.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from scilex.constants import MISSING_VALUE, extract_year
from scilex.init_templates import skeleton_text
from scilex.io_utils import write_aggregated_csv
from scilex.settings.loader import CONFIG_FILENAME
from scilex.settings.migrate import legacy_to_settings
from scilex.settings.resolve import is_legacy_format
from scilex.settings.schema import ScilexSettings, SettingsError
from scilex.tagging.grid import (
    COLLECT_KEYWORD_TAG,
    GRID_FILENAME,
    deduce_grid,
    deduce_keyword_groups,
    is_paper,
    save_grid,
)

logger = logging.getLogger(__name__)

SOURCE_FILENAME = "zotero_source.yml"
DOI_IN_EXTRA = re.compile(r"^\s*DOI:\s*(\S+)", re.I | re.M)
VENUE_FIELDS = (
    "publicationTitle",
    "proceedingsTitle",
    "bookTitle",
    "journalAbbreviation",
    "conferenceName",
)


class ZoteroNotConfiguredError(ValueError):
    """The API keys file has no complete Zotero block."""


@dataclass(frozen=True)
class ZoteroCollection:
    """One collection of the library, with its full path (``Parent / Child``)."""

    key: str
    path: str
    num_items: int = 0
    parent: str | None = None  # key of the parent collection


@dataclass(frozen=True)
class ZoteroSource:
    """The review's Zotero library and collection (saved as ``zotero_source.yml``).

    Each review chooses its own: a user or group library, then a collection
    (``collection_key``) or the whole library (``collection_key`` None), with or
    without the sub-collections. The papers are read from it, pushed to it, and
    the knowledge graph is exported from it.
    """

    library_id: str
    library_type: str
    collection_key: str | None
    collection_name: str
    include_subcollections: bool = True
    library_name: str = ""

    @property
    def whole_library(self) -> bool:
        """True when the review uses the whole library, not one collection."""
        return not self.collection_key

    def describe(self) -> str:
        """Human description, e.g. ``group 'Lab' / Reviews / RE (+ sub-collections)``."""
        library = self.library_name or f"{self.library_type} {self.library_id}"
        if self.whole_library:
            return f"{library} (whole library)"
        sub = " (+ sub-collections)" if self.include_subcollections else ""
        return f"{library} / {self.collection_name}{sub}"


@dataclass(frozen=True)
class ZoteroLibrary:
    """A library the key can read: the user's own, or one of their groups."""

    library_type: str  # "user" or "group"
    library_id: str
    name: str


@dataclass
class ImportSummary:
    """What was created from the Zotero collection."""

    papers: int = 0
    keyword_groups: list[list[str]] = field(default_factory=list)
    years: str = ""
    grid_dimensions: int = 0
    config_from: str = "deduced"  # "deduced" or the configuration file used
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Library access
# ---------------------------------------------------------------------------


def zotero_credentials(keys: dict) -> tuple[str, str, str]:
    """Return ``(api_key, library_id, library_type)`` from the keys file content.

    Raises:
        ZoteroNotConfiguredError: If the key or the library id is missing.
    """
    block = keys.get("Zotero") or keys.get("zotero") or {}
    api_key, library_id = block.get("api_key"), block.get("user_id")
    if isinstance(api_key, list):
        api_key = api_key[0] if api_key else None
    if not api_key or not library_id:
        raise ZoteroNotConfiguredError(
            "Zotero is not configured: set its key and library id on the API keys page."
        )
    return str(api_key), str(library_id), str(block.get("user_mode") or "user")


def client(keys: dict | None = None, library: ZoteroLibrary | ZoteroSource | None = None):
    """Return a ``ZoteroAPI`` for ``library``, else for the library of the keys file."""
    from scilex.gui.services import keys_editor
    from scilex.Zotero.zotero_api import ZoteroAPI

    api_key, library_id, library_type = zotero_credentials(
        keys if keys is not None else keys_editor.load_keys()
    )
    if library is not None:
        library_id, library_type = library.library_id, library.library_type
    return ZoteroAPI(user_id=library_id, user_role=library_type, api_key=api_key)


def list_libraries(keys: dict | None = None) -> list[ZoteroLibrary]:
    """Return the libraries the key can read: the one of the keys file, then its groups.

    Raises:
        ZoteroNotConfiguredError: If the key or the library id is missing.
        ConnectionError: If the groups cannot be listed.
    """
    api = client(keys)
    own = ZoteroLibrary(
        api.user_role,
        str(api.user_id),
        "My library" if api.user_role == "user" else f"Group {api.user_id}",
    )
    groups = api.get_groups()
    if groups is None:
        raise ConnectionError("Cannot list the Zotero groups (check the key).")
    found = [
        ZoteroLibrary(
            "group",
            str(group.get("id") or group.get("data", {}).get("id")),
            f"Group: {group.get('data', {}).get('name', group.get('id'))}",
        )
        for group in groups
    ]
    return [own, *sorted(found, key=lambda lib: lib.name.lower())]


def descendant_keys(collections: list[ZoteroCollection], key: str) -> list[str]:
    """Return ``key`` and the keys of every collection below it."""
    children: dict[str, list[str]] = {}
    for collection in collections:
        if collection.parent:
            children.setdefault(collection.parent, []).append(collection.key)
    found, stack = [], [key]
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.append(current)
        stack.extend(children.get(current, []))
    return found


def fetch_source_papers(
    api, source: ZoteroSource, collections: list[ZoteroCollection] | None = None
) -> list[dict]:
    """Return the papers of the review's library / collection(s), each once.

    Every item gets ``_scilex_collections``: the paths of the chosen collections
    it belongs to (its sub-corpora).

    Raises:
        ConnectionError: If a page cannot be fetched.
    """
    collections = collections if collections is not None else list_collections(api)
    paths = {c.key: c.path for c in collections}
    if source.whole_library:
        items = fetch_papers(api, None)
        wanted = set(paths)
    else:
        keys = (
            descendant_keys(collections, source.collection_key)
            if source.include_subcollections
            else [source.collection_key]
        )
        wanted = set(keys)
        by_key: dict[str, dict] = {}
        for key in keys:
            for item in fetch_papers(api, key):
                by_key.setdefault(item.get("key") or id(item), item)
        items = list(by_key.values())
    for item in items:
        member = item.get("data", {}).get("collections") or []
        item["_scilex_collections"] = sorted(paths[k] for k in member if k in wanted)
    return items


def split_by_collection(items: list[dict]) -> dict[str, list[dict]]:
    """Group papers by sub-corpus (collection path); a paper may be in several."""
    groups: dict[str, list[dict]] = {}
    for item in items:
        for path in item.get("_scilex_collections") or []:
            groups.setdefault(path, []).append(item)
    return groups


def export_source_biblatex(api, source: ZoteroSource, collections=None) -> tuple[str, dict]:
    """Return the BibLaTeX export of the review's Zotero source and its sub-corpora.

    Returns:
        ``(biblatex text, {collection path: [citation keys]})``; the mapping is
        empty for a single collection without sub-collections.

    Raises:
        ConnectionError: If an export page fails.
    """
    from scilex.kg.bib2json import convert_string

    def export(key: str | None) -> str:
        text = api.export_top_items(key, "biblatex")
        if text is None:
            raise ConnectionError(f"Cannot export the Zotero collection {key or '(library)'}")
        return text

    if source.whole_library:
        collections = collections if collections is not None else list_collections(api)
        keys = [c.key for c in collections]
        full = export(None)
    elif source.include_subcollections:
        collections = collections if collections is not None else list_collections(api)
        keys = descendant_keys(collections, source.collection_key)
        full = None
    else:
        return export(source.collection_key), {}
    paths = {c.key: c.path for c in collections or []}
    parts: list[str] = []
    subcorpora: dict[str, list[str]] = {}
    for key in keys:
        text = export(key)
        parts.append(text)
        cited = [entry["ID"] for entry in convert_string(text, key)["entries"]]
        if cited:
            subcorpora[paths.get(key, key)] = cited
    # Duplicated entries (a paper in two collections) are dropped by bib2json.
    return (full if full is not None else "\n".join(parts)), subcorpora


def list_collections(api) -> list[ZoteroCollection]:
    """Return the library's collections sorted by path.

    Raises:
        ConnectionError: If Zotero cannot be reached or refuses the key.
    """
    raw = api.get_collections()
    if raw is None:
        raise ConnectionError(
            "Cannot list the Zotero collections (check the key and library id)."
        )
    by_key = {c["data"]["key"]: c for c in raw}

    def path_of(key: str, seen: frozenset = frozenset()) -> str:
        data = by_key[key]["data"]
        parent = data.get("parentCollection")
        name = data.get("name", key)
        if parent and parent in by_key and parent not in seen:
            return f"{path_of(parent, seen | {key})} / {name}"
        return name

    collections = [
        ZoteroCollection(
            key=key,
            path=path_of(key),
            num_items=int(by_key[key].get("meta", {}).get("numItems", 0) or 0),
            # Zotero sends parentCollection: false for a top-level collection.
            parent=by_key[key]["data"].get("parentCollection") or None,
        )
        for key in by_key
    ]
    return sorted(collections, key=lambda c: c.path.lower())


def fetch_papers(api, collection_key: str | None) -> list[dict]:
    """Return the papers (top-level items) of a collection, or of the library.

    Raises:
        ConnectionError: If a page cannot be fetched.
    """
    items = api.get_top_items(collection_key)
    if items is None:
        raise ConnectionError("Cannot read the papers of this Zotero collection.")
    return [item for item in items if is_paper(item)]


# ---------------------------------------------------------------------------
# Papers -> aggregated results
# ---------------------------------------------------------------------------


def _authors(creators: list[dict]) -> str:
    names = []
    for creator in creators or []:
        if creator.get("creatorType", "author") not in ("author", "editor"):
            continue
        name = creator.get("name") or " ".join(
            part for part in (creator.get("firstName"), creator.get("lastName")) if part
        )
        if name:
            names.append(name.strip())
    return ";".join(names)


def _doi(data: dict) -> str:
    doi = (data.get("DOI") or "").strip()
    if not doi:
        match = DOI_IN_EXTRA.search(data.get("extra") or "")
        doi = match.group(1) if match else ""
    return doi


def item_to_row(item: dict) -> dict:
    """Map a Zotero item to a row of ``aggregated_results.csv``."""
    data = item.get("data", {})
    tags = [str(t.get("tag", "")).strip() for t in data.get("tags", [])]
    keyword_tags = [t for t in tags if COLLECT_KEYWORD_TAG.match(t)]
    other_tags = [t for t in tags if t and t not in keyword_tags]
    venue = next((data[f] for f in VENUE_FIELDS if data.get(f)), "")
    row = {
        "title": data.get("title", ""),
        "publisher": data.get("publisher", ""),
        "itemType": data.get("itemType", ""),
        "authors": _authors(data.get("creators", [])),
        "language": data.get("language", ""),
        "abstract": data.get("abstractNote", ""),
        "archiveID": item.get("key", ""),
        "archive": "Zotero",
        "date": data.get("date", ""),
        "DOI": _doi(data),
        "url": data.get("url", ""),
        "rights": data.get("rights", ""),
        "pages": data.get("pages", ""),
        "journalAbbreviation": venue,
        "volume": data.get("volume", ""),
        "issue": data.get("issue", ""),
        "conferenceName": data.get("conferenceName", ""),
        "collect_keywords": ";".join(keyword_tags),
        "tags": ";".join(other_tags),
        "extra": data.get("extra", ""),
        "zotero_key": item.get("key", ""),
        # Sub-corpora: the chosen collections the paper belongs to.
        "zotero_collections": ";".join(item.get("_scilex_collections") or []),
    }
    return {
        key: (value if value not in (None, "") else MISSING_VALUE)
        for key, value in row.items()
    }


def items_to_results(items: list[dict]) -> pd.DataFrame:
    """Return the aggregated-results table of ``items`` (papers only)."""
    return pd.DataFrame([item_to_row(item) for item in items if is_paper(item)])


def year_range(items: list[dict]) -> str:
    """Return ``"first-last"`` year of the papers' dates ('' when none has a year)."""
    years = [
        year
        for item in items
        if (year := extract_year(item.get("data", {}).get("date"))) is not None
    ]
    if not years:
        return ""
    return f"{min(years)}-{max(years)}"


# ---------------------------------------------------------------------------
# Review creation
# ---------------------------------------------------------------------------


def _read_config_file(path: Path) -> dict:
    """Read a ``scilex.yml`` or a legacy ``scilex.config.yml`` (+ advanced file)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: expected a mapping at the top level")
    if is_legacy_format(data):
        advanced_path = path.with_name("scilex.advanced.yml")
        advanced = (
            yaml.safe_load(advanced_path.read_text(encoding="utf-8")) or {}
            if advanced_path.is_file()
            else None
        )
        data = legacy_to_settings(data, advanced)
    return data


def build_settings(
    name: str, items: list[dict], config_file: Path | None, summary: ImportSummary
) -> dict:
    """Return the ``scilex.yml`` content of the new review.

    Values of ``config_file`` win; keywords and years missing from it are
    deduced from the papers.
    """
    if config_file is not None:
        data = _read_config_file(config_file)
        summary.config_from = str(config_file)
    else:
        data = yaml.safe_load(skeleton_text(name))
    data["name"] = name
    search = data.setdefault("search", {})

    deduced_keywords = deduce_keyword_groups(items)
    summary.keyword_groups = deduced_keywords
    if config_file is None or not search.get("keywords"):
        if deduced_keywords:
            # SciLEx searches with at most two groups (group1 AND group2).
            search["keywords"] = deduced_keywords[:2]
        else:
            summary.warnings.append(
                "No Collect_KW tag found: the keywords are placeholders, set them "
                "in ① Configure before collecting more papers."
            )
    summary.keyword_groups = search.get("keywords", [])

    years = year_range(items)
    if config_file is None or not search.get("years"):
        if years:
            search["years"] = years
        else:
            summary.warnings.append("No paper has a date: the years are a placeholder.")
    summary.years = str(search.get("years", ""))
    return data


def _validate(data: dict) -> None:
    from pydantic import ValidationError

    from scilex.settings.schema import format_validation_error

    try:
        ScilexSettings.model_validate(data)
    except ValidationError as exc:
        raise SettingsError(format_validation_error(exc, data)) from exc


def create_review_from_zotero(
    workspace,
    folder: Path,
    name: str,
    source: ZoteroSource,
    items: list[dict],
    config_file: Path | None = None,
):
    """Create a review whose results are the papers of a Zotero collection.

    Writes ``scilex.yml``, ``output/<name>/aggregated_results.csv``,
    ``annotation_grid.csv`` (when the papers carry annotations) and
    ``zotero_source.yml`` in ``folder``, then registers the review.

    Returns:
        ``(review, summary)``.

    Raises:
        FileExistsError: If the folder already holds a ``scilex.yml``.
        SettingsError: If the configuration (given or deduced) is invalid.
        ValueError: If the collection has no paper.
    """
    from scilex.gui.services.workspace import resolve_folder

    papers = [item for item in items if is_paper(item)]
    if not papers:
        raise ValueError(
            f"The Zotero collection '{source.collection_name}' has no paper."
        )
    folder = resolve_folder(folder)
    config_path = folder / CONFIG_FILENAME
    if config_path.exists():
        raise FileExistsError(f"{config_path} already exists")

    summary = ImportSummary(papers=len(papers))
    data = build_settings(name, papers, config_file, summary)
    _validate(data)

    folder.mkdir(parents=True, exist_ok=True)
    header = (
        f"# scilex.yml: created from the Zotero collection '{source.collection_name}' "
        f"on {dt.date.today().isoformat()}.\n"
    )
    config_path.write_text(
        header
        + yaml.safe_dump(
            data, sort_keys=False, default_flow_style=None, allow_unicode=True
        ),
        encoding="utf-8",
    )
    try:
        review = workspace.open_review(folder)
        review.collection_dir.mkdir(parents=True, exist_ok=True)
        write_aggregated_csv(
            items_to_results(papers),
            str(review.results_path),
            quoting=csv.QUOTE_NONNUMERIC,
        )
        grid = deduce_grid(papers)
        summary.grid_dimensions = len(grid)
        if len(grid):
            save_grid(grid, folder / GRID_FILENAME)
        save_source(folder, source)
        from scilex.gui.services.overview import record_snapshot, zotero_tags

        record_snapshot(folder, zotero_tags(papers), "import")
    except BaseException:
        # Leave no half-created review: the user can retry the import.
        workspace.forget_review(folder)
        config_path.unlink(missing_ok=True)
        raise
    return review, summary


def save_source(folder: Path, source: ZoteroSource) -> Path:
    """Remember the Zotero library and collection a review is linked to."""
    path = Path(folder) / SOURCE_FILENAME
    path.write_text(
        yaml.safe_dump(
            {
                "library_id": source.library_id,
                "library_type": source.library_type,
                "collection_key": source.collection_key,
                "collection_name": source.collection_name,
                "include_subcollections": source.include_subcollections,
                "library_name": source.library_name,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def load_source(folder: Path) -> ZoteroSource | None:
    """Return the Zotero library and collection of a review, if it has chosen one."""
    path = Path(folder) / SOURCE_FILENAME
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return ZoteroSource(
            library_id=str(data["library_id"]),
            library_type=str(data.get("library_type") or "user"),
            collection_key=data.get("collection_key") or None,
            collection_name=str(data.get("collection_name") or ""),
            # Files written before sub-collections were supported: one collection.
            include_subcollections=bool(data.get("include_subcollections", False)),
            library_name=str(data.get("library_name") or ""),
        )
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        logger.warning("Ignoring unreadable %s: %s", path, exc)
        return None
