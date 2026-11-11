"""Workflow tags of a paper: who annotates it, who validated it, who discarded it.

They are Zotero tags, so the whole team sees and edits them in Zotero and
SciLEx syncs them like the annotation codes:

- ``ANNOT:<id>``          the paper is assigned to annotator ``<id>``;
- ``ANNOT_VALID_BY:<id>`` its annotation is complete against the grid,
  validated by ``<id>``;
- ``DELETED_BY:<who>``    it is discarded from the analyses (kept in the
  corpus): ``<who>`` is a person, or ``filter:<reason>`` for an automatic rule.

``<id>`` is the person's ORCID iD (``0000-0002-1825-0097``) when known, else
their Zotero user name. These tags are not annotation codes: they never count
as a ``DIMENSION:value`` of the grid (see :data:`WORKFLOW_PREFIXES`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

ASSIGNED = "ANNOT"
VALIDATED = "ANNOT_VALID_BY"
DELETED = "DELETED_BY"
# AGREEMENT_COPY:<item key>: an annotator's copy of a paper (scilex.gui.services.agreement).
AGREEMENT_COPY = "AGREEMENT_COPY"
# KEEP:<criterion id>: an exception to an eligibility criterion
# (scilex.gui.services.criteria), set by a person.
KEEP = "KEEP"
WORKFLOW_PREFIXES = (ASSIGNED, VALIDATED, DELETED, AGREEMENT_COPY, KEEP)
FILTER_PREFIX = "filter:"
ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def is_workflow_tag(tag: str) -> bool:
    """True for ``ANNOT:``, ``ANNOT_VALID_BY:`` and ``DELETED_BY:`` tags."""
    dimension, sep, value = tag.partition(":")
    return bool(sep and value) and dimension.strip().upper() in WORKFLOW_PREFIXES


def tag(kind: str, who: str) -> str:
    """``tag(ASSIGNED, "0000-0002-1825-0097")`` -> ``"ANNOT:0000-0002-1825-0097"``."""
    if kind not in WORKFLOW_PREFIXES:
        raise ValueError(f"Unknown workflow tag {kind!r}")
    who = who.strip()
    if not who or ";" in who:
        raise ValueError(f"Invalid identifier {who!r} (empty or with ';')")
    return f"{kind}:{who}"


def filter_tag(reason: str) -> str:
    """Discard tag of an automatic rule: ``DELETED_BY:filter:<reason>``."""
    return tag(DELETED, FILTER_PREFIX + reason.strip().replace(";", ","))


def split_tags(value) -> list[str]:
    """Tags of a ``;``-separated cell (missing values give none)."""
    text = "" if value is None else str(value)
    if text.strip().upper() in ("", "NA", "NAN", "NONE"):
        return []
    return [t.strip() for t in text.split(";") if t.strip()]


@dataclass
class Workflow:
    """Workflow state of one paper, read from its tags."""

    assigned: list[str] = field(default_factory=list)
    validated_by: list[str] = field(default_factory=list)
    deleted_by: list[str] = field(default_factory=list)

    @property
    def deleted(self) -> bool:
        return bool(self.deleted_by)

    @property
    def validated(self) -> bool:
        return bool(self.validated_by)

    @property
    def status(self) -> str:
        """``deleted``, ``validated``, ``assigned`` or ``unassigned``."""
        if self.deleted:
            return "deleted"
        if self.validated:
            return "validated"
        return "assigned" if self.assigned else "unassigned"


def workflow(tags: Iterable[str] | str | None) -> Workflow:
    """Read the workflow tags of a paper (a list or a ``;``-separated cell)."""
    # A list of tags, or a results cell (a string, or NaN when empty).
    items = list(tags) if isinstance(tags, (list, tuple, set)) else split_tags(tags)
    state = Workflow()
    for item in items:
        kind, sep, who = item.partition(":")
        if not sep or not who.strip():
            continue
        kind = kind.strip().upper()
        target = {
            ASSIGNED: state.assigned,
            VALIDATED: state.validated_by,
            DELETED: state.deleted_by,
        }.get(kind)
        if target is not None and who.strip() not in target:
            target.append(who.strip())
    return state


def with_tags(value, add: Iterable[str] = (), remove: Iterable[str] = ()) -> str:
    """The ``;``-separated cell ``value`` with ``add`` added and ``remove`` removed."""
    tags = split_tags(value)
    gone = {t.casefold() for t in remove}
    tags = [t for t in tags if t.casefold() not in gone]
    known = {t.casefold() for t in tags}
    for item in add:
        if item.casefold() not in known:
            tags.append(item)
            known.add(item.casefold())
    return ";".join(tags)
