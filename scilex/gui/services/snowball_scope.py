"""Snowballing settings of a review: which corpus papers seed it, and how.

Snowballing looks for papers outside the corpus that cite, or are cited by,
corpus papers. The **seeds** can be narrowed to:

- some Zotero collections (a collection includes its sub-collections);
- some paper types (Benchmark, Review, Dataset, Model; see
  :mod:`scilex.paper_types`);
- the papers that meet the review's eligibility criteria (see
  :mod:`scilex.gui.services.criteria`; exceptions count as met).

Candidates are still compared with the whole corpus: a paper already in the
review is never added again. The settings (direction, limits, seeds) are
stored in ``snowball.yml`` in the review folder and reused the next time.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from scilex import review_tags

FILENAME = "snowball.yml"
# Stored settings: the option keys of the Snowball analysis.
KEYS = (
    "direction",
    "top_k",
    "min_frequency",
    "add_to_collection",
    "collections",
    "paper_types",
    "eligible_only",
)


def path_of(folder: Path) -> Path:
    return Path(folder) / FILENAME


def load(folder: Path) -> dict:
    """The stored settings (empty when none, or unreadable)."""
    path = path_of(folder)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, yaml.YAMLError):
        return {}
    return {k: v for k, v in (raw or {}).items() if k in KEYS}


def save(folder: Path, settings: dict) -> Path:
    """Write the settings (only the known keys; a dry run is not stored)."""
    kept = {k: settings[k] for k in KEYS if k in settings}
    for key in ("collections", "paper_types"):
        if key in kept:
            kept[key] = [str(v) for v in kept[key] or []]
    path = path_of(folder)
    path.write_text(
        yaml.safe_dump(kept, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return path


def collection_options(data: pd.DataFrame | None) -> list[str]:
    """Zotero collections of the corpus, with their parent collections."""
    if data is None or "zotero_collections" not in data.columns:
        return []
    found: set[str] = set()
    for value in data["zotero_collections"]:
        for path in review_tags.split_tags(value):
            parts = [p.strip() for p in path.split("/") if p.strip()]
            for depth in range(1, len(parts) + 1):
                found.add(" / ".join(parts[:depth]))
    return sorted(found, key=str.casefold)


def _norm(path: str) -> str:
    return "/".join(p.strip().casefold() for p in str(path).split("/") if p.strip())


def _in_collections(value, chosen: set[str]) -> bool:
    for path in review_tags.split_tags(value):
        normalized = _norm(path)
        if any(normalized == c or normalized.startswith(c + "/") for c in chosen):
            return True
    return False


def seeds(
    data: pd.DataFrame,
    collections: list[str] | None = None,
    paper_types: list[str] | None = None,
    eligible_only: bool = False,
    review=None,
) -> pd.DataFrame:
    """The corpus papers snowballing starts from.

    ``eligible_only`` needs ``review`` (its criteria and screening decisions).
    """
    selected = data
    chosen = {_norm(c) for c in collections or [] if str(c).strip()}
    if chosen:
        column = selected.get("zotero_collections", pd.Series("", index=selected.index))
        selected = selected[column.map(lambda v: _in_collections(v, chosen))]
    if paper_types:
        from scilex.paper_types import effective_types

        wanted = set(paper_types)
        selected = selected[
            selected.apply(lambda row: bool(wanted & set(effective_types(row))), axis=1)
        ]
    if eligible_only and review is not None and not selected.empty:
        from scilex.gui.services import criteria, screening
        from scilex.gui.services.workspace import Workspace

        try:
            main = Workspace.load_config(review).main
        except Exception:
            main = {}
        items = criteria.load(review.folder, main)
        included = {
            key
            for key, d in screening.load_decisions(review).items()
            if d.decision == screening.INCLUDE
        }
        # Judged on the whole corpus (duplicates, top % rules), then narrowed.
        verdicts = criteria.eligibility(items, data, included)
        keys = selected.apply(screening.paper_key, axis=1)
        failing = {
            key
            for key, states in verdicts.items()
            if any(state == criteria.EXCLUDED for state, _ in states.values())
        }
        selected = selected[~keys.isin(failing)]
    return selected


def describe(
    collections: list[str] | None, paper_types: list[str] | None, eligible_only: bool
) -> str:
    """The seed scope in words ("" for the whole corpus)."""
    parts = []
    if collections:
        parts.append("collections " + ", ".join(collections))
    if paper_types:
        parts.append("types " + ", ".join(paper_types))
    if eligible_only:
        parts.append("eligible papers")
    return "; ".join(parts)
