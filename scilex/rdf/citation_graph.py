"""Citation graph of an aggregated collection, serialised as Turtle.

For every DOI of the collection the graph holds:

- ``bibo:cites`` edges to the DOIs it references (from the references already
  fetched by ``scilex-enrich-citations`` or, if missing, fetched on demand);
- optionally the bibliographic Turtle returned by DOI content negotiation
  (``Accept: text/turtle`` on ``https://doi.org/{doi}``, documented at
  https://citation.doi.org/docs.html).

Content negotiation only describes the paper itself, not its citations, hence
the ``bibo:cites`` edges come from the reference fetchers.
"""

import json
import logging
import os
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests
from ratelimit import limits, sleep_and_retry
from rdflib import Graph, URIRef
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from scilex.constants import normalize_doi

from .namespaces import BIBO

logger = logging.getLogger(__name__)

DOI_RESOLVER = "https://doi.org/"
CITATION_GRAPH_FILENAME = "citation_graph.ttl"
TURTLE_CACHE_FILENAME = "doi_turtle_cache.json"
# doi.org tolerates modest parallel use; stay well below 5 req/s.
REQUESTS_PER_SECOND = 3
DEFAULT_WORKERS = 3


class _RetryableDoiError(Exception):
    """Transient failure of the DOI resolver."""


def doi_uri(doi: str) -> URIRef:
    """URI of a DOI, identical to the one minted by the BibTeX converter."""
    return URIRef(f"{DOI_RESOLVER}{urllib.parse.quote(doi, safe='/')}")


@sleep_and_retry
@limits(calls=REQUESTS_PER_SECOND, period=1)
def _rate_limited_get(url: str, headers: dict) -> requests.Response:
    return requests.get(url, headers=headers, timeout=30, allow_redirects=True)


@retry(
    retry=retry_if_exception_type(_RetryableDoiError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def fetch_doi_turtle(doi: str, mailto: str | None = None) -> str | None:
    """Fetch the Turtle description of a DOI via content negotiation.

    Returns:
        Turtle text, or None when the registration agency has no Turtle for it.
    """
    headers = {"Accept": "text/turtle"}
    if mailto:
        headers["User-Agent"] = f"SciLEx (mailto:{mailto})"
    try:
        response = _rate_limited_get(doi_uri(doi), headers)
    except requests.exceptions.RequestException as error:
        raise _RetryableDoiError(str(error)) from error
    if response.status_code == 429 or response.status_code >= 500:
        raise _RetryableDoiError(f"HTTP {response.status_code}")
    if response.status_code != 200:
        return None
    return response.text


class _TurtleCache:
    """Thread-safe JSON cache {doi: turtle text or ""}."""

    def __init__(self, path: str | None):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    self._data = json.load(handle)
            except (json.JSONDecodeError, OSError) as error:
                logger.warning(f"Could not load cache {path}: {error}")

    def get(self, doi: str) -> str | None:
        with self._lock:
            return self._data.get(doi)

    def set(self, doi: str, turtle: str) -> None:
        with self._lock:
            self._data[doi] = turtle

    def save(self) -> None:
        if not self.path:
            return
        with self._lock:
            temporary_path = f"{self.path}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle)
            os.replace(temporary_path, self.path)


def build_citation_graph(
    dois: list[str],
    references: dict[str, list[str]],
    cache_path: str | None = None,
    include_doi_metadata: bool = True,
    mailto: str | None = None,
    workers: int = DEFAULT_WORKERS,
) -> Graph:
    """Build the citation graph of ``dois``.

    Args:
        dois: DOIs of the collection.
        references: ``{doi: [cited_dois]}`` mapping.
        cache_path: JSON cache of the DOI Turtle responses (None disables it).
        include_doi_metadata: Also merge the content-negotiated Turtle.
        mailto: Contact e-mail for the User-Agent (polite usage).
        workers: Parallel DOI requests.

    Returns:
        rdflib Graph with ``bibo:cites`` edges (and DOI metadata if requested).
    """
    graph = Graph()
    graph.bind("bibo", BIBO)
    normalized = [d for d in dict.fromkeys(normalize_doi(x) for x in dois) if d]

    for doi in normalized:
        for cited in references.get(doi, []):
            cited_doi = normalize_doi(cited)
            if cited_doi:
                graph.add((doi_uri(doi), BIBO.cites, doi_uri(cited_doi)))

    if include_doi_metadata:
        cache = _TurtleCache(cache_path)
        pending = [d for d in normalized if cache.get(d) is None]
        logger.info(
            f"DOI Turtle: {len(normalized) - len(pending)} cached, "
            f"{len(pending)} to fetch"
        )

        def fetch(doi: str) -> None:
            try:
                turtle = fetch_doi_turtle(doi, mailto)
            except _RetryableDoiError as error:
                logger.warning(f"DOI Turtle failed for {doi}: {error}")
                return
            cache.set(doi, turtle or "")

        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            list(executor.map(fetch, pending))
        cache.save()

        for doi in normalized:
            turtle = cache.get(doi)
            if not turtle:
                continue
            try:
                graph.parse(data=turtle, format="turtle")
            except Exception as error:
                logger.warning(f"Unparsable Turtle for {doi}: {error}")
    return graph


def write_citation_graph(
    dois: list[str],
    collect_dir: str,
    references: dict[str, list[str]],
    include_doi_metadata: bool = True,
    mailto: str | None = None,
) -> str:
    """Build the graph and write ``citation_graph.ttl`` in ``collect_dir``."""
    graph = build_citation_graph(
        dois,
        references,
        cache_path=os.path.join(collect_dir, TURTLE_CACHE_FILENAME),
        include_doi_metadata=include_doi_metadata,
        mailto=mailto,
    )
    output_path = os.path.join(collect_dir, CITATION_GRAPH_FILENAME)
    graph.serialize(destination=output_path, format="turtle")
    logger.info(f"Citation graph: {len(graph)} triples -> {output_path}")
    return output_path
