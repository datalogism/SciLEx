"""Annotators of a review and the papers assigned to them.

The members are those of the review's Zotero library: the group's owner,
admins and members, plus everyone who created or edited one of its items
(Zotero gives user names only through items). They are kept in
``members.yml`` in the review folder, where each member's ORCID iD can be
added; people without a Zotero account can be added by hand.

A member is identified in tags by their ORCID iD when known, else their Zotero
user name (see :mod:`scilex.review_tags`). Assigning papers writes
``ANNOT:<id>`` tags into the review's results; the Zotero sync pushes them.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import yaml

from scilex import review_tags
from scilex.gui.services.workspace import Review

logger = logging.getLogger(__name__)

MEMBERS_FILENAME = "members.yml"
ROLES = ("owner", "admin", "member", "contributor", "manual")


@dataclass
class Member:
    """One person of the review."""

    name: str = ""
    username: str = ""  # Zotero user name
    zotero_id: str = ""
    orcid: str = ""
    role: str = "manual"  # see ROLES; "contributor": seen editing items only

    @property
    def identifier(self) -> str:
        """What the workflow tags use: ORCID iD, else Zotero user name, else name."""
        return self.orcid or self.username or self.name

    @property
    def label(self) -> str:
        who = self.name or self.username or self.orcid
        return f"{who} ({self.identifier})" if who != self.identifier else who


def members_path(folder: Path) -> Path:
    return Path(folder) / MEMBERS_FILENAME


def load(folder: Path) -> list[Member]:
    """Members of the review in ``folder`` (empty if none saved yet)."""
    try:
        raw = yaml.safe_load(members_path(folder).read_text(encoding="utf-8")) or []
    except FileNotFoundError:
        return []
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Ignoring the damaged %s: %s", members_path(folder), exc)
        return []
    fields = set(Member.__dataclass_fields__)
    return [
        Member(**{k: str(v or "") for k, v in m.items() if k in fields})
        for m in raw
        if isinstance(m, dict)
    ]


def save(folder: Path, members: list[Member]) -> None:
    """Write ``members.yml`` (refuses an invalid ORCID or a duplicate identifier)."""
    seen = set()
    for member in members:
        if member.orcid and not review_tags.ORCID.match(member.orcid):
            raise ValueError(
                f"Invalid ORCID iD {member.orcid!r} (expected 0000-0000-0000-0000)"
            )
        key = member.identifier.casefold()
        if not key:
            raise ValueError(
                "A member needs an ORCID iD, a Zotero user name or a name."
            )
        if key in seen:
            raise ValueError(f"Two members are identified as {member.identifier!r}.")
        seen.add(key)
    path = members_path(folder)
    tmp = path.with_suffix(".yml.tmp")
    tmp.write_text(
        yaml.safe_dump(
            [asdict(m) for m in members], sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def _merge(members: list[Member], found: Member) -> None:
    """Add ``found`` or complete the member it already is (ORCIDs are kept)."""
    for member in members:
        same = (found.zotero_id and member.zotero_id == found.zotero_id) or (
            found.username and member.username.casefold() == found.username.casefold()
        )
        if same:
            member.zotero_id = member.zotero_id or found.zotero_id
            member.username = member.username or found.username
            member.name = member.name or found.name
            if ROLES.index(found.role) < ROLES.index(member.role):
                member.role = found.role
            return
    members.append(found)


def discover(review: Review) -> list[Member]:
    """Members of the review's Zotero library, merged into ``members.yml``.

    Raises:
        ValueError: The review has no Zotero library.
        ZoteroNotConfiguredError, ConnectionError: Zotero cannot be read.
    """
    from scilex.gui.services import zotero_library
    from scilex.gui.services.keys_editor import effective_keys

    source = zotero_library.load_source(review.folder)
    if source is None:
        raise ValueError(
            "The review has no Zotero group: choose it on its Zotero group page."
        )
    api = zotero_library.client(effective_keys(review.folder), library=source)
    members = load(review.folder)
    if source.library_type == "group":
        response = api._get("")
        if response is None:
            raise ConnectionError(
                "Zotero cannot be reached (offline, or the key was refused)."
            )
        body = response.json()
        data = body.get("data", body)
        roles = [
            ("owner", [data.get("owner")]),
            ("admin", data.get("admins") or []),
            ("member", data.get("members") or []),
        ]
        for role, ids in roles:
            for user_id in ids:
                if user_id:
                    _merge(members, Member(zotero_id=str(user_id), role=role))
    else:
        _merge(members, Member(zotero_id=str(source.library_id), role="owner"))
    # User names come with the items.
    start = 0
    while True:
        response = api._get("/items/top", params={"limit": 100, "start": start})
        page = response.json() if response is not None else []
        for item in page:
            for key in ("createdByUser", "lastModifiedByUser"):
                user = item.get("meta", {}).get(key)
                if user:
                    _merge(
                        members,
                        Member(
                            zotero_id=str(user.get("id") or ""),
                            username=str(user.get("username") or ""),
                            name=str(user.get("name") or ""),
                            role="contributor",
                        ),
                    )
        if len(page) < 100:
            break
        start += 100
    members = [m for m in members if m.identifier]
    save(review.folder, members)
    return members


@dataclass
class GroupMember:
    """One row of the review's group page: a person and their place."""

    label: str
    role: str  # owner, admin, member (of the Zotero group), contributor, manual
    zotero_id: str = ""
    username: str = ""
    orcid: str = ""
    in_group: bool = False


def group_roster(group, saved: list[Member]) -> list[GroupMember]:
    """The group's people (owner, admins, members), then the review's other members.

    ``group`` is a :class:`~scilex.gui.services.zotero_library.ZoteroGroup`
    (None: the group could not be read, the saved members only). Names and
    ORCID iDs come from ``members.yml`` (Zotero gives only user ids).
    """
    by_id = {m.zotero_id: m for m in saved if m.zotero_id}
    rows: list[GroupMember] = []
    seen: set[str] = set()
    if group is not None:
        people = [("owner", [group.owner]), ("admin", group.admins)]
        people.append(("member", group.members))
        for role, ids in people:
            for user_id in ids:
                if not user_id or user_id in seen:
                    continue
                seen.add(user_id)
                known = by_id.get(user_id)
                rows.append(
                    GroupMember(
                        label=(known.name or known.username)
                        if known and (known.name or known.username)
                        else f"Zotero user {user_id}",
                        role=role,
                        zotero_id=user_id,
                        username=known.username if known else "",
                        orcid=known.orcid if known else "",
                        in_group=True,
                    )
                )
    for member in saved:
        if member.zotero_id and member.zotero_id in seen:
            continue
        rows.append(
            GroupMember(
                label=member.name or member.username or member.orcid,
                role=member.role,
                zotero_id=member.zotero_id,
                username=member.username,
                orcid=member.orcid,
                in_group=group is None and member.role in ("owner", "admin", "member"),
            )
        )
    return rows


# -- assignment ---------------------------------------------------------------


@dataclass
class Assignment:
    """Papers to tag ``ANNOT:<id>``: results index -> annotator identifiers."""

    plan: dict[int, list[str]]
    load: dict[str, int]  # papers per annotator after the assignment

    def message(self) -> str:
        if not self.plan:
            return "No paper to assign."
        loads = ", ".join(f"{who}: {n}" for who, n in sorted(self.load.items()))
        return f"{len(self.plan)} papers to assign ({loads})."


def _sub_corpora(value) -> set[str]:
    return {p.split("/")[0].strip().casefold() for p in review_tags.split_tags(value)}


def plan_assignment(
    data: pd.DataFrame,
    annotators: list[str],
    *,
    per_paper: int = 1,
    only_unassigned: bool = True,
    sub_corpus: str | None = None,
    include_deleted: bool = False,
) -> Assignment:
    """Spread papers over ``annotators`` so that their loads stay balanced.

    Papers already assigned count in the loads. ``per_paper`` > 1 gives each
    paper to several annotators (cross-annotation, as for agreement studies).
    """
    if not annotators:
        raise ValueError("Choose at least one annotator.")
    per_paper = max(1, min(per_paper, len(annotators)))
    tags = data.get("tags", pd.Series("", index=data.index))
    corpora = data.get("zotero_collections", pd.Series("", index=data.index))
    load = Counter({who: 0 for who in annotators})
    states = {index: review_tags.workflow(tags[index]) for index in data.index}
    for state in states.values():
        for who in state.assigned:
            if who in load:
                load[who] += 1
    plan: dict[int, list[str]] = {}
    for index in data.index:
        state = states[index]
        if state.deleted and not include_deleted:
            continue
        if sub_corpus and sub_corpus.casefold() not in _sub_corpora(corpora[index]):
            continue
        missing = per_paper - len(state.assigned)
        if only_unassigned and state.assigned:
            continue
        if missing <= 0:
            continue
        free = [who for who in annotators if who not in state.assigned]
        chosen = sorted(free, key=lambda who: (load[who], annotators.index(who)))[
            :missing
        ]
        for who in chosen:
            load[who] += 1
        if chosen:
            plan[index] = chosen
    return Assignment(plan, dict(load))


def apply_tags(review: Review, changes: dict[int, tuple[list[str], list[str]]]) -> int:
    """Add / remove tags on results rows: ``{index: (add, remove)}``; return rows changed."""
    from scilex.gui.services.extend import backup, read_results
    from scilex.gui.services.results_store import write_changes

    before = read_results(review.results_path)
    data = before.copy()
    if "tags" not in data.columns:
        data["tags"] = ""
    data["tags"] = data["tags"].astype(object)
    changed = 0
    for index, (add, remove) in changes.items():
        old = data.at[index, "tags"]
        new = review_tags.with_tags(old, add, remove)
        if new != review_tags.with_tags(old):
            data.at[index, "tags"] = new
            changed += 1
    if changed:
        backup(review.results_path)
        # Only the changed tag cells: an enricher running meanwhile keeps its work.
        write_changes(review.results_path, before, data)
    return changed


def assign(review: Review, assignment: Assignment) -> int:
    """Write the ``ANNOT:<id>`` tags of ``assignment``; return papers tagged."""
    return apply_tags(
        review,
        {
            index: ([review_tags.tag(review_tags.ASSIGNED, who) for who in whos], [])
            for index, whos in assignment.plan.items()
        },
    )


def progress(data: pd.DataFrame) -> list[dict]:
    """Per annotator: papers assigned, validated and discarded (for a table)."""
    rows: dict[str, Counter] = {}
    for value in data.get("tags", pd.Series("", index=data.index)):
        state = review_tags.workflow(value)
        for who in state.assigned:
            counts = rows.setdefault(who, Counter())
            counts["assigned"] += 1
            counts["validated"] += state.validated
            counts["deleted"] += state.deleted
        for who in state.validated_by:
            rows.setdefault(who, Counter())["validated_by_them"] += 1
    return [
        {
            "annotator": who,
            **{
                k: counts.get(k, 0)
                for k in ("assigned", "validated", "deleted", "validated_by_them")
            },
        }
        for who, counts in sorted(rows.items())
    ]


def apply_tags_by_key(
    review: Review, changes: dict[str, tuple[list[str], list[str]]]
) -> dict[str, str]:
    """:func:`apply_tags` addressed by paper key; return each paper's new tags."""
    from scilex.gui.services.extend import read_results
    from scilex.gui.services.screening import paper_key

    data = read_results(review.results_path)
    by_index = {}
    for index, record in zip(data.index, data.to_dict("records"), strict=True):
        key = paper_key(record)
        if key in changes and index not in by_index.values():
            by_index[key] = index
    apply_tags(
        review,
        {by_index[key]: change for key, change in changes.items() if key in by_index},
    )
    data = read_results(review.results_path)
    return {
        key: review_tags.with_tags(data.at[index, "tags"] if "tags" in data else "")
        for key, index in by_index.items()
    }
