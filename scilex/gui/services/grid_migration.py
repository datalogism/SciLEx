"""Move a review's annotations to a new version of its annotation grid.

A new grid version renames dimensions, renames or merges values, splits a
value into several tags, or drops a dimension. The translation is a mapping
table (CSV, ``grid_mapping.csv`` next to ``scilex.yml`` by default), one row
per rule:

==============  ==========  ==============  ==========
old_dimension   old_value   new_dimension   new_value
==============  ==========  ==============  ==========
BENCHMARKTYPE   *           SURVEY_TYPE                 (rename the dimension)
TASK            RelationClassif  TASK       RC          (rename a value)
NBMODEL         *           -                           (drop the dimension)
INPUT           NER         INPUT           Text        (one tag ...
INPUT           NER         USE_NER         1           ... gives two)
==============  ==========  ==============  ==========

- ``old_value`` ``*`` (or empty) matches every value of the dimension; a rule
  naming the value wins over ``*``. A value matches exactly (ignoring case)
  first, else without spaces or punctuation (``Relation classif`` matches
  ``RelationClassif``) when that loose form names a single rule.
- ``new_value`` empty keeps the old value; ``new_dimension`` ``-`` drops the tag.
- Several rows for one tag give several tags.
- An optional ``note`` column (e.g. ``re-check``) is shown with the rule's
  tags in the plan; a rule writing the tag unchanged marks it as covered
  (left for a person) instead of unmapped.

Only existing ``DIMENSION:value`` tags are translated: nothing is added for a
dimension a paper has no tag for, and ``DIMENSION:?`` placeholders only follow
a dimension rename (they never get a value). Tags no rule covers stay as they
are and are listed in the plan, so the mapping can be completed before
applying. Tags written by SciLEx (workflow, keywords, metrics) are never
touched.

:func:`apply` writes Zotero first (each item at the version it was read: an
item edited meanwhile is skipped), then the same translation to the local
results, replaces the grid file (the old one is kept as a backup) and records
the change as an automatic update in the workflow journal and the annotation
history.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from scilex import review_tags
from scilex.tag_analysis import parse_annotation, value_key
from scilex.tagging.grid import GRID_FILENAME, PLACEHOLDER

MAPPING_FILENAME = "grid_mapping.csv"
MAPPING_COLUMNS = ("old_dimension", "old_value", "new_dimension", "new_value")
NOTE_COLUMN = "note"
ANY, DROP = "*", "-"
ACTIVITY = "grid-migration"
HISTORY_ORIGIN = "grid-migration"


class MappingError(ValueError):
    """The mapping table cannot be read (user-facing message)."""


@dataclass(frozen=True)
class Target:
    """One tag a rule writes: ``dimension`` (``-`` drops) and ``value`` (``""`` keeps)."""

    dimension: str
    value: str = ""
    note: str = ""


@dataclass
class Mapping:
    """Translation rules: per dimension, per exact value (``*`` = any value)."""

    rules: dict[str, dict[str, list[Target]]] = field(default_factory=dict)

    def targets(self, dimension: str, value: str) -> list[Target] | None:
        """Targets of ``DIMENSION:value``; None when no rule covers it."""
        by_value = self.rules.get(dimension.upper())
        if by_value is None:
            return None
        exact = by_value.get(value.strip().casefold())
        if exact is not None:
            return exact
        key = value_key(value)
        loose = [v for v in by_value if v != ANY and value_key(v) == key]
        if key and len(loose) == 1:
            return by_value[loose[0]]
        return by_value.get(ANY)

    def __len__(self) -> int:
        return sum(len(v) for v in self.rules.values())


def mapping_path(folder: Path) -> Path:
    return Path(folder) / MAPPING_FILENAME


def parse_mapping(rows: list[dict]) -> Mapping:
    """Build the rules from table rows (see the module docstring).

    Raises:
        MappingError: A row lacks its old or new dimension.
    """
    mapping = Mapping()
    for number, row in enumerate(rows, start=2):
        old_dim = str(row.get("old_dimension") or "").strip().upper()
        old_value = str(row.get("old_value") or "").strip()
        new_dim = str(row.get("new_dimension") or "").strip()
        new_value = str(row.get("new_value") or "").strip()
        note = str(row.get(NOTE_COLUMN) or "").strip()
        if not old_dim and not new_dim:
            continue  # blank line
        if not old_dim or not new_dim:
            raise MappingError(
                f"Line {number}: old_dimension and new_dimension are both "
                f"required (use '{DROP}' as new_dimension to drop a tag)."
            )
        key = ANY if old_value in ("", ANY) else old_value.casefold()
        target = Target(DROP if new_dim == DROP else new_dim.upper(), new_value, note)
        targets = mapping.rules.setdefault(old_dim, {}).setdefault(key, [])
        if target not in targets:
            targets.append(target)
    return mapping


def load_mapping(path: Path) -> Mapping:
    """Read a mapping CSV (``,`` or ``;`` separated, UTF-8 with or without BOM).

    Raises:
        MappingError: Missing file or columns, or an incomplete row.
    """
    path = Path(path)
    if not path.is_file():
        raise MappingError(f"No mapping table at {path}.")
    text = path.read_text(encoding="utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except (csv.Error, IndexError):
        dialect = csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    fields = {(f or "").strip().lower() for f in reader.fieldnames or []}
    missing = [c for c in MAPPING_COLUMNS if c not in fields]
    if missing:
        raise MappingError(
            f"The mapping table lacks the column(s) {', '.join(missing)}; "
            f"expected: {', '.join(MAPPING_COLUMNS)}."
        )
    rows = [{(k or "").strip().lower(): v for k, v in row.items()} for row in reader]
    return parse_mapping(rows)


@dataclass
class Translation:
    """Result of translating one paper's tags."""

    tags: list[str]
    changed: bool
    renames: list[tuple[str, str, str]]  # (old tag, new tag or "" if dropped, note)
    unmapped: list[tuple[str, str]]  # (DIMENSION, value) no rule covers
    kept: list[tuple[str, str]] = field(default_factory=list)  # (tag, note)


def translate_tags(tags: list[str], mapping: Mapping) -> Translation:
    """Translate the annotation tags of one paper; other tags are kept as they are.

    The translated tags take the place of the old one (order kept); a paper
    never gets the same tag twice.
    """
    out: list[str] = []
    seen: set[str] = set()
    renames: list[tuple[str, str, str]] = []
    unmapped: list[tuple[str, str]] = []
    kept: list[tuple[str, str]] = []
    changed = False

    def add(tag: str) -> None:
        nonlocal changed
        if tag.casefold() in seen:
            changed = True  # a duplicate collapses
            return
        seen.add(tag.casefold())
        out.append(tag)

    for tag in tags:
        parsed = None if review_tags.is_workflow_tag(tag) else parse_annotation(tag)
        if parsed is None:
            add(tag)
            continue
        dimension, value = parsed
        if not value:
            add(tag)  # "DIM:" carries nothing to translate
            continue
        targets = mapping.targets(dimension, value)
        if targets is None:
            unmapped.append((dimension, value))
            add(tag)
            continue
        placeholder = value == PLACEHOLDER
        new_tags: list[str] = []
        notes: list[str] = []
        for target in targets:
            if target.dimension == DROP:
                continue
            # A placeholder follows a dimension rename only: it never gets a value.
            new_value = value if placeholder or not target.value else target.value
            new_tag = f"{target.dimension}:{new_value}"
            # Two rules writing the same tag (e.g. with different notes) give one.
            if new_tag.casefold() not in {t.casefold() for t in new_tags}:
                new_tags.append(new_tag)
                notes.append(target.note)
        note = "; ".join(dict.fromkeys(t.note for t in targets if t.note))
        if new_tags == [tag]:
            kept.append((tag, note))
        else:
            changed = True
            renames.extend(
                [(tag, new, n) for new, n in zip(new_tags, notes, strict=True)]
                or [(tag, "", note)]
            )
        for new in new_tags:
            add(new)
    return Translation(out, changed, renames, unmapped, kept)


@dataclass
class Plan:
    """What applying a mapping changes."""

    papers: int = 0  # papers read
    annotated: int = 0  # papers with at least one annotation tag
    updates: dict[str, tuple[int, list[str]]] = field(default_factory=dict)
    renames: Counter = field(default_factory=Counter)  # (old, new, note) -> papers
    unmapped: Counter = field(default_factory=Counter)  # (DIM, value) -> papers
    kept: Counter = field(default_factory=Counter)  # (tag, note) -> papers

    @property
    def changed(self) -> int:
        return len(self.updates)

    def unmapped_dimensions(self) -> Counter:
        """Papers per dimension having a value no rule covers."""
        counts: Counter = Counter()
        for (dimension, _), n in self.unmapped.items():
            counts[dimension] += n
        return counts


def _item_tags(item: dict) -> list[str]:
    return [str(t.get("tag", "")) for t in item.get("data", {}).get("tags", [])]


def _is_paper(item: dict) -> bool:
    data = item.get("data", {})
    return data.get("itemType") not in ("attachment", "note") and "title" in data


def plan(items: list[dict], mapping: Mapping) -> Plan:
    """Plan the tag changes of Zotero ``items`` (attachments and notes skipped)."""
    result = Plan()
    for item in items:
        if not _is_paper(item):
            continue
        result.papers += 1
        tags = _item_tags(item)
        if any(
            parse_annotation(t) and not review_tags.is_workflow_tag(t) for t in tags
        ):
            result.annotated += 1
        translation = translate_tags(tags, mapping)
        for pair in set(translation.renames):
            result.renames[pair] += 1
        for pair in set(translation.unmapped):
            result.unmapped[pair] += 1
        for pair in set(translation.kept):
            result.kept[pair] += 1
        if translation.changed:
            version = item.get("version", item.get("data", {}).get("version", 0))
            result.updates[item["key"]] = (version, translation.tags)
    return result


def translate_results(data: pd.DataFrame, mapping: Mapping) -> int:
    """Translate the ``tags`` column of local results in place; rows changed."""
    if "tags" not in data.columns:
        return 0
    data["tags"] = data["tags"].astype(object)
    changed = 0
    for index, cell in zip(data.index, data["tags"].tolist(), strict=True):
        translation = translate_tags(review_tags.split_tags(cell), mapping)
        if translation.changed:
            data.at[index, "tags"] = ";".join(translation.tags)
            changed += 1
    return changed


def plan_table(result: Plan) -> pd.DataFrame:
    """One row per translated, kept (with a note) or uncovered tag."""
    rows = (
        [
            {"old_tag": old, "new_tag": new or "(dropped)", "papers": n, "note": note}
            for (old, new, note), n in result.renames.items()
        ]
        + [
            {"old_tag": tag, "new_tag": "(kept)", "papers": n, "note": note}
            for (tag, note), n in result.kept.items()
            if note
        ]
        + [
            {
                "old_tag": f"{dim}:{value}",
                "new_tag": "(no rule: kept)",
                "papers": n,
                "note": "",
            }
            for (dim, value), n in result.unmapped.items()
        ]
    )
    frame = pd.DataFrame(rows, columns=["old_tag", "new_tag", "papers", "note"])
    return frame.sort_values(["papers", "old_tag"], ascending=[False, True])


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def install_grid(folder: Path, new_grid: Path, label: str) -> Path | None:
    """Make ``new_grid`` the review's grid; return the backup of the old one."""
    from scilex.tagging.grid import load_grid, save_grid

    target = Path(folder) / GRID_FILENAME
    grid = load_grid(new_grid)  # raises on an unreadable grid, before any change
    backup = None
    if target.is_file():
        backup = target.with_name(f"{GRID_FILENAME}.before-{label}")
        if backup.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = target.with_name(f"{GRID_FILENAME}.before-{label}-{stamp}")
        shutil.copy2(target, backup)
    save_grid(grid, target)
    return backup


def apply(
    review,
    mapping_file: Path,
    *,
    new_grid: Path | None = None,
    label: str = "new-grid",
    items: list[dict] | None = None,
    api=None,
) -> dict:
    """Translate the review's tags in Zotero and locally; install ``new_grid``.

    ``items``/``api`` default to the review's Zotero group read now (tests pass
    their own). Returns the counts recorded in the journal.
    """
    from scilex.gui.services import journal, overview, results_store, zotero_library
    from scilex.gui.services.extend import read_results
    from scilex.gui.services.keys_editor import effective_keys

    folder = Path(review.folder)
    mapping = load_mapping(mapping_file)
    if api is None or items is None:
        source = zotero_library.load_source(folder)
        if source is None:
            raise ValueError("The review has no Zotero library yet.")
        api = api or zotero_library.client(effective_keys(folder), library=source)
        items = zotero_library.fetch_papers(api, None) if items is None else items
    result = plan(items, mapping)
    written = (
        api.update_item_tags(result.updates)
        if result.updates
        else {"success": 0, "failed": 0}
    )

    local_rows = 0
    if review.results_path and Path(review.results_path).is_file():
        with results_store.lock_for(review.results_path):
            data = read_results(review.results_path)
            if data is not None:
                before = data.copy()
                local_rows = translate_results(data, mapping)
                if local_rows:
                    results_store.write_changes(review.results_path, before, data)

    backup = install_grid(folder, new_grid, label) if new_grid else None

    # Annotation state after the change, as Zotero now holds it.
    after = [
        result.updates[item["key"]][1]
        if item.get("key") in result.updates
        else _item_tags(item)
        for item in items
        if _is_paper(item)
    ]
    overview.record_snapshot(folder, after, HISTORY_ORIGIN)
    counts = {
        "papers": result.papers,
        "annotated": result.annotated,
        "changed": result.changed,
        "zotero_written": written["success"],
        "zotero_skipped": written["failed"],
        "local_rows": local_rows,
        "unmapped_values": len(result.unmapped),
    }
    journal.append(
        folder,
        ACTIVITY,
        used={
            "mapping": {
                "file": Path(mapping_file).name,
                "sha256": _fingerprint(mapping_file),
            },
            **(
                {
                    "grid": {
                        "file": Path(new_grid).name,
                        "sha256": _fingerprint(new_grid),
                    }
                }
                if new_grid
                else {}
            ),
            "library": journal.library_of(zotero_library.load_source(folder)),
        },
        generated={**counts, **({"grid_backup": backup.name} if backup else {})},
        params={
            "category": "annotation",
            "automatic": True,
            "grid": label,
            "rules": len(mapping),
        },
        annotation=journal.annotation_state(after),
        message=(
            f"Automatic update to the {label} grid: tags of {result.changed} "
            f"papers translated ({written['success']} written to Zotero"
            + (
                f", {written['failed']} skipped: edited meanwhile"
                if written["failed"]
                else ""
            )
            + f"); {len(result.unmapped)} values had no rule and were kept."
        ),
    )
    return counts
