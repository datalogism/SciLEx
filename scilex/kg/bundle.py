"""The survey bundle: everything a review records, for the knowledge-graph dump (SX-1).

The scilex-lpwc-ap profile (iteration 5 on, ORSD SR1, D29) maps two files of a
review: its Zotero BibLaTeX export, and ``survey.json``, written here. The bundle
holds what the bibliography cannot: configuration and criteria versions, the
grid, sub-corpus roles, members, screening decisions, exclusions, agreement
studies, the journal, venues, scores, metrics...

Layout (``docs/ontology-dev/survey-bundle.md``): **flat parts**, one top-level
array per part, each paper row carrying the paper's citation key in ``paper``
(the profile's paper IRI ``br/<key>``). morph-kgc iterates one JSONPath per part
(``$.venues[*]``), and the manifest (``parts``) gives one row count per array.

Three disclosure levels (ORSD SR17, D36): ``public`` (the default for a file
meant to be shared), ``team`` and ``full``. A part above the dump's level is
listed in the manifest as ``withheld`` and left out. No secret at any level:
every string goes through :func:`scilex.crawlers.utils.sanitize_secrets`, and the
values of the keys file are masked (SX-14).
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scilex.crawlers.utils import sanitize_secrets

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
BUNDLE_FILENAME = "survey.json"
PUBLIC, TEAM, FULL = "public", "team", "full"
LEVELS = (PUBLIC, TEAM, FULL)
WITHHELD_TEXT = "<withheld>"
ISSN = re.compile(r"^\s*(\d{4})-?(\d{3}[\dXx])\s*$")
ORCID_ID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
ORCID_IRI = "https://orcid.org/"
MISSING = {"", "na", "nan", "none", "null"}
# Corpus columns of the enrichers (SR14) and of the citation metrics (SR13).
ENRICHMENT_PREFIXES = ("lpwc_", "orkg_", "crossref_", "zenodo_", "pwc_")
ENRICHMENT_COLUMNS = ("code_license", "code_repository")
METRIC_PREFIX = "metric_"

# part -> (lowest level it is exported at, source shown in the manifest)
PARTS: dict[str, tuple[str, str]] = {
    "papers": (PUBLIC, "corpus + BibLaTeX export (join keys)"),
    "config_versions": (PUBLIC, "config_history/, scilex.yml"),
    "config_parameters": (PUBLIC, "config_history/"),
    "criteria_versions": (PUBLIC, "criteria_history/, criteria.yml"),
    "criteria": (PUBLIC, "criteria_history/"),
    "grid": (PUBLIC, "annotation_grid.csv"),
    "subcorpora": (PUBLIC, "collection_roles.yml"),
    "members": (PUBLIC, "members.yml"),
    "screening": (PUBLIC, "screening.csv"),
    "excluded": (PUBLIC, "DELETED_BY: tags"),
    "keep": (PUBLIC, "KEEP: tags"),
    "assignments": (PUBLIC, "ANNOT: / ANNOT_VALID_BY: tags"),
    "paper_types": (PUBLIC, "PAPER_TYPE: tags, paper_type_origin"),
    "agreement_studies": (TEAM, "annotations/agreement/*.json"),
    "agreement_measures": (PUBLIC, "annotations/agreement/*.json"),
    "agreement_codes": (TEAM, "annotations/agreement/*.json"),
    "journal": (PUBLIC, "workflow.jsonl"),
    "annotation_history": (PUBLIC, "annotation_history.jsonl"),
    "annotation_codes": (PUBLIC, "annotation_history.jsonl (codes added / removed)"),
    "paper_log": (PUBLIC, "paper_log.json"),
    "snowball": (PUBLIC, "snowball.yml"),
    "aggregation": (PUBLIC, "aggregation_stats.csv"),
    "scores": (PUBLIC, "aggregated_results.csv (relevance_score, quality_score)"),
    "venues": (
        PUBLIC,
        "aggregated_results.csv (journalAbbreviation, serie, conferenceName)",
    ),
    "metrics": (PUBLIC, "aggregated_results.csv (metric_*)"),
    "enrichment": (
        PUBLIC,
        "aggregated_results.csv (lpwc_*, orkg_*, crossref_*, zenodo_*)",
    ),
    "zotero": (PUBLIC, "zotero_source.yml"),
    "origin_kg": (PUBLIC, "kg_source.yml"),
}


@dataclass
class BundleReport:
    """What :func:`write_bundle` wrote."""

    path: Path
    disclosure: str
    parts: dict[str, str] = field(default_factory=dict)  # part -> status
    papers: int = 0
    unmatched: int = 0  # corpus papers with no BibLaTeX entry
    masked: int = 0  # strings where a secret was masked


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    text = str(value).strip()
    return "" if text.lower() in MISSING else text


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _read_yaml(path: Path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def agent_iri(identifier: str) -> str:
    """``0000-0002-1825-0097`` -> its ORCID IRI; other ids are kept as they are."""
    identifier = _text(identifier)
    if ORCID_ID.match(identifier):
        return ORCID_IRI + identifier
    return identifier


def issn_of(value) -> str | None:
    match = ISSN.match(_text(value))
    return f"{match.group(1)}-{match.group(2).upper()}" if match else None


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _json_text(value) -> str:
    """Nested journal fields as one JSON string (RML reads flat values)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class _Scrubber:
    """Masks credentials in every string: API keys in URLs, the keys file's values."""

    def __init__(self, secrets: Iterable[str] = ()):
        self.secrets = sorted(
            {s for s in (str(x).strip() for x in secrets) if len(s) >= 6},
            key=len,
            reverse=True,
        )
        self.masked = 0

    def __call__(self, value):
        if isinstance(value, Mapping):
            return {k: self(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self(v) for v in value]
        if not isinstance(value, str):
            return value
        clean = sanitize_secrets(value)
        for secret in self.secrets:
            if secret in clean:
                clean = clean.replace(secret, "***")
        if clean != value:
            self.masked += 1
        return clean


def secret_values(keys: Mapping | None) -> list[str]:
    """Every string value of a keys file (API keys, tokens, e-mail addresses)."""
    found: list[str] = []

    def walk(value) -> None:
        if isinstance(value, Mapping):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, str) and value.strip():
            found.append(value.strip())

    walk(keys or {})
    return found


# ---------------------------------------------------------------------------
# The join of a paper's keys (SX-2)
# ---------------------------------------------------------------------------


@dataclass
class Paper:
    key: str  # citation key (the profile's br/<key>), else derived from paper_key
    paper_key: str  # SciLEx's key: doi:<doi> / title:<title>|<year>
    zotero_key: str = ""
    in_bibliography: bool = False
    tags: list[str] = field(default_factory=list)
    row: dict = field(default_factory=dict)  # corpus row, when there is one


def derived_key(paper_key: str) -> str:
    """Key of a paper without BibLaTeX entry (review not linked, or not exported)."""
    return "sx-" + hashlib.sha1(paper_key.encode("utf-8")).hexdigest()[:12]


def join_papers(bib: Mapping, corpus: list[dict]) -> list[Paper]:
    """One :class:`Paper` per paper: BibLaTeX entries joined to corpus rows.

    A BibLaTeX entry and a corpus row are the same paper when their
    :func:`~scilex.gui.services.screening.paper_key` (normalised DOI, else
    normalised title and year) is the same.
    """
    from scilex.gui.services.screening import paper_key

    keywords: dict[str, list[str]] = {}
    for row in bib.get("lists", []):
        if row.get("field") == "keywords":
            keywords.setdefault(row["entry"], []).append(str(row["value"]))
    papers: list[Paper] = []
    by_paper_key: dict[str, Paper] = {}
    for entry in bib.get("entries", []):
        key = paper_key(
            {
                "DOI": entry.get("doi"),
                "title": entry.get("title"),
                "date": entry.get("date"),
            }
        )
        paper = Paper(
            key=entry["ID"],
            paper_key=key,
            in_bibliography=True,
            tags=keywords.get(entry["ID"], []),
        )
        papers.append(paper)
        by_paper_key.setdefault(key, paper)
    from scilex import review_tags

    for row in corpus:
        key = row.get("paper_key") or paper_key(row)
        paper = by_paper_key.get(key)
        if paper is None:
            paper = Paper(key=derived_key(key), paper_key=key)
            paper.tags = review_tags.split_tags(row.get("tags"))
            papers.append(paper)
            by_paper_key[key] = paper
        if not paper.row:
            paper.row = row
            paper.zotero_key = _text(row.get("zotero_key"))
    return papers


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------


class _Agents:
    """Agent ids as the dump may show them (members named only with consent)."""

    def __init__(self, members: list[dict], owner: str, disclosure: str):
        self.disclosure = disclosure
        self.public = {agent_iri(owner)} if owner else set()
        known = []
        for member in members:
            ident = agent_iri(
                member.get("orcid") or member.get("username") or member.get("name")
            )
            if not ident:
                continue
            known.append(ident)
            if member.get("consent_public") and member.get("orcid"):
                self.public.add(ident)
        self.pseudonyms = {
            ident: f"agent/{n}" for n, ident in enumerate(sorted(set(known)), 1)
        }

    def __call__(self, identifier: str) -> str:
        ident = agent_iri(identifier)
        if not ident or self.disclosure != PUBLIC or ident in self.public:
            return ident
        if ident.startswith(("filter:", "scilex")):
            return ident
        if ident not in self.pseudonyms:
            self.pseudonyms[ident] = f"agent/{len(self.pseudonyms) + 1}"
        return self.pseudonyms[ident]


def _corpus(collection_dir: Path, name: str) -> list[dict]:
    from scilex.gui.services.screening import paper_key

    path = Path(collection_dir) / "aggregated_results.csv"
    if not path.is_file():
        return []
    try:
        from scilex.io_utils import load_aggregated_data

        data = load_aggregated_data(
            {"collect_name": name}, collect_dir=str(collection_dir)
        )
    except Exception:  # damaged file: the bundle says the corpus is absent
        logger.warning("Cannot read %s for the survey bundle", path, exc_info=True)
        return []
    records = data.to_dict("records")
    for record in records:
        record["paper_key"] = paper_key(record)
    return records


def _config_parts(folder: Path) -> tuple[list, list]:
    from scilex.gui.services import versions

    versions.ensure_current(folder, versions.CONFIG)
    rows, parameters, previous = [], [], None
    for number, version in enumerate(
        versions.load_versions(folder, versions.CONFIG), 1
    ):
        key = version["sha256"][:12]
        rows.append(
            {
                "key": key,
                "sha256": version["sha256"],
                "at": version.get("at"),
                "version": number,
                "previous": previous,
            }
        )
        previous = key
        for value in version.get("values") or []:
            raw = value.get("value")
            parameters.append(
                {
                    "config": key,
                    "path": value.get("path"),
                    "value": raw if isinstance(raw, str) else _json_text(raw),
                    "datatype": type(raw).__name__,
                    "default": bool(value.get("default")),
                }
            )
    return rows, parameters


def _criteria_parts(folder: Path) -> tuple[list, list]:
    from scilex.gui.services import versions

    versions.ensure_current(folder, versions.CRITERIA)
    rows, criteria, previous = [], [], None
    for number, version in enumerate(
        versions.load_versions(folder, versions.CRITERIA), 1
    ):
        key = version["sha256"][:12]
        rows.append(
            {
                "key": key,
                "sha256": version["sha256"],
                "at": version.get("at"),
                "version": number,
                "previous": previous,
            }
        )
        previous = key
        for item in version.get("criteria") or []:
            if not isinstance(item, Mapping):
                continue
            criteria.append(
                {
                    "version": key,
                    "id": item.get("id"),
                    "kind": item.get("kind"),
                    "label": item.get("label") or item.get("name"),
                    "enabled": bool(item.get("enabled", True)),
                    "ec": item.get("ec") or item.get("exclusion"),
                    "ic": item.get("ic") or item.get("inclusion"),
                    "exception": item.get("exception") or item.get("exceptions"),
                    "params": _json_text(
                        {
                            k: v
                            for k, v in item.items()
                            if k not in {"id", "kind", "label", "name", "enabled"}
                        }
                    ),
                }
            )
    return rows, criteria


def _grid(folder: Path) -> list[dict]:
    from scilex.tagging.grid import (
        DETAIL_COLUMN,
        GRID_FILENAME,
        PAPER_TYPES,
        TAG_COLUMN,
        load_grid,
    )

    path = Path(folder) / GRID_FILENAME
    if not path.is_file():
        return []
    grid = load_grid(path)
    return [
        {
            "dimension": row[TAG_COLUMN],
            "question": _text(row.get(DETAIL_COLUMN)),
            "paper_types": [t for t in PAPER_TYPES if _text(row.get(t))],
        }
        for _, row in grid.iterrows()
    ]


def _criteria_version_at(criteria_events: list[dict], at: str) -> str | None:
    """Key of the criteria version applied last before ``at`` (else the last one)."""
    chosen = None
    for event in criteria_events:
        sha = (event.get("used") or {}).get("criteria.yml sha256")
        if not sha:
            continue
        if at and str(event.get("at", "")) > at:
            break
        chosen = sha[:12]
    return chosen


def build_bundle(
    folder: Path,
    collection_dir: Path,
    *,
    review_name: str,
    bib: Mapping,
    base_iri: str = "",
    owner: str = "",
    disclosure: str = PUBLIC,
    secrets: Iterable[str] = (),
    profile_version_iri: str = "",
) -> tuple[dict, BundleReport]:
    """Return the survey bundle of a review (a JSON-ready dict) and its report.

    Args:
        folder: Review folder.
        collection_dir: Collection folder (``output/<name>/``).
        review_name: Review name.
        bib: bib2json tables of the review's BibLaTeX export.
        base_iri: Base IRI of the review's graph.
        owner: IRI of the owner's ORCID iD.
        disclosure: ``public``, ``team`` or ``full``.
        secrets: Literal values to mask everywhere (the keys file's values).
        profile_version_iri: Version IRI of the pinned profile.
    """
    from scilex import paper_types, review_tags
    from scilex.gui.services import agreement, members, paper_log
    from scilex.gui.services import collection_roles as roles_service
    from scilex.gui.services.journal import FILENAME as JOURNAL_FILE
    from scilex.gui.services.overview import HISTORY_FILENAME
    from scilex.kg.profile import slugify

    if disclosure not in LEVELS:
        raise ValueError(
            f"Unknown disclosure level {disclosure!r} ({', '.join(LEVELS)})"
        )
    level = LEVELS.index(disclosure)
    folder, collection_dir = Path(folder), Path(collection_dir)
    scrub = _Scrubber(secrets)
    parts: dict[str, list | dict] = {}
    sources: dict[str, Path | None] = {}

    corpus = _corpus(collection_dir, review_name)
    papers = join_papers(bib, corpus)
    by_paper_key = {p.paper_key: p for p in papers}
    member_rows = [
        {**m.__dict__, "consent_public": getattr(m, "consent_public", False)}
        for m in members.load(folder)
    ]
    agents = _Agents(member_rows, owner, disclosure)
    journal_events = _read_jsonl(folder / JOURNAL_FILE)
    criteria_events = [e for e in journal_events if e.get("activity") == "criteria"]

    parts["papers"] = [
        {
            "paper": p.key,
            "paper_key": p.paper_key,
            "zotero_key": p.zotero_key or None,
            "in_bibliography": p.in_bibliography,
        }
        for p in papers
    ]
    sources["papers"] = collection_dir / "aggregated_results.csv"

    parts["config_versions"], parts["config_parameters"] = _config_parts(folder)
    sources["config_versions"] = folder / "scilex.yml"
    parts["criteria_versions"], parts["criteria"] = _criteria_parts(folder)
    sources["criteria_versions"] = folder / "criteria.yml"
    parts["grid"] = _grid(folder)
    sources["grid"] = folder / "annotation_grid.csv"

    roles = roles_service.load(folder)
    parts["subcorpora"] = [
        {
            "path": r.path,
            "role": r.role,
            "paper_type": r.paper_type,
            "zotero_key": r.key or None,
        }
        for r in roles.values()
    ]
    sources["subcorpora"] = roles_service.path_of(folder)

    parts["members"] = [
        {
            "id": agents(m.get("orcid") or m.get("username") or m.get("name")),
            "name": m.get("name") if level >= LEVELS.index(TEAM) else None,
            "zotero_user": m.get("username") if level >= LEVELS.index(TEAM) else None,
            "role": m.get("role"),
            "consent_public": bool(m.get("consent_public")),
        }
        for m in member_rows
    ]
    sources["members"] = members.members_path(folder)

    # Screening decisions (SX-5: decided_by)
    screening_rows = []
    path = collection_dir / "screening.csv"
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                paper = by_paper_key.get(row.get("paper_key", ""))
                screening_rows.append(
                    {
                        "paper": paper.key
                        if paper
                        else derived_key(row.get("paper_key", "")),
                        "decision": row.get("decision"),
                        "at": row.get("updated_at") or None,
                        "by": agents(row.get("decided_by", "")) or None,
                        "note": (row.get("note") or None)
                        if level >= LEVELS.index(TEAM)
                        else None,
                    }
                )
    parts["screening"] = screening_rows
    sources["screening"] = path

    # Workflow tags: exclusions (SX-3), exceptions, assignments, types (SX-17)
    excluded, keep, assignments, types = [], [], [], []
    for p in papers:
        state = review_tags.workflow(p.tags)
        for who in state.deleted_by:
            if who.startswith(review_tags.FILTER_PREFIX):
                rule = who[len(review_tags.FILTER_PREFIX) :].strip()
                criterion, _, cause = rule.partition(" ")
                excluded.append(
                    {
                        "paper": p.key,
                        "by": f"filter:{criterion}",
                        "criterion": criterion,
                        "criteria_version": _criteria_version_at(criteria_events, ""),
                        "cause": cause or None,
                        "kept": state.kept,
                    }
                )
            else:
                excluded.append(
                    {
                        "paper": p.key,
                        "by": agents(who),
                        "criterion": None,
                        "criteria_version": None,
                        "cause": None,
                        "kept": False,
                    }
                )
        keep += [{"paper": p.key, "criterion": c} for c in state.keep]
        assignments += [
            {"paper": p.key, "agent": agents(a), "role": "assigned"}
            for a in state.assigned
        ]
        assignments += [
            {"paper": p.key, "agent": agents(a), "role": "validated"}
            for a in state.validated_by
        ]
        origin = (
            _text(p.row.get(paper_types.ORIGIN_COLUMN)) or paper_types.UNKNOWN_ORIGIN
        )
        if origin.startswith("person:"):
            origin = "person:" + agents(origin[len("person:") :])
        types += [
            {"paper": p.key, "type": t, "origin": origin}
            for t in paper_types.types_of({"tags": ";".join(p.tags)})
        ]
    parts["excluded"], parts["keep"] = excluded, keep
    parts["assignments"], parts["paper_types"] = assignments, types

    # Agreement studies (SX-4): codes per annotator on the original papers.
    by_zotero = {p.zotero_key: p.key for p in papers if p.zotero_key}
    studies, measures, codes = [], [], []
    for study in agreement.load_studies(collection_dir):
        study_id = Path(study["file"]).stem
        merge = study.get("merge") or {}
        studies.append(
            {
                "study": study_id,
                "at": study.get("at"),
                "file": study["file"],
                "sample": [by_zotero.get(k, k) for k in study.get("sample", [])],
                "annotators": [agents(a) for a in study.get("annotators", [])],
                "merge_rule": merge.get("rule"),
                "to_adjudicate": [
                    {"paper": by_zotero.get(d["paper"], d["paper"]), "code": d["code"]}
                    for d in merge.get("to_adjudicate", [])
                ],
            }
        )
        measures += [{"study": study_id, **m} for m in study.get("measures", [])]
        codes += [
            {
                "study": study_id,
                "paper": by_zotero.get(c["paper"], c["paper"]),
                "annotator": agents(c["annotator"]),
                "dimension": c["dimension"],
                "value": c["value"],
            }
            for c in study.get("codes", [])
        ]
    parts["agreement_studies"], parts["agreement_measures"] = studies, measures
    parts["agreement_codes"] = codes
    sources["agreement_studies"] = collection_dir / agreement.STUDY_DIR

    # Journal (params at full level only)
    parts["journal"] = [
        {
            "n": n,
            "at": e.get("at"),
            "activity": e.get("activity"),
            "agent": agents(
                (e.get("agent") or {}).get("id", "")
                if isinstance(e.get("agent"), Mapping)
                else ""
            )
            or None,
            "status": e.get("status"),
            "inferred": bool(e.get("inferred")),
            "used": _json_text(e.get("used") or {}),
            "generated": _json_text(e.get("generated") or {}),
            "params": _json_text(e.get("params") or {})
            if level >= LEVELS.index(FULL)
            else None,
            "message": e.get("message") or None,
        }
        for n, e in enumerate(journal_events, 1)
    ]
    sources["journal"] = folder / JOURNAL_FILE
    history, history_codes = [], []
    for n, row in enumerate(_read_jsonl(folder / HISTORY_FILENAME), 1):
        # SX-20: codes added / removed since the previous snapshot, by Zotero key
        for change in ("codes_added", "codes_removed"):
            for pair in row.pop(change, None) or []:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    history_codes.append(
                        {
                            "snapshot": n,
                            "paper": by_zotero.get(str(pair[0]), str(pair[0])),
                            "code": pair[1],
                            "change": "added" if change == "codes_added" else "removed",
                        }
                    )
        history.append(
            {
                "snapshot": n,
                **{
                    k: (_json_text(v) if isinstance(v, (dict, list)) else v)
                    for k, v in row.items()
                },
            }
        )
    parts["annotation_history"], parts["annotation_codes"] = history, history_codes
    sources["annotation_history"] = folder / HISTORY_FILENAME
    sources["annotation_codes"] = folder / HISTORY_FILENAME
    log = paper_log.load(folder)
    parts["paper_log"] = [
        {
            "paper": by_paper_key[k].key if k in by_paper_key else derived_key(k),
            "first_seen": v.get("imported_at"),
            "origin": v.get("origin"),
        }
        for k, v in sorted(log.items())
        if isinstance(v, Mapping)
    ]
    sources["paper_log"] = paper_log.log_path(folder)
    snowball = _read_yaml(folder / "snowball.yml")
    parts["snowball"] = snowball if isinstance(snowball, dict) else {}
    sources["snowball"] = folder / "snowball.yml"

    aggregation = []
    path = collection_dir / "aggregation_stats.csv"
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                value = _text(row.get("value"))
                if value.isdigit():
                    aggregation.append({"stage": row.get("stat"), "count": int(value)})
                elif row.get("stat") == "run_date":
                    aggregation.append(
                        {"stage": "run_date", "at": value.replace(" ", "T")}
                    )
    parts["aggregation"] = aggregation
    sources["aggregation"] = path

    # Corpus columns: scores, venues, metrics, enrichment
    scores, venues, metrics, enrichment = [], [], [], []
    for p in papers:
        row = p.row
        if not row:
            continue
        score = {"paper": p.key}
        for column, name in (
            ("relevance_score", "relevance"),
            ("quality_score", "quality"),
        ):
            number = _number(row.get(column))
            if number is not None:
                score[name] = number
        if len(score) > 1:
            scores.append(score)
        venue = {"paper": p.key}
        if _text(row.get("journalAbbreviation")):
            venue["journal"] = _text(row.get("journalAbbreviation"))
        if issn_of(row.get("serie")):
            venue["issn"] = issn_of(row.get("serie"))
        elif _text(row.get("serie")):
            venue["series"] = _text(row.get("serie"))
        if _text(row.get("conferenceName")):
            venue["conference"] = _text(row.get("conferenceName"))
        if len(venue) > 1:
            venues.append(venue)
        computed_at = _text(row.get("metric_computed_at")) or None
        for column, value in row.items():
            column = str(column)
            if column.startswith(METRIC_PREFIX) and column != "metric_computed_at":
                number = _number(value)
                if number is not None:
                    metrics.append(
                        {
                            "paper": p.key,
                            "metric": column[len(METRIC_PREFIX) :],
                            "value": number,
                            "computed_at": computed_at,
                        }
                    )
            elif column.startswith(ENRICHMENT_PREFIXES) or column in ENRICHMENT_COLUMNS:
                if _text(value):
                    enrichment.append(
                        {"paper": p.key, "column": column, "value": _text(value)}
                    )
    parts["scores"], parts["venues"] = scores, venues
    parts["metrics"], parts["enrichment"] = metrics, enrichment
    for name in ("scores", "venues", "metrics", "enrichment"):
        sources[name] = collection_dir / "aggregated_results.csv"

    source = _read_yaml(folder / "zotero_source.yml")
    parts["zotero"] = (
        {
            k: source.get(k)
            for k in ("library_type", "library_id", "collection_key", "collection_name")
        }
        if isinstance(source, dict)
        else {}
    )
    sources["zotero"] = folder / "zotero_source.yml"
    origin = _read_yaml(folder / "kg_source.yml")
    parts["origin_kg"] = (
        {k: v for k, v in origin.items() if not str(k).endswith(("path", "file"))}
        if isinstance(origin, dict)
        else {}
    )
    sources["origin_kg"] = folder / "kg_source.yml"

    # Manifest (SR2) and disclosure
    manifest, report_parts = [], {}
    for name, (lowest, label) in PARTS.items():
        value = parts.get(name)
        src = sources.get(name) or sources.get(name.rsplit("_", 1)[0])
        rows = len(value) if isinstance(value, (list, dict)) else 0
        if LEVELS.index(lowest) > level:
            status = "withheld"
            parts.pop(name, None)
        elif src is not None and not Path(src).exists() and not rows:
            status = "absent"
        else:
            status = "present" if rows else "empty"
        report_parts[name] = status
        manifest.append(
            {
                "name": name,
                "status": status,
                "file": label,
                "sha256": _sha256(src)
                if src and Path(src).is_file() and status != "withheld"
                else None,
                "rows": rows if status in ("present", "empty") else 0,
            }
        )

    bundle = {
        "schemaVersion": SCHEMA_VERSION,
        "review": {
            "name": review_name,
            "slug": slugify(review_name),
            "base": base_iri or None,
            "owner": owner or None,
            "disclosure": disclosure,
        },
        "generator": {
            "name": _generator(),
            "profile": profile_version_iri or None,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "parts": manifest,
        **parts,
    }
    bundle = scrub(bundle)
    report = BundleReport(
        path=Path(),
        disclosure=disclosure,
        parts=report_parts,
        papers=len(papers),
        unmatched=sum(1 for p in papers if not p.in_bibliography),
        masked=scrub.masked,
    )
    return bundle, report


def _generator() -> str:
    from scilex.kg.build import generator_name

    return generator_name()


def write_bundle(output: Path, *args, **kwargs) -> BundleReport:
    """Write :func:`build_bundle` to ``output`` (``.../survey.json``); return its report."""
    bundle, report = build_bundle(*args, **kwargs)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report.path = output
    return report


# ---------------------------------------------------------------------------
# Secret scan of a graph (SX-14)
# ---------------------------------------------------------------------------

KEY_NAMES = re.compile(
    r"(api[_-]?key|access[_-]?token|bearer\s+[a-z0-9._-]{8,}"
    r"|[?&](api_?key|key|token|access_token)=(?!\*\*\*)[^&\s]{6,})",
    re.I,
)
TOKEN = re.compile(r"(?<![A-Za-z0-9+_-])[A-Za-z0-9+_-]{32,}={0,2}(?![A-Za-z0-9+_-])")
HASH = re.compile(r"^(sha(1|256):)?([0-9a-f]{40}|[0-9a-f]{64})$", re.I)


def _key_like(text: str, iri: bool = False) -> bool:
    if HASH.match(text.strip()):
        return False  # a SHA-1 / SHA-256 hash (configuration versions), not a key
    text = re.sub(
        r"sha256[\"':\s]*[0-9a-f]{64}|sha256%3A[0-9a-f]{64}", "", text, flags=re.I
    )
    if KEY_NAMES.search(text):
        return True
    if iri:  # vocabulary terms and paths: only a key parameter counts
        return False
    for match in TOKEN.finditer(text):
        token = match.group(0)
        mixed = (
            re.search(r"[a-z]", token)
            and re.search(r"[A-Z]", token)
            and re.search(r"\d", token)
        )
        if (
            mixed
            or re.fullmatch(r"[0-9a-f]{32,}", token, re.I)
            and not HASH.match(token)
        ):
            return True
    return False


def find_secrets(graph, secrets: Iterable[str] = ()) -> list[str]:
    """Literals and IRIs of ``graph`` that look like a credential (SR18, CFG7).

    Looks for the values of the keys file, ``api_key`` / ``token`` / ``Bearer``
    texts and long random-looking tokens. A SHA-1 or SHA-256 hash (configuration
    versions) is not a credential.
    """
    from rdflib import Literal, URIRef

    values = [s for s in (str(x).strip() for x in secrets) if len(s) >= 6]
    found = []
    for term in {t for triple in graph for t in triple}:
        if not isinstance(term, (Literal, URIRef)):
            continue
        text = str(term)
        if any(v in text for v in values) or _key_like(text, isinstance(term, URIRef)):
            found.append(text[:120])
    return sorted(found)
