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
- **GitHub** (``api.github.com/repos/{owner}/{repo}``, by the GitHub repositories
  the other sources found): licence of the code (SPDX id) and the repository.
- **Zenodo** (``zenodo.org/api/records``): the deposits of a paper's data or
  code -- records it links to (Zenodo DOI or link in its DOI, URL or abstract)
  and records naming its DOI among their related identifiers -- with their
  licence, type (dataset, software…), size and downloads.
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
    "lpwc_paper",
    "lpwc_tasks",
    "lpwc_methods",
    "lpwc_datasets",
    "lpwc_repositories",
    "lpwc_conference",
)
ORKG_COLUMNS = ("orkg_paper", "orkg_research_fields", "orkg_research_problems")
GITHUB_API = "https://api.github.com/repos/{repo}"
GITHUB_COLUMNS = ("code_license", "code_repository")
ZENODO_API = "https://zenodo.org/api"
ZENODO_COLUMNS = (
    "zenodo_records",
    "zenodo_dois",
    "zenodo_license",
    "zenodo_types",
    "zenodo_size",
    "zenodo_downloads",
)
# Columns holding the code repositories of a paper (Papers with Code, LPWC).
REPOSITORY_COLUMNS = ("github_repo", "pwc_repository", "lpwc_repositories")


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
    kept: int = 0  # papers already enriched, left as they are (GitHub)
    candidates: int | None = None  # papers that could be looked up (GitHub)
    rate_limited: bool = False

    def message(self) -> str:
        if self.source == "GitHub" and not self.candidates and not self.kept:
            return (
                "GitHub: no paper has a GitHub repository yet: run Papers with Code "
                "or Linked Papers With Code first."
            )
        if self.source == "GitHub":
            text = (
                f"GitHub: licence found for {self.found} of {self.looked_up} papers "
                "with a repository"
            )
        elif self.source == "Zenodo":
            text = f"Zenodo: deposits found for {self.found} of {self.looked_up} papers"
        else:
            text = f"{self.source}: {self.found} of {self.looked_up} papers found"
        if self.kept:
            text += f", {self.kept} already enriched (kept)"
        if self.filled:
            text += f", {self.filled} empty fields filled"
        if self.rate_limited:
            text += (
                f"; {self.source} refused more requests for now, {self.failed} "
                f"papers left for a later run (a {self.source} token in Keys "
                "raises the limit)"
            )
        elif self.failed:
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
    return not is_valid(value) or str(value).strip() in (
        "",
        MISSING_VALUE,
        "nan",
        "None",
    )


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


def crossref_record(
    doi: str, session: requests.Session, mailto: str | None = None
) -> dict | None:
    """Return the Crossref ``message`` of ``doi`` ({} when unknown, None on failure)."""
    params = {"mailto": mailto} if mailto else None
    try:
        response = session.get(
            CROSSREF_WORKS.format(doi=doi), params=params, timeout=TIMEOUT
        )
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
    date = "-".join(
        f"{part:02d}" if i else str(part) for i, part in enumerate(issued[0] or [])
    )
    abstract = message.get("abstract")
    licence = first("license") or {}
    fields = {
        "abstract": re.sub(r"\s+", " ", _JATS.sub(" ", abstract)).strip()
        if abstract
        else "",
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
    todo = [
        (index, _doi(row))
        for index, row in zip(rows.index, rows.to_dict("records"), strict=True)
    ]
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
            progress(
                int(100 * count / max(len(todo), 1)), f"Crossref: {count}/{len(todo)}"
            )
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
    return json.dumps(
        text
    )  # a valid SPARQL string literal (escapes quotes, backslashes)


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
        "?paper fabio:hasArXivId ?key ."
        if by == "arxiv"
        else "?paper dcterms:title ?key ."
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
            value = (b.get("label") or {}).get("value") or b["o"]["value"].rsplit(
                "/", 1
            )[-1]
            if column == "lpwc_repositories":
                value = b["o"]["value"].split("/repository/", 1)[-1]
            entry.setdefault(column, []).append(value)
    return {
        key: {col: _join(vals) for col, vals in cols.items()}
        for key, cols in found.items()
    }


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
            found = _orkg_get(
                session, "/papers", {"doi": doi, "size": 1}, ORKG_PAPER_MEDIA
            )
            paper = next(iter(found.get("content") or []), None)
        if paper is None and title:
            found = _orkg_get(
                session,
                "/papers",
                {"title": title, "exact": "true", "size": 1},
                ORKG_PAPER_MEDIA,
            )
            paper = next(iter(found.get("content") or []), None)
        if paper is None:
            return {}
        problems = []
        for contribution in paper.get("contributions") or []:
            statements = _orkg_get(
                session,
                "/statements",
                {
                    "subject_id": contribution["id"],
                    "predicate_id": ORKG_RESEARCH_PROBLEM,
                },
            )
            problems += [s["object"]["label"] for s in statements.get("content") or []]
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.warning("ORKG lookup failed for %s: %s", doi or title, exc)
        return None
    return {
        "orkg_paper": f"https://orkg.org/paper/{paper['id']}",
        "orkg_research_fields": _join(
            f.get("label") for f in paper.get("research_fields") or []
        ),
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


# ---------------------------------------------------------------------------
# GitHub (licence of the code)
# ---------------------------------------------------------------------------

_GITHUB_REPO = re.compile(
    r"github\.com[/:]+(?P<owner>[A-Za-z0-9][A-Za-z0-9\-]*)/(?P<name>[A-Za-z0-9_.\-]+)",
    re.IGNORECASE,
)
_NOT_REPOSITORIES = {"orgs", "topics", "features", "sponsors", "marketplace", "about"}


class RateLimited(Exception):
    """GitHub refused more requests for now (60 an hour without a token)."""


def github_repositories(row: dict) -> list[str]:
    """``owner/name`` of the GitHub repositories given for a paper, in order."""
    found: list[str] = []
    for column in REPOSITORY_COLUMNS:
        value = row.get(column)
        if _missing(value):
            continue
        for match in _GITHUB_REPO.finditer(str(value)):
            owner = match.group("owner")
            name = match.group("name").removesuffix(".git").rstrip(".")
            if owner.lower() in _NOT_REPOSITORIES or not name:
                continue
            repo = f"{owner}/{name}"
            if repo.lower() not in (r.lower() for r in found):
                found.append(repo)
    return found


def github_record(repo: str, session: requests.Session, token: str | None = None):
    """``{"code_license", "code_repository"}`` of ``repo``; {} if it is gone.

    Returns None when GitHub could not answer (retried next run).

    Raises:
        RateLimited: No more requests allowed for now.
    """
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = session.get(
            GITHUB_API.format(repo=repo), headers=headers, timeout=TIMEOUT
        )
    except requests.RequestException as exc:
        logger.warning("GitHub request failed for %s: %s", repo, exc)
        return None
    remaining = (getattr(response, "headers", None) or {}).get("X-RateLimit-Remaining")
    if response.status_code == 429 or (
        response.status_code == 403 and remaining == "0"
    ):
        raise RateLimited
    if response.status_code in (404, 451):
        return {}
    if not response.ok:
        logger.warning("GitHub answered %s for %s", response.status_code, repo)
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    licence = payload.get("license") or {}
    spdx = licence.get("spdx_id")
    if spdx in (None, "", "NOASSERTION"):
        spdx = licence.get("name") or ""  # "Other": a licence GitHub cannot name
    return {
        "code_license": spdx or "",
        "code_repository": payload.get("html_url") or f"https://github.com/{repo}",
    }


def enrich_github(
    data: pd.DataFrame,
    cache_path: Path,
    *,
    row_filter: RowFilter | None = None,
    limit: int | None = None,
    progress: ProgressFn = lambda p, m: None,
    cancel: threading.Event | None = None,
    session: requests.Session | None = None,
    token: str | None = None,
) -> EnrichmentReport:
    """Add ``code_license`` and ``code_repository`` from the papers' GitHub repositories.

    Only papers with a GitHub repository (``github_repo``, ``pwc_repository``,
    ``lpwc_repositories``: run Papers with Code or LPWC first) and no
    ``code_license`` yet are looked up; a licence already there is never
    changed. A paper with several repositories takes the first licensed one.
    """
    session = session or _session()
    report = EnrichmentReport("GitHub", columns=list(GITHUB_COLUMNS))
    _ensure_columns(data, GITHUB_COLUMNS)
    cache = _load_cache(cache_path)
    rows = _selected(data, row_filter, None)
    todo = []
    for index, row in zip(rows.index, rows.to_dict("records"), strict=True):
        if not _missing(row.get("code_license")):
            report.kept += 1
            continue
        repos = github_repositories(row)
        if repos:
            todo.append((index, repos))
    if limit:
        todo = todo[:limit]
    report.candidates = len(todo)
    try:
        for count, (index, repos) in enumerate(todo, 1):
            _check(cancel)
            answers = []
            failed = False
            for repo in repos:
                key = repo.lower()
                if key not in cache:
                    record = github_record(repo, session, token)
                    if record is None:
                        failed = True
                        continue
                    cache[key] = record
                    if count % 20 == 0:
                        _save_cache(cache_path, cache)
                answers.append(cache[key])
                if cache[key].get("code_license"):
                    break
            if failed and not answers:
                report.failed += 1
                continue
            report.looked_up += 1
            licensed = next((a for a in answers if a.get("code_license")), None)
            chosen = licensed or next((a for a in answers if a), None)
            if licensed:
                report.found += 1
                data.at[index, "code_license"] = licensed["code_license"]
            if chosen and _missing(data.at[index, "code_repository"]):
                data.at[index, "code_repository"] = chosen["code_repository"]
            progress(
                int(100 * count / max(len(todo), 1)), f"GitHub: {count}/{len(todo)}"
            )
    except RateLimited:
        report.rate_limited = True
        report.failed = len(todo) - report.looked_up
    finally:
        _save_cache(cache_path, cache)
    return report


# ---------------------------------------------------------------------------
# Zenodo (datasets and software deposited with a paper)
# ---------------------------------------------------------------------------

_ZENODO_ID = re.compile(
    r"(?:10\.5281/zenodo\.|zenodo\.org/(?:records?|deposit|doi/10\.5281/zenodo\.)/?)(\d+)",
    re.IGNORECASE,
)
# Where a paper may give its Zenodo deposit.
ZENODO_SOURCE_COLUMNS = ("DOI", "url", "pdf_url", "abstract", "extra", "github_repo")


def zenodo_ids(row: dict) -> list[str]:
    """Zenodo record ids the paper gives (Zenodo DOI, link in its URL or abstract)."""
    found: list[str] = []
    for column in ZENODO_SOURCE_COLUMNS:
        value = row.get(column)
        if _missing(value):
            continue
        for match in _ZENODO_ID.finditer(str(value)):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found


def _zenodo_get(session, path, params, token):
    """GET ``ZENODO_API + path``; waits once when Zenodo asks to slow down.

    Raises:
        RateLimited: Zenodo still refuses after the wait.
    """
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(2):
        response = session.get(
            ZENODO_API + path, params=params, headers=headers, timeout=TIMEOUT
        )
        if response.status_code != 429:
            return response
        if attempt == 0:
            wait = (getattr(response, "headers", None) or {}).get("Retry-After")
            time.sleep(min(float(wait or 10), 60))
    raise RateLimited


def zenodo_summary(record: dict) -> dict:
    """What SciLEx keeps of a Zenodo record."""
    metadata = record.get("metadata") or {}
    licence = metadata.get("license") or {}
    licence = licence.get("id") if isinstance(licence, dict) else str(licence)
    resource = metadata.get("resource_type") or {}
    kind = resource.get("type") or resource.get("title") or ""
    files = record.get("files") or []
    size = sum(int(f.get("size") or 0) for f in files if isinstance(f, dict))
    stats = record.get("stats") or {}
    doi = record.get("doi") or metadata.get("doi") or ""
    return {
        "id": str(record.get("id") or record.get("recid") or ""),
        "doi": doi,
        "url": (record.get("links") or {}).get("html")
        or f"https://zenodo.org/records/{record.get('id')}",
        "license": licence or "",
        "type": kind,
        "size": size,
        "downloads": int(stats.get("unique_downloads") or stats.get("downloads") or 0),
    }


def zenodo_lookup(
    ids: list[str], doi: str | None, session, token: str | None = None
) -> list[dict] | None:
    """Zenodo records of a paper: those it gives, plus those citing its DOI.

    A record whose related identifiers include the paper's DOI (``isSupplementTo``,
    ``isDocumentedBy``…) is the deposit of its data or code. Returns None when
    Zenodo could not be reached (retried next run).
    """
    records: dict[str, dict] = {}
    try:
        for record_id in ids:
            response = _zenodo_get(session, f"/records/{record_id}", None, token)
            if response.status_code in (404, 410):
                continue
            response.raise_for_status()
            summary = zenodo_summary(response.json())
            records[summary["id"]] = summary
        if doi and not doi.startswith("10.5281/zenodo."):
            response = _zenodo_get(
                session,
                "/records",
                {
                    "q": f'metadata.related_identifiers.identifier:"{doi}"',
                    "size": 25,
                    "all_versions": "false",
                },
                token,
            )
            response.raise_for_status()
            for hit in (response.json().get("hits") or {}).get("hits") or []:
                summary = zenodo_summary(hit)
                records.setdefault(summary["id"], summary)
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        logger.warning("Zenodo request failed (%s, %s): %s", ids, doi, exc)
        return None
    return list(records.values())


def _size(total: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if total < 1000 or unit == "TB":
            return f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
        total /= 1000
    return ""


def zenodo_fields(records: list[dict]) -> dict[str, str]:
    """The zenodo_* cells of a paper from its records."""
    return {
        "zenodo_records": _join(r["url"] for r in records),
        "zenodo_dois": _join(r["doi"] for r in records),
        "zenodo_license": _join(r["license"] for r in records),
        "zenodo_types": _join(r["type"] for r in records),
        "zenodo_size": _size(sum(r["size"] for r in records))
        if any(r["size"] for r in records)
        else MISSING_VALUE,
        "zenodo_downloads": str(sum(r["downloads"] for r in records))
        if records
        else MISSING_VALUE,
    }


def enrich_zenodo(
    data: pd.DataFrame,
    cache_path: Path,
    *,
    row_filter: RowFilter | None = None,
    limit: int | None = None,
    progress: ProgressFn = lambda p, m: None,
    cancel: threading.Event | None = None,
    session: requests.Session | None = None,
    token: str | None = None,
) -> EnrichmentReport:
    """Add the zenodo_* columns: records, DOIs, licences, types, size, downloads.

    Papers whose ``zenodo_records`` is already filled are left as they are. A
    software record also gives ``code_license`` when that cell is empty.
    """
    session = session or _session()
    report = EnrichmentReport("Zenodo", columns=list(ZENODO_COLUMNS))
    _ensure_columns(data, ZENODO_COLUMNS)
    _ensure_columns(data, ("code_license",))
    cache = _load_cache(cache_path)
    rows = _selected(data, row_filter, None)
    todo = []
    for index, row in zip(rows.index, rows.to_dict("records"), strict=True):
        if not _missing(row.get("zenodo_records")):
            report.kept += 1
            continue
        ids, doi = zenodo_ids(row), _doi(row)
        if ids or doi:
            todo.append((index, ids, doi))
    if limit:
        todo = todo[:limit]
    try:
        for count, (index, ids, doi) in enumerate(todo, 1):
            _check(cancel)
            key = f"{doi or ''}|{','.join(ids)}"
            if key not in cache:
                records = zenodo_lookup(ids, doi, session, token)
                if records is None:
                    report.failed += 1
                    continue
                cache[key] = records
                if count % 20 == 0:
                    _save_cache(cache_path, cache)
            report.looked_up += 1
            records = cache[key]
            if records:
                report.found += 1
                for column, value in zenodo_fields(records).items():
                    data.at[index, column] = value
                software = [r for r in records if r["type"] == "software"]
                licences = _join(r["license"] for r in software)
                if licences != MISSING_VALUE and _missing(
                    data.at[index, "code_license"]
                ):
                    data.at[index, "code_license"] = licences
            progress(
                int(100 * count / max(len(todo), 1)), f"Zenodo: {count}/{len(todo)}"
            )
    except RateLimited:
        report.rate_limited = True
        report.failed = len(todo) - report.looked_up
    finally:
        _save_cache(cache_path, cache)
    return report


ENRICHERS = {
    "crossref": enrich_crossref,
    "lpwc": enrich_lpwc,
    "orkg": enrich_orkg,
    "github": enrich_github,
    "zenodo": enrich_zenodo,
}
