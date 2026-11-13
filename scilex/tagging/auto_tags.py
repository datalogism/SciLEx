"""LLM proposals in Zotero: ``DIMENSION-AUTO:value`` tags.

Humans annotate a paper by replacing ``DIMENSION:?`` with ``DIMENSION:value``.
An LLM annotator (SciLEx Annotator, see
:mod:`scilex.gui.services.llm_annotator`) never writes codes: it proposes
``DIMENSION-AUTO:value``, which a person accepts, corrects or rejects. A human
code always wins:

- ``-AUTO`` tags are automation tags (:func:`scilex.tagging.grid.is_automation_tag`),
  so they never count as annotation codes (grid deduction, reports, Overview,
  knowledge graph, agreement);
- proposals are only written on dimensions a human has not coded yet.

:func:`dimension_states` gives, per dimension of a paper, the human codes,
the pending proposals and whether it is still to do.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

AUTO_SUFFIX = "-AUTO"
PLACEHOLDER = "?"
_AUTO = re.compile(r"^([^:\s]+)-AUTO:(.+)$", re.IGNORECASE)

HUMAN, PROPOSED, TODO = "human", "proposed", "todo"


def auto_tag(dimension: str, value: str) -> str:
    """``auto_tag("sat_task", "Ner")`` -> ``"SAT_TASK-AUTO:Ner"``."""
    dimension = dimension.strip().upper()
    value = str(value).strip()
    if not dimension or not value or ";" in value:
        raise ValueError(f"Invalid proposal {dimension!r}:{value!r}")
    return f"{dimension}{AUTO_SUFFIX}:{value}"


def parse_auto(tag: str) -> tuple[str, str] | None:
    """``("SAT_TASK", "Ner")`` for ``SAT_TASK-AUTO:Ner``; None for other tags."""
    match = _AUTO.match(str(tag).strip())
    if not match or not match.group(2).strip():
        return None
    return match.group(1).upper(), match.group(2).strip()


def is_auto_tag(tag: str) -> bool:
    return parse_auto(tag) is not None


@dataclass
class DimensionState:
    """One dimension of one paper."""

    dimension: str
    human: list[str] = field(default_factory=list)  # DIM:value codes (not ?)
    proposed: list[str] = field(default_factory=list)  # DIM-AUTO:value values
    placeholder: bool = False  # DIM:? present

    @property
    def status(self) -> str:
        """``human`` (coded by a person), ``proposed`` (LLM proposal waiting) or ``todo``."""
        if self.human:
            return HUMAN
        return PROPOSED if self.proposed else TODO

    @property
    def stale_proposals(self) -> bool:
        """Proposals left on a dimension a human has coded (human wins)."""
        return bool(self.human and self.proposed)


def _split(tags: Iterable[str] | str | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(";") if t.strip()]
    return [str(t).strip() for t in tags if str(t).strip()]


def dimension_states(
    tags: Iterable[str] | str | None, dimensions: Iterable[str] | None = None
) -> dict[str, DimensionState]:
    """State of each dimension of a paper (tags: a list or a ``;``-separated cell).

    With ``dimensions``, only those are returned (every one of them, even when
    the paper has no tag for it); else every dimension found in the tags.
    """
    from scilex.tagging.grid import is_automation_tag

    wanted = [d.strip().upper() for d in dimensions] if dimensions is not None else None
    states: dict[str, DimensionState] = {d: DimensionState(d) for d in (wanted or [])}

    def state(dim: str) -> DimensionState | None:
        if wanted is not None and dim not in states:
            return None
        return states.setdefault(dim, DimensionState(dim))

    for tag in _split(tags):
        proposal = parse_auto(tag)
        if proposal:
            target = state(proposal[0])
            if target is not None and proposal[1] not in target.proposed:
                target.proposed.append(proposal[1])
            continue
        if is_automation_tag(tag):
            continue
        dim, sep, value = tag.partition(":")
        dim, value = dim.strip().upper(), value.strip()
        if not sep or not dim or " " in dim or not value:
            continue
        target = state(dim)
        if target is None:
            continue
        if value == PLACEHOLDER:
            target.placeholder = True
        elif value not in target.human:
            target.human.append(value)
    return states


def resolve(
    tags: Iterable[str] | str | None, dimension: str, values: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Tags to add and remove when a person sets ``dimension`` to ``values``.

    Adds ``DIM:value`` for each value; removes ``DIM:?`` and every
    ``DIM-AUTO:*`` proposal. Empty ``values`` = the proposals are rejected:
    they are removed and ``DIM:?`` stays (added if missing), still to annotate.
    """
    dim = dimension.strip().upper()
    current = _split(tags)
    proposals = [t for t in current if (p := parse_auto(t)) is not None and p[0] == dim]
    values = [str(v).strip() for v in values if str(v).strip()]
    if not values:
        return [f"{dim}:{PLACEHOLDER}"], proposals
    remove = proposals + [
        t for t in current if t.upper() == f"{dim}:{PLACEHOLDER}".upper()
    ]
    return [f"{dim}:{v}" for v in values], remove
