"""Short titles of the papers, deduced from their title when it names an acronym.

Many papers are known by a short name given in their title:

* a prefix before a colon or a dash: ``BERT: Pre-training of Deep Bidirectional
  Transformers…`` → ``BERT``; ``GPT-4 – Technical report`` → ``GPT-4``;
* an acronym in parentheses spelled by the words before it: ``Holistic
  Evaluation of Language Models (HELM)`` → ``HELM``.

Only acronym-like names are taken (``BERT``, ``SQuAD``, ``T5``, ``word2vec``,
``RoBERTa``), never plain words (``Transformers: …``) or phrases (``Lost in the
Middle: …``). A prefix starting the titles of several papers of the corpus
(``COVID-19: …``) is a topic, not a name, and is left out.

The short title goes to the ``shortTitle`` column (Zotero's *Short Title*,
``fabio:hasShortTitle`` in the knowledge graph). A paper that already has one is
never changed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from scilex.constants import is_valid

COLUMN = "shortTitle"
MAX_LENGTH = 30

# A name token: letters/digits, optionally joined by - . + & '
_TOKEN = r"[A-Za-z0-9][A-Za-z0-9\-.+&']*"
# "NAME: rest", "NAME - rest", "NAME – rest", "NAME — rest"
_PREFIX = re.compile(
    rf"^\s*(?P<name>{_TOKEN}(?:\s+{_TOKEN}){{0,2}})\s*(?::|\s[-–—]\s)\s*\S"
)
_PARENTHESIS = re.compile(rf"\((?P<name>{_TOKEN})\)")
_WORD = re.compile(r"[A-Za-z][A-Za-z']*")


def acronym_like(token: str) -> bool:
    """True for a name such as ``BERT``, ``SQuAD``, ``T5``, ``word2vec``, ``RoBERTa``.

    Plain words (``Transformers``, ``deep``), numbers (``2``) and single
    letters are not.
    """
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return False
    has_digit = any(c.isdigit() for c in token)
    upper_inside = any(c.isupper() for c in token[1:] if c.isalpha())
    if has_digit:
        return True  # T5, GPT-4, word2vec, Wikidata5M
    return upper_inside and len(letters) >= 2  # BERT, SQuAD, fastText, RoBERTa


def _version_like(token: str) -> bool:
    """A number or a size following a name: ``2``, ``3.5``, ``7B``, ``v2``."""
    return bool(re.fullmatch(r"(?:v?\d+(?:\.\d+)*[A-Za-z]?|[A-Z]{1,2}\d*)", token))


def _prefix_name(title: str) -> str | None:
    match = _PREFIX.match(title)
    if not match:
        return None
    tokens = match.group("name").split()
    if not acronym_like(tokens[0]):
        return None
    if not all(acronym_like(t) or _version_like(t) for t in tokens[1:]):
        return None
    return " ".join(tokens)


def _spelled_by(acronym: str, words: list[str]) -> bool:
    """True when the capitals of ``acronym`` follow the initials of ``words``."""
    capitals = [c.lower() for c in acronym if c.isupper()]
    if len(capitals) < 2:
        return False
    initials = iter(w[0].lower() for w in words)
    return all(any(c == i for i in initials) for c in capitals)


def _parenthesis_name(title: str) -> str | None:
    for match in _PARENTHESIS.finditer(title):
        name = match.group("name")
        if not acronym_like(name):
            continue
        before = _WORD.findall(title[: match.start()])
        if _spelled_by(name, before[-12:]):
            return name
    return None


def candidate(title) -> str | None:
    """The short title the title gives, if it names an acronym; else None."""
    if not is_valid(title):
        return None
    title = " ".join(str(title).split())
    name = _prefix_name(title) or _parenthesis_name(title)
    if not name or len(name) > MAX_LENGTH:
        return None
    return name.rstrip(".-")


@dataclass
class ShortTitleReport:
    """What :func:`annotate` did."""

    considered: int = 0
    already: int = 0
    filled: int = 0
    shared: int = 0  # names starting several titles: topics, left out

    def message(self) -> str:
        parts = [f"{self.filled} short titles deduced from the titles"]
        parts.append(f"{self.already} papers already had one (kept)")
        if self.shared:
            parts.append(
                f"{self.shared} left out: their prefix starts several titles (a topic)"
            )
        none = self.considered - self.already - self.filled - self.shared
        parts.append(f"{none} titles name no acronym")
        return "; ".join(parts) + "."


def annotate(
    data: pd.DataFrame,
    *,
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> ShortTitleReport:
    """Fill the empty ``shortTitle`` cells of ``data`` (in place) from the titles.

    ``row_filter`` limits the papers changed; the whole table is used to spot
    prefixes shared by several titles.
    """
    report = ShortTitleReport()
    if data.empty or "title" not in data.columns:
        return report
    if COLUMN not in data.columns:
        data[COLUMN] = pd.Series([None] * len(data), index=data.index, dtype=object)
    elif data[COLUMN].dtype != object:
        data[COLUMN] = data[COLUMN].astype(object)
    names = {index: candidate(title) for index, title in data["title"].items()}
    # Distinct titles per name: copies of one paper do not make a topic.
    titles_of: dict[str, set[str]] = {}
    for index, name in names.items():
        if name:
            title = " ".join(str(data.at[index, "title"]).casefold().split())
            titles_of.setdefault(name.casefold(), set()).add(title)
    titles_per_name = Counter({name: len(t) for name, t in titles_of.items()})
    scope = row_filter(data) if row_filter is not None else data
    for index in scope.index:
        report.considered += 1
        if is_valid(data.at[index, COLUMN]) and str(data.at[index, COLUMN]).strip():
            report.already += 1
            continue
        name = names.get(index)
        if not name:
            continue
        if titles_per_name[name.casefold()] > 1:
            report.shared += 1
            continue
        data.at[index, COLUMN] = name
        report.filled += 1
    return report
