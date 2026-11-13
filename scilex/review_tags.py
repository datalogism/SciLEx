"""Workflow tags of a paper: who annotates it, who validated it, who discarded it.

They are Zotero tags, so the whole team sees and edits them in Zotero and
SciLEx syncs them like the annotation codes:

- ``ANNOT:<id>``          the paper is assigned to annotator ``<id>``;
- ``ANNOT_VALID_BY:<id>`` its annotation is complete against the grid,
  validated by ``<id>``;
- ``DELETED_BY:<who>``    it is discarded from the analyses (kept in the
  corpus): ``<who>`` is a person, or ``filter:<reason>`` for an automatic rule;
- ``KEEP:screened``       a person put it in a screened-results collection
  (:mod:`scilex.gui.services.collection_roles`): the automatic discards
  (``DELETED_BY:filter:…``) stay as a warning but no longer discard it.
  ``SCREEN:Include`` (a person's screening decision, synced by SciLEx) does
  the same: papers are often kept although they fail a criterion.

:func:`eligibility` reads the screening state of a paper the way an
annotation grid states it (V7 ``SCREEN`` / ``EXCLUDED`` / ``EXCLUSION`` /
``INCLUSION_EXCEPTION``). It is computed from the tags above, never written
back: there is one source of truth.

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
SCREENED_KEEP = f"{KEEP}:screened"
# A person's screening decision (scilex.gui.services.zotero_sync writes it).
SCREEN_INCLUDE = "SCREEN:Include"
SCREEN_EXCLUDE = "SCREEN:Exclude"
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
    screened: bool = False  # KEEP:screened: in a screened-results collection
    included: bool = False  # SCREEN:Include: a person included it
    excluded: bool = False  # SCREEN:Exclude: a person excluded it
    keep: list[str] = field(default_factory=list)  # KEEP:<criterion id>

    @property
    def kept(self) -> bool:
        """A person kept the paper (screened collection or included in Screen)."""
        return self.screened or self.included

    @property
    def deleted(self) -> bool:
        """Discarded: by a person, or by a rule unless a person kept the paper."""
        if self.kept:
            return bool(self.deleted_by_person)
        return bool(self.deleted_by)

    @property
    def deleted_by_person(self) -> list[str]:
        return [who for who in self.deleted_by if not who.startswith(FILTER_PREFIX)]

    @property
    def failed_criteria(self) -> list[str]:
        """Criterion ids of the ``DELETED_BY:filter:<id> <cause>`` tags, in order."""
        ids: list[str] = []
        for who in self.deleted_by:
            if who.startswith(FILTER_PREFIX):
                cid = who[len(FILTER_PREFIX) :].strip().split(" ")[0] or "?"
                if cid not in ids:
                    ids.append(cid)
        return ids

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
        if kind == KEEP and who.strip().casefold() == "screened":
            state.screened = True
            continue
        if kind == KEEP:
            if who.strip() not in state.keep:
                state.keep.append(who.strip())
            continue
        if kind == "SCREEN":
            decision = who.strip().casefold()
            state.included |= decision == "include"
            state.excluded |= decision == "exclude"
            continue
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


# Screening state as an annotation grid states it (V7 Sec. 3).
AUTO, MANUAL = "Auto", "Manual"


@dataclass
class Eligibility:
    """Screening state of one paper, computed from its workflow tags.

    - ``excluded``: the paper leaves the analyses (:attr:`Workflow.deleted`);
    - ``method``: ``Manual`` when a person decided (kept it, excluded it in
      Screen or discarded it), ``Auto`` when only a SciLEx rule did, ``""``
      when nothing was decided;
    - ``exclusion``: the code of the first criterion the paper fails (one code,
      as the grid allows), ``exclusion_all`` every one of them;
    - ``exceptions``: for a kept paper, the criteria it is kept despite of
      (failed criteria and ``KEEP:<id>`` tags).
    """

    excluded: bool = False
    method: str = ""
    exclusion: str = ""
    exclusion_all: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)


def eligibility(
    tags: Iterable[str] | str | None,
    codes: dict[str, str] | None = None,
    order: list[str] | None = None,
) -> Eligibility:
    """The screening state of a paper.

    ``codes`` maps a criterion id to the grid's code (``C3`` -> ``C3-Language``,
    see :func:`scilex.gui.services.criteria.exclusion_codes`); an unmapped id
    stays as it is. ``order`` lists the criterion ids in the protocol order
    (the first failed one gives :attr:`Eligibility.exclusion`).
    """
    state = tags if isinstance(tags, Workflow) else workflow(tags)
    codes = codes or {}
    rank = {cid: i for i, cid in enumerate(order or [])}
    failed = sorted(
        state.failed_criteria, key=lambda cid: (rank.get(cid, len(rank)), cid)
    )
    coded = list(dict.fromkeys(codes.get(cid, cid) for cid in failed))
    result = Eligibility(excluded=state.deleted)
    if state.kept or state.excluded or state.deleted_by_person:
        result.method = MANUAL
    elif failed:
        result.method = AUTO
    if result.excluded:
        result.exclusion_all = coded
        result.exclusion = result.exclusion_all[0] if result.exclusion_all else ""
    elif state.kept:
        result.exceptions = list(
            dict.fromkeys(coded + [codes.get(k, k) for k in state.keep])
        )
    return result
