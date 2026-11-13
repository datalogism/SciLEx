"""Default type of each paper: Benchmark, Review or State of the art, Dataset, Model or Method.

Every paper of a review gets at least one ``PAPER_TYPE:<type>`` tag (a
DIMENSION:value tag, shared through Zotero like the others); a paper can have
several types, e.g. a Model or Method paper that also releases a Dataset. The default comes from cue words
of the title (decisive) and the abstract, and from the publication type; a
person can change it in Zotero or SciLEx, and a type already set is never
overwritten. A paper with no cue is a Model or Method paper, the common case.
"""

from __future__ import annotations

import re
from collections import Counter

from scilex import review_tags
from scilex.constants import is_valid

TAG = "PAPER_TYPE"
PREFIX = f"{TAG}:"
BENCHMARK = "Benchmark"
REVIEW = "Review or State of the art"
DATASET = "Dataset"
MODEL = "Model or Method"
TYPES = (BENCHMARK, REVIEW, DATASET, MODEL)
# Who set the PAPER_TYPE tags of a paper (SX-17, ORSD SR16): ``person:<ORCID iD
# IRI>`` (③ Screen, Explore), ``collection-role`` (a screened collection's type),
# ``default-guess`` (⑥ Enrich > Paper types). No value: ``unknown``.
ORIGIN_COLUMN = "paper_type_origin"
DEFAULT_GUESS = "default-guess"
COLLECTION_ROLE = "collection-role"
UNKNOWN_ORIGIN = "unknown"


def person_origin(agent_id: str) -> str:
    """Origin of types set by a person (``person:`` + ORCID iD IRI, or unknown)."""
    return f"person:{agent_id}" if agent_id else "person:unknown"


def changes_types(add, remove) -> bool:
    """True when a tag change adds or removes a ``PAPER_TYPE:`` tag."""
    return any(str(tag).upper().startswith(PREFIX) for tag in (*add, *remove))


def set_origin(data, index, origin: str) -> None:
    """Record who set the types of row ``index`` of ``data``."""
    if ORIGIN_COLUMN not in data.columns:
        data[ORIGIN_COLUMN] = ""
    data[ORIGIN_COLUMN] = data[ORIGIN_COLUMN].astype(object)
    data.at[index, ORIGIN_COLUMN] = origin


_CUES = {
    REVIEW: re.compile(
        r"\b(survey|review|overview|state[- ]of[- ]the[- ]art|literature|"
        r"systematic mapping|tutorial|perspectives?|challenges and opportunities|"
        r"roadmap|taxonomy)\b",
        re.IGNORECASE,
    ),
    BENCHMARK: re.compile(
        r"\b(benchmark(s|ing)?|leaderboard|shared task|evaluation (suite|framework)|"
        r"comparative (study|evaluation)|empirical (study|comparison)|"
        r"how (good|well)|competition)\b",
        re.IGNORECASE,
    ),
    DATASET: re.compile(
        r"\b(dataset|data set|corpus|corpora|treebank|knowledge base|"
        r"collection of|annotated (data|resource)|resource for|test collection)\b",
        re.IGNORECASE,
    ),
}
# When the title holds several cues, the most specific type wins.
PRIORITY = (REVIEW, BENCHMARK, DATASET)


def _text(value) -> str:
    return str(value) if is_valid(value) else ""


def classify(title: str, abstract: str = "", item_type: str = "") -> str:
    """The default type of one paper (see the module docstring)."""
    title, abstract = _text(title), _text(abstract)
    found = [t for t in PRIORITY if _CUES[t].search(title)]
    if found:
        return found[0]
    if "review" in _text(item_type).lower():
        return REVIEW
    # The abstract decides only with repeated cues: most abstracts mention
    # a dataset or a benchmark they use.
    hits = Counter({t: len(_CUES[t].findall(abstract)) for t in PRIORITY})
    best, count = max(hits.items(), key=lambda kv: (kv[1], -PRIORITY.index(kv[0])))
    if count >= 3:
        return best
    return MODEL


def types_of(row) -> list[str]:
    """The ``PAPER_TYPE`` tags of a results row, in tag order (may be empty)."""
    found: list[str] = []
    for tag in review_tags.split_tags(row.get("tags")):
        if tag.upper().startswith(PREFIX):
            value = tag[len(PREFIX) :].strip()
            if value and value not in found:
                found.append(value)
    return found


def type_of(row) -> str | None:
    """The first ``PAPER_TYPE`` tag of a results row, if it has one."""
    found = types_of(row)
    return found[0] if found else None


def effective_types(row) -> list[str]:
    """The paper's types: its tags, else ``[default]``."""
    return types_of(row) or [
        classify(row.get("title"), row.get("abstract"), row.get("itemType"))
    ]


def effective_type(row) -> str:
    """The paper's main type (first tag, else the default); one value, for a
    colour or a single group. Use :func:`effective_types` to count or filter."""
    return effective_types(row)[0]


def tag_changes(row, types: list[str]) -> tuple[list[str], list[str]]:
    """``(add, remove)`` tags making ``types`` the paper's types (``[]``: none)."""
    current = [
        tag
        for tag in review_tags.split_tags(row.get("tags"))
        if tag.upper().startswith(PREFIX)
    ]
    wanted = [PREFIX + kind for kind in types]
    return (
        [tag for tag in wanted if tag not in current],
        [tag for tag in current if tag not in wanted],
    )


def annotate(data) -> int:
    """Tag the papers without a type with their default type; return how many."""
    if "tags" not in data.columns:
        data["tags"] = ""
    data["tags"] = data["tags"].astype(object)
    tagged = 0
    for index, row in zip(data.index, data.to_dict("records"), strict=True):
        if type_of(row):
            continue
        tags = review_tags.split_tags(row.get("tags"))
        data.at[index, "tags"] = ";".join([*tags, PREFIX + effective_type(row)])
        set_origin(data, index, DEFAULT_GUESS)
        tagged += 1
    return tagged
