"""Enrich aggregated papers from open scholarly sources: Crossref, LPWC, ORKG.

Each enricher reads ``aggregated_results.csv``, looks up the papers (all, or
those a ``row_filter`` keeps), writes what it found in its own columns, fills
missing bibliographic fields (Crossref only fills empty cells, never overwrites)
and writes the file back. Answers are cached per review (``<source>_cache.json``)
so a rerun only asks for papers not looked up yet.

- **Crossref** (``api.crossref.org/works/{doi}``, by DOI): abstract, venue,
  volume, issue, pages, date, publisher, language, licence, ISSN, type,
  citation count, funders.
- **Linked Papers With Code** (SPARQL ``linkedpaperswithcode.com/sparql``, by
  arXiv id, else exact title): tasks, methods, datasets, repositories,
  conference -- the LPWC terms the scilex-lpwc-ap profile reuses.
- **ORKG** (``orkg.org/api``, by DOI, else exact title): ORKG paper, research
  fields and research problems of its contributions.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

from scilex.constants import MISSING_VALUE, is_valid, normalize_doi

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int, str], None]
RowFilter = Callable[[pd.DataFrame], pd.DataFrame]

CROSSREF_WORKS = "https://api.crossref.org/works/{doi}"
LPWC_SPARQL = "https://linkedpaperswithcode.com/sparql"
ORKG_API = "https://orkg.org/api"
ORKG_PAPER_MEDIA = "application/vnd.orkg.paper.v2+json"
ORKG_RESEARCH_PROBLEM = "P32"
USER_AGENT = "SciLEx (systematic literature review toolkit)"
TIMEOUT = 30
LPWC_BATCH = 40

CROSSREF_COLUMNS = ("crossref_type", "crossref_cited_by", "crossref_funders", "issn")
LPWC_COLUMNS = (
    "lpwc_paper", "lpwc_tasks", "lpwc_methods", "lpwc_datasets",
    "lpwc_repositories", "lpwc_conference",
)
ORKG_COLUMNS = ("orkg_paper", "orkg_research_fields", "orkg_research_problems")


class Cancelled(Exception):
    """The run was cancelled between two papers."""


@dataclass
class EnrichmentReport:
    """What a run did."""

    source: str
    looked_up: int = 0
    found: int = 0
    filled: int = 0  # bibliographic cells filled (Crossref)
    failed: int = 0
    output: Path | None = None
    columns: list[str] = field(default_factory=list)

    def message(self) -> str:
        text = f"{self.source}: {self.found} of {self.looked_up} papers found"
        if self.filled:
            text += f", {self.filled} empty fields filled"
        if self.failed:
            text += f", {self.failed} requests failed (rerun to retry them)"
        return text + "."


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def _missing(value) -> bool:
    return not is_valid(value) or str(value).strip() in ("", MISSING_VALUE, "nan", "None")


def _doi(row: dict) -> str | None:
    value = row.get("DOI")
    return normalize_doi(value) if is_valid(value) else None


ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?", re.I)


def arxiv_id(row: dict) -> str | None:
    """Return the arXiv id of a paper (DOI 10.48550/arXiv.X, an arXiv URL or eprint)."""
    doi = _doi(row) or ""
    if doi.startswith("10.48550/arxiv."):
        return doi.removeprefix("10.48550/arxiv.")
    for column in ("url", "eprint", "archiveID", "pdf_url"):
        value = str(row.get(column) or "")
        if "arxiv" in value.lower() or column == "eprint":
            match = ARXIV_ID.search(value)
            if match:
                return match.group(1)
    return None


def _load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled


def _selected(data: pd.DataFrame, row_filter: RowFilter | None, limit: int | None):
    rows = row_filter(data) if row_filter is not None else data
    return rows.head(limit) if limit else rows


def _ensure_columns(data: pd.DataFrame, columns) -> None:
    for column in columns:
        if column not in data.columns:
            data[column] = MISSING_VALUE


def _join(values) -> str:
    return ";".join(dict.fromkeys(v for v in values if v)) or MISSING_VALUE


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------

_JATS = re.compile(r"<[^>]+>")


def crossref_record(doi: str, session: requests.Session, mailto: str | None = None) -> dict | None:
    """Return the Crossref ``message`` of ``doi`` ({} when unknown, None on failure)."""
    params = {"mailto": mailto} if mailto else None
    try:
        response = session.get(CROSSREF_WORKS.format(doi=doi), params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Crossref %s: %s", doi, exc)
        return None
    if response.status_code == 404:
        return {}
    if response.status_code == 429:
        time.sleep(5)
        return None
    if not response.ok:
        logger.warning("Crossref %s: HTTP %s", doi, response.status_code)
        return None
    return response.json().get("message") or {}


def crossref_fields(message: dict) -> dict[str, str]:
    """Map a Crossref record to SciLEx columns (bibliographic + crossref_*)."""
    if not message:
        return {}

    def first(key):
        value = message.get(key)
        return value[0] if isinstance(value, list) and value else value

    issued = (message.get("issued") or {}).get("date-parts") or [[]]
    date = "-".join(f"{part:02d}" if i else str(part) for i, part in enumerate(issued[0] or []))
    abstract = message.get("abstract")
    licence = first("license") or {}
    fields = {
        "abstract": re.sub(r"\s+", " ", _JATS.sub(" ", abstract)).strip() if abstract else "",
        "journalAbbreviation": first("container-title") or "",
        "publisher": message.get("publisher") or "",
        "volume": message.get("volume") or "",
        "issue": message.get("issue") or "",
        "pages": message.get("page") or "",
        "date": date,
        "language": message.get("language") or "",
        "rights": licence.get("URL", "") if isinstance(licence, dict) else "",
        "issn": first("ISSN") or "",
        "crossref_type": message.get("type") or "",
        "crossref_cited_by": str(message.get("is-referenced-by-count", "")),
        "crossref_funders": _join(f.get("name") for f in message.get("funder") or []),
    }
    return {k: v for k, v in fields.items() if v and v != MISSING_VALUE}


def enrich_crossref(
    data: pd.DataFrame,
    cache_path: Path,
    *,
    mailto: str | None = None,
    row_filter: RowFilter | None = None,
    limit: int | None = None,
    progress: ProgressFn = lambda p, m: None,
    cancel: threading.Event | None = None,
    session: requests.Session | None = None,
) -> EnrichmentReport:
    """Fill empty bibliographic fields and add crossref_* columns, by DOI."""
    session = session or _session()
    report = EnrichmentReport("Crossref", columns=list(CROSSREF_COLUMNS))
    _ensure_columns(data, CROSSREF_COLUMNS)
    cache = _load_cache(cache_path)
    rows = _selected(data, row_filter, limit)
    todo = [(index, _doi(row)) for index, row in zip(rows.index, rows.to_dict("records"), strict=True)]
    todo = [(index, doi) for index, doi in todo if doi]
    try:
        for count, (index, doi) in enumerate(todo, 1):
            _check(cancel)
            if doi not in cache:
                record = crossref_record(doi, session, mailto)
                if record is None:
                    report.failed += 1
                    continue
                cache[doi] = crossref_fields(record)
                if count % 20 == 0:
                    _save_cache(cache_path, cache)
            report.looked_up += 1
            found = cache.get(doi) or {}
            if found:
                report.found += 1
            for column, value in found.items():
                if column not in data.columns:
                    data[column] = MISSING_VALUE
                if column in CROSSREF_COLUMNS:
                    data.at[index, column] = value
                elif _missing(data.at[index, column]):
                    data.at[index, column] = value
                    report.filled += 1
            progress(int(100 * count / max(len(todo), 1)), f"Crossref: {count}/{len(todo)}")
    finally:
        _save_cache(cache_path, cache)
    return report


# ---------------------------------------------------------------------------
# Linked Papers With Code
# ---------------------------------------------------------------------------

_LPWC_PROPS = {
    "hasTask": "lpwc_tasks",
    "hasMethod": "lpwc_methods",
    "usesDataset": "lpwc_datasets",
    "hasOfficialRepository": "lpwc_repositories",
    "hasConference": "lpwc_conference",
}


def _literal(text: str) -> str:
    return json.dumps(text)  # a valid SPARQL string literal (escapes quotes, backslashes)


def _lpwc_query(match_clause: str, values: list[str]) -> str:
    rows = " ".join(_literal(v) for v in values)
    props = ", ".join(f"lpwcp:{p}" for p in _LPWC_PROPS)
    return f"""
PREFIX lpwcp: <https://linkedpaperswithcode.com/property/>
PREFIX fabio: <http://purl.org/spar/fabio/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
SELECT ?key ?paper ?p ?o ?label WHERE {{
  VALUES ?key {{ {rows} }}
  {match_clause}
  OPTIONAL {{
    ?paper ?p ?o .
    FILTER(?p IN ({props}))
    OPTIONAL {{ ?o foaf:name ?label }}
  }}
}}"""


def lpwc_lookup(
    keys: list[str], by: str, session: requests.Session
) -> dict[str, dict[str, str]] | None:
    """Look up papers on LPWC by ``arxiv`` id or exact ``title``; None on failure."""
    clause = (
        "?paper fabio:hasArXivId ?key ." if by == "arxiv" else "?paper dcterms:title ?key ."
    )
    try:
        response = session.post(
            LPWC_SPARQL,
            data={"query": _lpwc_query(clause, keys)},
            headers={"Accept": "application/sparql-results+json"},
            timeout=TIMEOUT * 3,
        )
        response.raise_for_status()
        bindings = response.json()["results"]["bindings"]
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.warning("LPWC lookup failed: %s", exc)
        return None
    found: dict[str, dict[str, list[str]]] = {}
    for b in bindings:
        key = b["key"]["value"]
        entry = found.setdefault(key, {"lpwc_paper": [b["paper"]["value"]]})
        if "p" in b:
            column = _LPWC_PROPS[b["p"]["value"].rsplit("/", 1)[-1]]
            value = (b.get("label") or {}).get("value") or b["o"]["value"].rsplit("/", 1)[-1]
            if column == "lpwc_repositories":
                value = b["o"]["value"].split("/repository/", 1)[-1]
            entry.setdefault(column, []).append(value)
    return {key: {col: _join(vals) for col, vals in cols.items()} for key, cols in found.items()}


def enrich_lpwc(
    data: pd.DataFrame,
    cache_path: Path,
    *,
    row_filter: RowFilter | None = None,
    limit: int | None = None,
    progress: ProgressFn = lambda p, m: None,
    cancel: threading.Event | None = None,
    session: requests.Session | None = None,
) -> EnrichmentReport:
    """Add lpwc_* columns (tasks, methods, datasets...) by arXiv id, else exact title."""
    session = session or _session()
    report = EnrichmentReport("Linked Papers With Code", columns=list(LPWC_COLUMNS))
    _ensure_columns(data, LPWC_COLUMNS)
    cache = _load_cache(cache_path)
    rows = _selected(data, row_filter, limit)
    wanted = []  # (index, cache key, lookup kind, lookup value)
    for index, row in zip(rows.index, rows.to_dict("records"), strict=True):
        arxiv = arxiv_id(row)
        title = str(row.get("title") or "").strip()
        if arxiv:
            wanted.append((index, f"arxiv:{arxiv}", "arxiv", arxiv))
        elif title and not _missing(title):
            wanted.append((index, f"title:{title}", "title", title))
    pending = {kind: [] for kind in ("arxiv", "title")}
    for _, key, kind, value in wanted:
        if key not in cache and value not in pending[kind]:
            pending[kind].append(value)
    total = sum(len(v) for v in pending.values())
    done = 0
    try:
        for kind, values in pending.items():
            for start in range(0, len(values), LPWC_BATCH):
                _check(cancel)
                chunk = values[start : start + LPWC_BATCH]
                answers = lpwc_lookup(chunk, kind, session)
                if answers is None:
                    report.failed += len(chunk)
                    continue
                for value in chunk:
                    cache[f"{kind}:{value}"] = answers.get(value, {})
                _save_cache(cache_path, cache)
                done += len(chunk)
                progress(int(100 * done / max(total, 1)), f"LPWC: {done}/{total}")
        for index, key, _, _ in wanted:
            if key not in cache:
                continue
            report.looked_up += 1
            found = cache[key]
            if found:
                report.found += 1
            for column, value in found.items():
                data.at[index, column] = value
    finally:
        _save_cache(cache_path, cache)
    return report


# ---------------------------------------------------------------------------
# ORKG
# ---------------------------------------------------------------------------


def _orkg_get(session, path, params=None, media="application/json"):
    response = session.get(
        f"{ORKG_API}{path}", params=params, headers={"Accept": media}, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def orkg_record(doi: str | None, title: str | None, session) -> dict | None:
    """Return the ORKG columns of a paper ({} when not in ORKG, None on failure)."""
    try:
        paper = None
        if doi:
            found = _orkg_get(session, "/papers", {"doi": doi, "size": 1}, ORKG_PAPER_MEDIA)
            paper = next(iter(found.get("content") or []), None)
        if paper is None and title:
            found = _orkg_get(
                session, "/papers", {"title": title, "exact": "true", "size": 1}, ORKG_PAPER_MEDIA
            )
            paper = next(iter(found.get("content") or []), None)
        if paper is None:
            return {}
        problems = []
        for contribution in paper.get("contributions") or []:
            statements = _orkg_get(
                session,
                "/statements",
                {"subject_id": contribution["id"], "predicate_id": ORKG_RESEARCH_PROBLEM},
            )
            problems += [s["object"]["label"] for s in statements.get("content") or []]
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.warning("ORKG lookup failed for %s: %s", doi or title, exc)
        return None
    return {
        "orkg_paper": f"https://orkg.org/paper/{paper['id']}",
        "orkg_research_fields": _join(f.get("label") for f in paper.get("research_fields") or []),
        "orkg_research_problems": _join(problems),
    }


def enrich_orkg(
    data: pd.DataFrame,
    cache_path: Path,
    *,
    row_filter: RowFilter | None = None,
    limit: int | None = None,
    progress: ProgressFn = lambda p, m: None,
    cancel: threading.Event | None = None,
    session: requests.Session | None = None,
) -> EnrichmentReport:
    """Add orkg_* columns (paper, research fields, research problems), by DOI else title."""
    session = session or _session()
    report = EnrichmentReport("ORKG", columns=list(ORKG_COLUMNS))
    _ensure_columns(data, ORKG_COLUMNS)
    cache = _load_cache(cache_path)
    rows = _selected(data, row_filter, limit)
    todo = []
    for index, row in zip(rows.index, rows.to_dict("records"), strict=True):
        doi = _doi(row)
        title = None if _missing(row.get("title")) else str(row.get("title")).strip()
        if doi or title:
            todo.append((index, f"doi:{doi}" if doi else f"title:{title}", doi, title))
    try:
        for count, (index, key, doi, title) in enumerate(todo, 1):
            _check(cancel)
            if key not in cache:
                record = orkg_record(doi, title, session)
                if record is None:
                    report.failed += 1
                    continue
                cache[key] = record
                if count % 20 == 0:
                    _save_cache(cache_path, cache)
            report.looked_up += 1
            found = cache[key]
            if found:
                report.found += 1
            for column, value in found.items():
                data.at[index, column] = value
            progress(int(100 * count / max(len(todo), 1)), f"ORKG: {count}/{len(todo)}")
    finally:
        _save_cache(cache_path, cache)
    return report


ENRICHERS = {"crossref": enrich_crossref, "lpwc": enrich_lpwc, "orkg": enrich_orkg}
