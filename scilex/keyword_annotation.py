"""Annotate papers with the review's search keywords found in their text.

Collected papers carry the keywords of the queries that found them
(``collect_keywords``: ``Collect_KW1:term;Collect_KW2:term``). Papers imported
from Zotero, a knowledge graph or BibTeX, or added by snowballing, have none.
This module fills those columns from the paper's own title and abstract, with
the keyword groups of ``scilex.yml``:

- ``collect_keywords``: each keyword of group *n* found verbatim (case-insensitive)
  gives ``Collect_KW<n>:keyword``, as the aggregation would write it;
- ``bonus_keyword_tags``: each bonus keyword found (all its meaningful words
  present) gives ``BK:keyword``, as the ranking step writes it.

Existing tags are kept: matches are added to them, never removed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import pandas as pd

from scilex.constants import is_valid
from scilex.keyword_validation import (
    build_searchable_text,
    exact_match_prepared,
    flexible_match_prepared,
    prepare_text,
)

COLLECT_COLUMN = "collect_keywords"
BONUS_COLUMN = "bonus_keyword_tags"


@dataclass
class KeywordReport:
    """Outcome of :func:`annotate_keywords`."""

    papers: int = 0  # papers looked at
    matched: int = 0  # papers with at least one keyword in their text
    updated: int = 0  # papers that got at least one new tag
    tags_added: int = 0
    per_keyword: dict[str, int] = field(default_factory=dict)

    def message(self) -> str:
        """One-line summary for the user."""
        if not self.papers:
            return "No paper to annotate."
        text = (
            f"{self.matched} of {self.papers} papers contain a search keyword; "
            f"{self.tags_added} keyword tags added to {self.updated} papers."
        )
        missing = [kw for kw, count in self.per_keyword.items() if count == 0]
        if missing:
            text += f" Never found: {', '.join(missing)}."
        return text


def keyword_groups(main_config: dict) -> list[list[str]]:
    """The keyword groups of a review configuration (``[["a", "b"], ["c"]]``).

    A flat list of terms is one group.
    """
    raw = main_config.get("keywords") or []
    if raw and all(isinstance(term, str) for term in raw):
        raw = [raw]
    groups = []
    for group in raw:
        terms = [group] if isinstance(group, str) else list(group or [])
        terms = [str(term).strip() for term in terms if str(term).strip()]
        if terms:
            groups.append(terms)
    return groups


def _split(value, separator: str) -> list[str]:
    if not is_valid(value):
        return []
    return [part.strip() for part in str(value).split(separator) if part.strip()]


def _merge(existing: list[str], new: Iterable[str]) -> tuple[list[str], int]:
    """``existing`` + the new tags it lacks (case-insensitive), and their count."""
    known = {tag.lower() for tag in existing}
    merged = list(existing)
    added = 0
    for tag in new:
        if tag.lower() not in known:
            merged.append(tag)
            known.add(tag.lower())
            added += 1
    return merged, added


def annotate_keywords(
    data: pd.DataFrame,
    groups: list[list[str]],
    bonus_keywords: Iterable[str] = (),
    *,
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> KeywordReport:
    """Add to ``data`` (in place) the keyword tags found in each paper's text.

    Args:
        data: Aggregated results (``title`` and ``abstract`` columns).
        groups: Keyword groups, see :func:`keyword_groups`.
        bonus_keywords: Bonus keywords of the configuration.
        row_filter: Limits the papers annotated (e.g. those kept in screening).
    """
    bonus = [str(kw).strip() for kw in bonus_keywords if str(kw).strip()]
    report = KeywordReport(
        per_keyword={kw: 0 for group in groups for kw in group}
        | {kw: 0 for kw in bonus}
    )
    if data.empty or not (groups or bonus):
        return report
    rows = data if row_filter is None else row_filter(data)
    for column in (COLLECT_COLUMN, BONUS_COLUMN):
        if column not in data.columns:
            data[column] = ""
        data[column] = data[column].astype(object)

    for index, row in rows.iterrows():
        report.papers += 1
        text = prepare_text(
            build_searchable_text(row.get("title"), row.get("abstract"))
        )
        found = [
            (number, kw)
            for number, group in enumerate(groups, start=1)
            for kw in group
            if exact_match_prepared(kw, text)
        ]
        found_bonus = [kw for kw in bonus if flexible_match_prepared(kw, text)]
        for _, kw in found:
            report.per_keyword[kw] += 1
        for kw in found_bonus:
            report.per_keyword[kw] += 1
        if not (found or found_bonus):
            continue
        report.matched += 1

        collect, added = _merge(
            _split(data.at[index, COLLECT_COLUMN], ";"),
            (f"Collect_KW{number}:{kw}" for number, kw in found),
        )
        bonus_tags, bonus_added = _merge(
            _split(data.at[index, BONUS_COLUMN], "|"),
            (f"BK:{kw}" for kw in found_bonus),
        )
        if added:
            data.at[index, COLLECT_COLUMN] = ";".join(collect)
        if bonus_added:
            data.at[index, BONUS_COLUMN] = "|".join(bonus_tags)
        if added or bonus_added:
            report.updated += 1
            report.tags_added += added + bonus_added
    return report
