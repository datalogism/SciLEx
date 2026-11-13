"""Annotation campaigns: who annotates which collection, against which dimensions.

A campaign is one Zotero collection of the review (usually a screened-results
collection, e.g. ``datasets``) with:

- the paper type whose grid dimensions apply (``datasets``, ``surveys``,
  ``models`` or ``all``);
- its human annotators (members of the review, :mod:`members`), and how many
  of them annotate each paper (2 or more = cross-annotation, measured by the
  agreement study);
- its LLM annotators: model strings run by SciLEx Annotator
  (:mod:`llm_annotator`), which only propose ``DIMENSION-AUTO:value`` tags.

Campaigns are kept in ``campaigns.yml`` in the review folder, with the address
of the SciLEx Annotator service (its token is a key, in ``keys.yml``).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from scilex import review_tags
from scilex.tagging import auto_tags
from scilex.tagging.grid import ALL_TYPES, PAPER_TYPES, tags_for_type

logger = logging.getLogger(__name__)

FILENAME = "campaigns.yml"
COLUMN = "zotero_collections"
DEFAULT_ANNOTATOR_URL = "http://127.0.0.1:8000"
DEFAULT_MODEL = "anthropic:claude-opus-5-5"
LLM_PREFIX = "llm:"  # an LLM annotator's identifier in agreement studies

# A screened collection's paper type (collection_roles) or name -> grid paper type.
_GRID_TYPE_CUES = (
    (re.compile(r"survey|review|state[- ]of[- ]the[- ]art", re.I), "surveys"),
    (re.compile(r"data ?set|corpus|corpora|bench", re.I), "datasets"),
    (re.compile(r"model|method|approach|system", re.I), "models"),
)


@dataclass
class Campaign:
    """One collection to annotate."""

    id: str
    name: str = ""
    collection: str = ""  # path "Parent / Child"; "" = every paper of the review
    paper_type: str = ALL_TYPES
    annotators: list[str] = field(default_factory=list)  # member identifiers
    per_paper: int = 1
    llm_models: list[str] = field(default_factory=list)
    created_at: str = ""

    @property
    def label(self) -> str:
        return self.name or self.collection or "All papers"


@dataclass
class Campaigns:
    """Content of ``campaigns.yml``."""

    annotator_url: str = DEFAULT_ANNOTATOR_URL
    campaigns: list[Campaign] = field(default_factory=list)

    def get(self, campaign_id: str) -> Campaign | None:
        return next((c for c in self.campaigns if c.id == campaign_id), None)


def path_of(folder: Path) -> Path:
    return Path(folder) / FILENAME


def load(folder: Path) -> Campaigns:
    try:
        raw = yaml.safe_load(path_of(folder).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return Campaigns()
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Ignoring the damaged %s: %s", path_of(folder), exc)
        return Campaigns()
    fields = set(Campaign.__dataclass_fields__)
    campaigns = []
    for entry in raw.get("campaigns") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        values = {k: v for k, v in entry.items() if k in fields}
        values["annotators"] = [str(a) for a in values.get("annotators") or []]
        values["llm_models"] = [str(m) for m in values.get("llm_models") or []]
        values["per_paper"] = max(1, int(values.get("per_paper") or 1))
        if values.get("paper_type") not in (ALL_TYPES, *PAPER_TYPES):
            values["paper_type"] = ALL_TYPES
        for key in ("id", "name", "collection", "created_at"):
            values[key] = str(values.get(key) or "")
        campaigns.append(Campaign(**values))
    return Campaigns(
        annotator_url=str(raw.get("annotator_url") or DEFAULT_ANNOTATOR_URL),
        campaigns=campaigns,
    )


def save(folder: Path, data: Campaigns) -> Path:
    ids = [c.id for c in data.campaigns]
    if len(ids) != len(set(ids)):
        raise ValueError("Two campaigns have the same id.")
    for campaign in data.campaigns:
        if campaign.paper_type not in (ALL_TYPES, *PAPER_TYPES):
            raise ValueError(f"Unknown paper type {campaign.paper_type!r}.")
    path = path_of(folder)
    tmp = path.with_suffix(".yml.tmp")
    tmp.write_text(
        yaml.safe_dump(
            {
                "annotator_url": data.annotator_url,
                "campaigns": [asdict(c) for c in data.campaigns],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def new_id(name: str, existing: list[str]) -> str:
    """A short id from ``name`` (letters, digits, - and _), unique among ``existing``."""
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")[:40] or "campaign"
    candidate, n = base, 2
    while candidate in existing:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def create(
    folder: Path,
    collection: str,
    *,
    name: str = "",
    paper_type: str = ALL_TYPES,
    annotators: list[str] | None = None,
    per_paper: int = 1,
    llm_models: list[str] | None = None,
) -> Campaign:
    """Add a campaign to ``campaigns.yml`` and return it."""
    data = load(folder)
    campaign = Campaign(
        id=new_id(name or collection or "all", [c.id for c in data.campaigns]),
        name=name or collection,
        collection=collection,
        paper_type=paper_type,
        annotators=list(annotators or []),
        per_paper=max(1, int(per_paper)),
        llm_models=list(llm_models or []),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    data.campaigns.append(campaign)
    save(folder, data)
    return campaign


def update(folder: Path, campaign: Campaign) -> None:
    data = load(folder)
    data.campaigns = [campaign if c.id == campaign.id else c for c in data.campaigns]
    if data.get(campaign.id) is None:
        data.campaigns.append(campaign)
    save(folder, data)


def remove(folder: Path, campaign_id: str) -> None:
    data = load(folder)
    data.campaigns = [c for c in data.campaigns if c.id != campaign_id]
    save(folder, data)


# -- papers of a campaign ----------------------------------------------------------


def collection_paths(data: pd.DataFrame) -> list[str]:
    """Every collection of the results, parents included, sorted."""
    paths: set[str] = set()
    for value in data.get(COLUMN, pd.Series(dtype=object)).dropna():
        for path in review_tags.split_tags(value):
            parts = [p.strip() for p in path.split(" / ") if p.strip()]
            for end in range(1, len(parts) + 1):
                paths.add(" / ".join(parts[:end]))
    return sorted(paths, key=str.casefold)


def suggest_type(collection: str, folder: Path | None = None) -> str:
    """Grid paper type for ``collection``: its screened role's type, else its name."""
    if folder is not None:
        from scilex.gui.services import collection_roles

        role = collection_roles._role_for(collection, collection_roles.load(folder))
        if role is not None and role.paper_type:
            for pattern, kind in _GRID_TYPE_CUES:
                if pattern.search(str(role.paper_type)):
                    return kind
    for pattern, kind in _GRID_TYPE_CUES:
        if pattern.search(collection.split(" / ")[0]):
            return kind
    return ALL_TYPES


def in_collection(value, collection: str) -> bool:
    """True when a ``zotero_collections`` cell holds ``collection`` or a sub-collection."""
    if not collection:
        return True
    target = collection.strip().casefold()
    for path in review_tags.split_tags(value):
        path = " / ".join(p.strip() for p in path.split("/") if p.strip()).casefold()
        if path == target or path.startswith(target + " / "):
            return True
    return False


def paper_rows(data: pd.DataFrame, campaign: Campaign) -> list:
    """Results indexes of the campaign's papers (discarded papers left out)."""
    cells = data.get(COLUMN, pd.Series("", index=data.index))
    tags = data.get("tags", pd.Series("", index=data.index))
    return [
        index
        for index in data.index
        if in_collection(cells[index], campaign.collection)
        and not review_tags.workflow(tags[index]).deleted
    ]


def dimensions(grid: pd.DataFrame, campaign: Campaign) -> list[str]:
    """The grid dimensions the campaign's papers are annotated on."""
    if grid is None or grid.empty:
        return []
    return tags_for_type(grid, campaign.paper_type)


def plan_assignment(data: pd.DataFrame, campaign: Campaign, *, only_unassigned=True):
    """Balanced ``ANNOT:<id>`` assignment of the campaign's papers to its annotators.

    Loads are counted inside the campaign, so each campaign is balanced on its own.
    """
    from scilex.gui.services import members

    if not campaign.annotators:
        raise ValueError(
            "The campaign has no human annotator: add some to the campaign first."
        )
    subset = data.loc[paper_rows(data, campaign)]
    return members.plan_assignment(
        subset,
        campaign.annotators,
        per_paper=campaign.per_paper,
        only_unassigned=only_unassigned,
    )


# -- progress ------------------------------------------------------------------


@dataclass
class Progress:
    """Where a campaign stands."""

    papers: int = 0
    assigned: int = 0
    validated: int = 0  # ANNOT_VALID_BY
    cells: Counter = field(default_factory=Counter)  # human / proposed / todo
    by_dimension: list[dict] = field(default_factory=list)
    stale: int = 0  # proposals left on human-coded dimensions

    @property
    def done_share(self) -> float:
        total = sum(self.cells.values())
        return self.cells[auto_tags.HUMAN] / total if total else 0.0


def progress(data: pd.DataFrame, campaign: Campaign, dims: list[str]) -> Progress:
    """Counts per paper and per (paper, dimension) of the campaign."""
    result = Progress()
    per_dim = {d: Counter() for d in dims}
    tags = data.get("tags", pd.Series("", index=data.index))
    for index in paper_rows(data, campaign):
        result.papers += 1
        state = review_tags.workflow(tags[index])
        result.assigned += bool(state.assigned)
        result.validated += state.validated
        for dim, cell in auto_tags.dimension_states(tags[index], dims).items():
            result.cells[cell.status] += 1
            per_dim[dim][cell.status] += 1
            result.stale += cell.stale_proposals
    result.by_dimension = [
        {
            "dimension": dim,
            "human": counts[auto_tags.HUMAN],
            "proposed": counts[auto_tags.PROPOSED],
            "todo": counts[auto_tags.TODO],
        }
        for dim, counts in per_dim.items()
    ]
    return result
