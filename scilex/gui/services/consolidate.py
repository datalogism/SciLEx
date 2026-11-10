"""Consolidate a review: deduplicate and filter the corpus after it was extended.

The aggregation deduplicates and filters the papers of the keyword collection
only. Papers added later (Extend collect, Zotero, BibTeX, knowledge graph,
snowball) are merged by exact DOI or exact title + year, so the same paper can
come in twice (preprint and published version, small title variants), and the
filters of ``scilex.yml`` never saw them. Consolidation works on the whole
corpus, in two steps that are previewed before being applied:

**Duplicates** are papers with the same DOI, the same normalised title, or
titles at least ``similarity`` % alike (rapidfuzz ratio) published at most one
year apart. Copies in different sub-corpora (Zotero collections) are not
grouped by default: a review may annotate a paper once per role on purpose
(e.g. once as a model and once as a dataset). Within a sub-corpus, one paper
can also describe several datasets, so each group is shown to the user, who
ticks the groups to merge; a group is pre-ticked only when its copies do not
carry different annotations.

Each merged group keeps its most complete record (same score as the
aggregation, then a Zotero-linked one, then the first). The others are merged
into it: sources, keywords and sub-corpora are united, its empty fields are
filled, and it gets the ``DIMENSION:value`` annotations of the dimensions it has
not coded (its own codes win, so no contradictory codes appear). A screening
decision moves to the kept paper (its own decision wins; a disagreement is
reported in its note). Then the other copies are removed.

**Filters** are those of ``scilex.yml`` (``quality_filters``): year range, item
type whitelist, required abstract / DOI / year, minimum number of authors,
abstract length. As in the aggregation, the quality rules spare the item types
of ``always_keep``. By default only papers found by queries (Collect, Extend
collect, Snowball) are filtered: imported papers (Zotero, BibTeX, knowledge
graph) were chosen by hand. Papers included in ③ Screen are never filtered out.
Filtered papers are excluded in ③ Screen (reversible, the reason in the note),
or removed from the results.

**Required sub-corpora** (``subcorpora.required`` of ``scilex.yml``, e.g.
``[datasets, surveys, models]``): every paper must be in at least one
collection of that name or under it (``models / Website`` counts as models).
The papers in none are listed with a suggested sub-corpus (a collection whose
name starts with it, such as a Zotero import collection ``datasets 10/11/2026
15:35:35``); :func:`classify` adds them to it, in Zotero for linked papers.

Results are backed up before anything is written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from scilex.constants import extract_year, is_valid, normalize_doi
from scilex.gui.services.workspace import Review

DEFAULT_SIMILARITY = 95
SET_COLUMNS = {  # column -> separator of its values, united on merge
    "collect_keywords": ";",
    "tags": ";",
    "zotero_collections": ";",
    "bonus_keyword_tags": "|",
}
NOTE_PREFIX = "Consolidate:"
IMPORTED = {"Zotero import", "BibTeX import", "Knowledge graph import"}

EXCLUDE_IN_SCREEN, REMOVE = "exclude", "remove"
PAST = {"include": "included", "exclude": "excluded", "maybe": "marked maybe"}


@dataclass
class DuplicateGroup:
    """Papers found to be the same; ``keep`` is the row kept."""

    keep: int  # results index
    others: list[int]
    reason: str  # "DOI", "title", "similar titles (97%)"
    titles: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)  # per copy, keep first
    code_counts: list[int] = field(
        default_factory=list
    )  # DIMENSION:value tags per copy
    # Codes some copies have and others lack, on dimensions both coded.
    differing_codes: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        """True when merging loses no annotation (pre-ticked in the page)."""
        return not self.differing_codes


@dataclass
class FilteredPaper:
    """A paper a filter of scilex.yml rejects."""

    index: int
    paper_key: str
    title: str
    reasons: list[str]


@dataclass
class Unclassified:
    """A paper in none of the required sub-corpora."""

    index: int
    title: str
    collections: str
    zotero_key: str
    suggestion: str | None  # required sub-corpus its collections hint at


@dataclass
class Plan:
    """What consolidation would do (see :func:`plan`)."""

    papers: int
    groups: list[DuplicateGroup]
    filtered: list[FilteredPaper]
    spared_included: int = 0  # filtered papers left alone because included
    required: list[str] = field(default_factory=list)  # subcorpora.required
    unclassified: list[Unclassified] = field(default_factory=list)

    @property
    def duplicates(self) -> int:
        """Rows that merging every group would remove."""
        return sum(len(group.others) for group in self.groups)

    def message(self) -> str:
        """One-line summary for the user."""
        text = (
            f"{self.papers} papers: {len(self.groups)} groups of duplicates "
            f"({self.duplicates} papers to merge), {len(self.filtered)} papers "
            "rejected by the filters of scilex.yml"
        )
        if self.spared_included:
            text += f" ({self.spared_included} more spared: included in ③ Screen)"
        if self.required:
            text += (
                f"; {len(self.unclassified)} papers in none of "
                f"{', '.join(self.required)}"
            )
        return text + "."


# -- duplicates ---------------------------------------------------------------


def _title(value) -> str:
    text = str(value).lower() if is_valid(value) else ""
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _year(value) -> int | None:
    return extract_year(value) if is_valid(value) else None


def _codes(value) -> dict[str, set[str]]:
    """``DIMENSION:value`` tags of a cell, by dimension."""
    codes: dict[str, set[str]] = {}
    for tag in _split(value, ";"):
        dimension, sep, code = tag.partition(":")
        if sep and dimension and code:
            codes.setdefault(dimension.upper(), set()).add(tag)
    return codes


def _subcorpora(value) -> set[str]:
    return {c.casefold() for c in _split(value, ";")}


class _Groups:
    """Union-find over row positions, remembering why rows were joined."""

    def __init__(self, size: int):
        self.parent = list(range(size))
        self.reason: dict[int, str] = {}

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, a: int, b: int, reason: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra
            self.reason.setdefault(ra, reason)


def find_duplicates(
    data: pd.DataFrame,
    similarity: int = DEFAULT_SIMILARITY,
    *,
    separate_subcorpora: bool = True,
) -> list[DuplicateGroup]:
    """Groups of duplicate papers in ``data`` (see the module docstring)."""
    from rapidfuzz import fuzz, process

    from scilex.crawlers.aggregate_parallel import _compute_dedup_quality

    if data.empty:
        return []
    positions = list(data.index)
    groups = _Groups(len(positions))
    titles = [_title(t) for t in data.get("title", pd.Series("", index=data.index))]
    years = [_year(d) for d in data.get("date", pd.Series(None, index=data.index))]
    dois = [
        normalize_doi(d) if is_valid(d) else ""
        for d in data.get("DOI", pd.Series("", index=data.index))
    ]

    corpora = [
        _subcorpora(v)
        for v in data.get("zotero_collections", pd.Series("", index=data.index))
    ]
    members_of: dict[int, set[str]] = {}

    def join(a: int, b: int, reason: str) -> None:
        """Join unless the two groups sit in different sub-corpora."""
        if separate_subcorpora:
            ca = members_of.get(groups.find(a), corpora[a])
            cb = members_of.get(groups.find(b), corpora[b])
            if ca and cb and ca != cb:
                return
        root_a, root_b = groups.find(a), groups.find(b)
        if root_a == root_b:
            return
        merged = members_of.get(root_a, corpora[a]) | members_of.get(root_b, corpora[b])
        groups.join(a, b, reason)
        members_of[groups.find(a)] = merged

    first: dict[str, int] = {}
    for pos, doi in enumerate(dois):
        if doi:
            if doi in first:
                join(first[doi], pos, "same DOI")
            else:
                first[doi] = pos
    first = {}
    for pos, title in enumerate(titles):
        if len(title) >= 10:
            if title in first:
                join(first[title], pos, "same title")
            else:
                first[title] = pos

    if similarity < 100:
        candidates = [pos for pos, title in enumerate(titles) if len(title) >= 20]
        if len(candidates) > 1:
            texts = [titles[pos] for pos in candidates]
            scores = process.cdist(
                texts,
                texts,
                scorer=fuzz.ratio,
                score_cutoff=similarity,
                dtype="uint8",
                workers=-1,
            )
            rows, cols = scores.nonzero()
            for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
                if i >= j:
                    continue
                a, b = candidates[i], candidates[j]
                ya, yb = years[a], years[b]
                if ya is not None and yb is not None and abs(ya - yb) > 1:
                    continue
                if (
                    dois[a]
                    and dois[b]
                    and dois[a] != dois[b]
                    and titles[a] != titles[b]
                ):
                    continue  # two DOIs and different titles: two papers
                join(a, b, f"similar titles ({int(scores[i, j])}%)")

    members: dict[int, list[int]] = {}
    for pos in range(len(positions)):
        members.setdefault(groups.find(pos), []).append(pos)

    quality = _compute_dedup_quality(data).tolist()
    linked = [
        is_valid(v) and bool(str(v).strip())
        for v in data.get("zotero_key", pd.Series("", index=data.index))
    ]
    tags = data.get("tags", pd.Series("", index=data.index)).tolist()
    result = []
    for root, group in members.items():
        if len(group) < 2:
            continue
        keep = max(group, key=lambda pos: (quality[pos], linked[pos], -pos))
        ordered = [keep, *[pos for pos in group if pos != keep]]
        codes = [_codes(tags[pos]) for pos in ordered]
        differing = set()
        for dimension in set().union(*codes):
            coded = [c[dimension] for c in codes if dimension in c]
            if len(coded) > 1 and any(c != coded[0] for c in coded):
                differing |= set().union(*coded) - set.intersection(*coded)
        result.append(
            DuplicateGroup(
                keep=positions[keep],
                others=[positions[pos] for pos in ordered[1:]],
                reason=groups.reason.get(root, "same paper"),
                titles=[str(data.at[positions[pos], "title"]) for pos in ordered],
                collections=[
                    ";".join(sorted(corpora[pos])) or "(none)" for pos in ordered
                ],
                code_counts=[sum(len(v) for v in c.values()) for c in codes],
                differing_codes=sorted(differing),
            )
        )
    result.sort(key=lambda g: (not g.safe, g.titles[0].lower()))
    return result


def _split(value, separator: str) -> list[str]:
    if not is_valid(value):
        return []
    return [part.strip() for part in str(value).split(separator) if part.strip()]


def merge_group(data: pd.DataFrame, group: DuplicateGroup) -> None:
    """Merge the rows of ``group.others`` into ``group.keep`` (in place)."""
    from scilex.constants import parse_archive_apis
    from scilex.crawlers.aggregate_parallel import _merge_archives_for_duplicates

    keep = group.keep
    rows = [keep, *group.others]
    if "tags" in data.columns:
        own = _split(data.at[keep, "tags"], ";")
        coded = set(_codes(data.at[keep, "tags"]))
        known = {t.casefold() for t in own}
        for row in group.others:
            for tag in _split(data.at[row, "tags"], ";"):
                dimension, sep, code = tag.partition(":")
                is_code = bool(sep and dimension and code)
                if tag.casefold() in known or (is_code and dimension.upper() in coded):
                    continue
                own.append(tag)
                known.add(tag.casefold())
            coded |= set(_codes(data.at[row, "tags"]))
        data.at[keep, "tags"] = ";".join(own)
    for column, separator in SET_COLUMNS.items():
        if column not in data.columns or column == "tags":
            continue
        values: dict[str, str] = {}
        for row in rows:
            for value in _split(data.at[row, column], separator):
                values.setdefault(value.casefold(), value)
        if values:
            data.at[keep, column] = separator.join(values.values())
    if "archive" in data.columns:
        names = [
            name for row in rows for name in parse_archive_apis(data.at[row, "archive"])
        ]
        names = list(dict.fromkeys(names))
        winner = (parse_archive_apis(data.at[keep, "archive"]) or [""])[0]
        if len(names) > 1:
            data.at[keep, "archive"] = _merge_archives_for_duplicates(names, winner)
    for column in data.columns:
        if column in SET_COLUMNS or column == "archive":
            continue
        if (
            not is_valid(data.at[keep, column])
            or str(data.at[keep, column]).strip() == ""
        ):
            for row in group.others:
                value = data.at[row, column]
                if is_valid(value) and str(value).strip():
                    data.at[keep, column] = value
                    break


# -- filters ------------------------------------------------------------------


def _words(text) -> int:
    return len(str(text).split()) if is_valid(text) else 0


def filter_reasons(record: dict, main_config: dict) -> list[str]:
    """Why the filters of ``scilex.yml`` reject a results row (empty: kept)."""
    rules = main_config.get("quality_filters") or {}
    reasons = []
    item_type = str(record.get("itemType") or "")
    year = _year(record.get("date"))
    years = main_config.get("years") or []
    in_range = year is None or not years or year in {int(y) for y in years}
    if rules.get("validate_year_range", True) and not in_range:
        reasons.append(f"year {year} outside {min(years)}-{max(years)}")
    allowed = rules.get("allowed_item_types")
    if rules.get("enable_itemtype_filter") and allowed and item_type not in allowed:
        reasons.append(f"type {item_type or '?'} not allowed")
    spared = rules.get("enable_itemtype_bypass") and item_type in (
        rules.get("bypass_item_types") or []
    )
    if spared:
        return reasons
    abstract = record.get("abstract")
    if rules.get("require_abstract") and not is_valid(abstract):
        reasons.append("no abstract")
    if rules.get("require_doi") and not is_valid(record.get("DOI")):
        reasons.append("no DOI")
    if rules.get("require_year") and year is None:
        reasons.append("no year")
    min_authors = rules.get("min_author_count") or 0
    authors = _split(record.get("authors"), ";")
    if min_authors and authors and len(authors) < min_authors:
        reasons.append(f"{len(authors)} author(s) < {min_authors}")
    words = _words(abstract)
    low, high = rules.get("min_abstract_words"), rules.get("max_abstract_words")
    if words and low and words < low:
        reasons.append(f"abstract of {words} words < {low}")
    if words and high and words > high:
        reasons.append(f"abstract of {words} words > {high}")
    return reasons


# -- plan and apply -----------------------------------------------------------


def _paths(value) -> list[str]:
    return [path.strip() for path in _split(value, ";")]


def roles_of(collections, required: list[str]) -> set[str]:
    """The required sub-corpora a paper's collections belong to (top level)."""
    wanted = {name.casefold(): name for name in required}
    roles = set()
    for path in _paths(collections):
        top = path.split("/")[0].strip().casefold()
        if top in wanted:
            roles.add(wanted[top])
    return roles


def suggest_role(collections, required: list[str]) -> str | None:
    """A required sub-corpus whose name starts one of the collections, if any."""
    for path in _paths(collections):
        top = path.split("/")[0].strip().casefold()
        for name in required:
            if top.startswith(name.casefold()):
                return name
    return None


def unclassified_papers(
    data: pd.DataFrame, required: list[str], skip: set[int] = frozenset()
) -> list[Unclassified]:
    """Papers of ``data`` in none of the ``required`` sub-corpora."""
    if not required:
        return []
    result = []
    collections = data.get("zotero_collections", pd.Series("", index=data.index))
    keys = data.get("zotero_key", pd.Series("", index=data.index))
    for index in data.index:
        if index in skip or roles_of(collections[index], required):
            continue
        key = keys[index]
        result.append(
            Unclassified(
                index=index,
                title=str(data.at[index, "title"]),
                collections=";".join(_paths(collections[index])) or "(none)",
                zotero_key=str(key).strip() if is_valid(key) else "",
                suggestion=suggest_role(collections[index], required),
            )
        )
    return result


def classify(review: Review, assignments: dict[int, str]) -> str:
    """Add papers to a required sub-corpus; return a summary.

    ``assignments``: results index -> sub-corpus name. A paper linked to Zotero
    is added to the top-level collection of that name in the review's library
    (created if missing; its other collections are kept); the
    ``zotero_collections`` column follows. Unlinked papers change in SciLEx only.
    """
    from scilex.gui.services import zotero_library
    from scilex.gui.services.extend import backup, read_results, write_results
    from scilex.gui.services.keys_editor import effective_keys

    if not assignments:
        return "Nothing to classify."
    data = read_results(review.results_path)
    if "zotero_collections" not in data.columns:
        data["zotero_collections"] = ""
    data["zotero_collections"] = data["zotero_collections"].astype(object)
    keys = data.get("zotero_key", pd.Series("", index=data.index))
    linked = {
        index: str(keys[index]).strip()
        for index in assignments
        if is_valid(keys[index]) and str(keys[index]).strip()
    }
    updated_in_zotero = failed = 0
    if linked:
        source = zotero_library.load_source(review.folder)
        api = zotero_library.client(effective_keys(review.folder), library=source)
        top_level = {
            c.path.casefold(): c.key for c in zotero_library.list_collections(api)
        }
        updates = {}
        for index, item_key in linked.items():
            role = assignments[index]
            collection = top_level.get(role.casefold())
            if collection is None:
                created = api.get_or_create_collection(role)
                if not created:
                    raise ConnectionError(f"Cannot create the Zotero collection '{role}'.")
                collection = created["key"] if "key" in created else created["data"]["key"]
                top_level[role.casefold()] = collection
            response = api._get(f"/items/{item_key}")
            if response is None:
                failed += 1
                continue
            item = response.json()
            current = list(item.get("data", {}).get("collections", []))
            if collection not in current:
                updates[item_key] = (item["version"], [*current, collection])
        if updates:
            outcome = api.update_item_collections(updates)
            updated_in_zotero, failed = outcome["success"], failed + outcome["failed"]
    for index, role in assignments.items():
        paths = _paths(data.at[index, "zotero_collections"])
        if role.casefold() not in {p.casefold() for p in paths}:
            data.at[index, "zotero_collections"] = ";".join([*paths, role])
    backup(review.results_path)
    write_results(data, review.results_path)
    text = f"{len(assignments)} papers classified"
    if linked:
        text += f" ({updated_in_zotero} added to their collection in Zotero"
        text += f", {failed} failed: edited meanwhile or unreachable)" if failed else ")"
    return text + "."


def plan(
    review: Review,
    main_config: dict,
    *,
    similarity: int = DEFAULT_SIMILARITY,
    filter_imported: bool = False,
    separate_subcorpora: bool = True,
) -> Plan:
    """What consolidation would do, without writing anything."""
    from scilex.gui.services import paper_log, screening
    from scilex.gui.services.extend import read_results

    data = read_results(review.results_path)
    if data is None or data.empty:
        return Plan(papers=0, groups=[], filtered=[])
    groups = find_duplicates(data, similarity, separate_subcorpora=separate_subcorpora)
    merged_away = {row for group in groups for row in group.others}
    log = paper_log.load(review.folder)
    decisions = screening.load_decisions(review)
    filtered, spared = [], 0
    for index, record in zip(data.index, data.to_dict("records"), strict=True):
        if index in merged_away:
            continue
        key = screening.paper_key(record)
        origin = (log.get(key) or {}).get("origin") or paper_log.origin_of(record)
        if origin in IMPORTED and not filter_imported:
            continue
        reasons = filter_reasons(record, main_config)
        if not reasons:
            continue
        decision = decisions.get(key)
        if decision and decision.decision == screening.INCLUDE:
            spared += 1
            continue
        filtered.append(
            FilteredPaper(index, key, str(record.get("title", "")), reasons)
        )
    required = list(main_config.get("required_subcorpora") or [])
    return Plan(
        len(data),
        groups,
        filtered,
        spared,
        required=required,
        # All papers: the user decides which duplicates are merged.
        unclassified=unclassified_papers(data, required),
    )


def apply(
    review: Review,
    the_plan: Plan,
    *,
    merge: list[int] | None = None,
    apply_filters: bool = True,
    action: str = EXCLUDE_IN_SCREEN,
) -> str:
    """Merge the chosen duplicate groups and apply the filters; return a summary.

    ``merge``: positions in ``the_plan.groups`` of the groups to merge (None:
    the safe ones). The results must not have changed since the plan (same
    rows): plan again otherwise.
    """
    from scilex.gui.services import paper_log, screening
    from scilex.gui.services.extend import backup, read_results, write_results

    if action not in (EXCLUDE_IN_SCREEN, REMOVE):
        raise ValueError(f"Unknown action {action!r}")
    data = read_results(review.results_path)
    if data is None or len(data) != the_plan.papers:
        raise ValueError("The results changed since the preview: preview again.")
    backup(review.results_path)
    for column in SET_COLUMNS:
        if column in data.columns:
            data[column] = data[column].astype(object)

    if merge is None:
        merge = [i for i, group in enumerate(the_plan.groups) if group.safe]
    chosen = [the_plan.groups[i] for i in merge]
    decisions = screening.load_decisions(review)
    log = paper_log.load(review.folder)
    moved = conflicts = 0
    removed: set[int] = set()
    for group in chosen:
        old_keys = {
            row: screening.paper_key(data.loc[row].to_dict()) for row in group.others
        }
        merge_group(data, group)
        keep_key = screening.paper_key(data.loc[group.keep].to_dict())
        kept = decisions.get(keep_key)
        for row, key in old_keys.items():
            removed.add(row)
            decision = decisions.get(key)
            if key == keep_key or decision is None:
                continue
            if kept is None:
                screening.set_decision(
                    review, keep_key, decision.decision, decision.note
                )
                kept = decision
                moved += 1
            elif kept.decision != decision.decision:
                note = (
                    f"{kept.note} {NOTE_PREFIX} a duplicate was "
                    f"{PAST[decision.decision]}.".strip()
                )
                screening.set_decision(review, keep_key, kept.decision, note)
                conflicts += 1
            screening.set_decision(review, key, None)
        dates = [
            (log.get(key) or {}).get("imported_at")
            for key in [keep_key, *old_keys.values()]
        ]
        dates = [d for d in dates if d]
        if dates and keep_key in log:
            log[keep_key]["imported_at"] = min(dates)

    excluded = 0
    filtered = the_plan.filtered if apply_filters else []
    for paper in filtered:
        note = f"{NOTE_PREFIX} {'; '.join(paper.reasons)}"
        if action == REMOVE:
            removed.add(paper.index)
            screening.set_decision(review, paper.paper_key, None)
        else:
            screening.set_decision(review, paper.paper_key, screening.EXCLUDE, note)
            excluded += 1
    data = data.drop(index=sorted(removed))
    write_results(data, review.results_path)
    if log:
        paper_log._save(review.folder, log)

    merged_rows = sum(len(group.others) for group in chosen)
    parts = [f"{merged_rows} duplicates merged into {len(chosen)} papers"]
    if moved or conflicts:
        parts.append(
            f"{moved} decisions moved to the kept paper, {conflicts} disagreements noted"
        )
    if not apply_filters:
        parts.append("filters not applied")
    elif action == REMOVE:
        parts.append(f"{len(filtered)} filtered papers removed")
    else:
        parts.append(f"{excluded} filtered papers excluded in ③ Screen")
    return "; ".join(parts) + f". {len(data)} papers left."
