"""Citation and quality metrics of each paper, computed once and kept with it.

From a citation network (``{doi: [dois]}`` references and citers, e.g. the
Zotero snapshot of :mod:`scilex.gui.services.zotero_citations`) and the
paper's own columns, this module computes:

==========================  ==================================================
column                      meaning
==========================  ==================================================
``metric_citations``        citing papers known for the paper
``metric_references``       papers it cites
``metric_citations_year``   citations per year since publication (IF2 criterion)
``metric_cited_in_corpus``  papers of the review that cite it
``metric_cites_in_corpus``  papers of the review it cites
``metric_pagerank``         PageRank in the review's citation graph (0-1)
``metric_quality``          SciLEx quality score of the metadata (if computed)
``metric_venue_rank``       CORE / SJR venue rank (if computed)
``metric_computed_at``      date of the computation (the network it used)
==========================  ==================================================

and the matching annotation tags, in the ``DIMENSION:value`` style of the
annotation grid, counts as orders of magnitude like the grid's quantities
(``CITATIONS:10^2`` means 100-999): ``CITATIONS``, ``REFERENCES``,
``CITATIONS_PER_YEAR``, ``CITED_IN_CORPUS``, ``PAGERANK`` (top 1/5/10/25 % or
other), ``QUALITY`` (0-100 by tens), ``VENUE_RANK``. Tags of these dimensions
are replaced at each computation; other tags are left alone.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

from scilex.constants import extract_year, is_valid, normalize_doi

METRIC_DIMENSIONS = (
    "CITATIONS",
    "REFERENCES",
    "CITATIONS_PER_YEAR",
    "CITED_IN_CORPUS",
    "PAGERANK",
    "QUALITY",
    "VENUE_RANK",
)
VENUE_COLUMNS = ("venue_rank", "core_rank", "sjr_quartile")


def magnitude(count: float | None) -> str | None:
    """Order of magnitude of a count: 0 -> "0", 5 -> "10^0", 120 -> "10^2"."""
    if count is None or (isinstance(count, float) and math.isnan(count)):
        return None
    if count < 1:
        return "0"
    return f"10^{int(math.floor(math.log10(count)))}"


def _pagerank_band(rank: int, total: int) -> str:
    share = rank / total if total else 1
    for limit in (0.01, 0.05, 0.10, 0.25):
        if share <= limit:
            return f"top{int(limit * 100)}%"
    return "other"


def compute(
    data: pd.DataFrame,
    references: dict[str, list[str]],
    citers: dict[str, list[str]],
    today: date | None = None,
) -> pd.DataFrame:
    """The metric columns of each row of ``data`` (same index)."""
    import networkx as nx

    today = today or date.today()
    dois = [
        normalize_doi(value) if is_valid(value) else ""
        for value in data.get("DOI", pd.Series("", index=data.index))
    ]
    corpus = {doi for doi in dois if doi}
    refs = {
        normalize_doi(k): {normalize_doi(d) for d in v} - {""}
        for k, v in references.items()
    }
    cits = {
        normalize_doi(k): {normalize_doi(d) for d in v} - {""}
        for k, v in citers.items()
    }

    graph = nx.DiGraph()
    graph.add_nodes_from(corpus)
    for doi in corpus:
        for cited in refs.get(doi, set()) & corpus:
            graph.add_edge(doi, cited)
        for citer in cits.get(doi, set()) & corpus:
            graph.add_edge(citer, doi)
    pagerank = nx.pagerank(graph) if graph.number_of_edges() else {}
    ranked = sorted(pagerank, key=pagerank.get, reverse=True)
    position = {doi: i + 1 for i, doi in enumerate(ranked)}

    rows = []
    for index, doi in zip(data.index, dois, strict=True):
        known = doi in refs or doi in cits
        n_cit = len(cits.get(doi, ())) if known else None
        n_ref = len(refs.get(doi, ())) if known else None
        year = (
            extract_year(data.at[index, "date"])
            if is_valid(data.at[index, "date"])
            else None
        )
        per_year = None
        if n_cit is not None and year:
            per_year = round(n_cit / max(1, today.year - int(year) + 1), 2)
        quality = (
            pd.to_numeric(data.at[index, "quality_score"], errors="coerce")
            if "quality_score" in data
            else None
        )
        venue = next(
            (
                str(data.at[index, c])
                for c in VENUE_COLUMNS
                if c in data and is_valid(data.at[index, c])
            ),
            "",
        )
        rows.append(
            {
                "metric_citations": n_cit,
                "metric_references": n_ref,
                "metric_citations_year": per_year,
                "metric_cited_in_corpus": graph.in_degree(doi)
                if doi in graph
                else None,
                "metric_cites_in_corpus": graph.out_degree(doi)
                if doi in graph
                else None,
                "metric_pagerank": round(pagerank[doi], 6) if doi in pagerank else None,
                "_pagerank_band": _pagerank_band(position[doi], len(ranked))
                if doi in position
                else None,
                "metric_quality": None
                if quality is None or pd.isna(quality)
                else float(quality),
                "metric_venue_rank": venue,
                "metric_computed_at": today.isoformat(),
            }
        )
    return pd.DataFrame(rows, index=data.index)


def tags_for(metrics: dict) -> list[str]:
    """Annotation tags of one row of :func:`compute`."""
    tags = []
    for dimension, column in (
        ("CITATIONS", "metric_citations"),
        ("REFERENCES", "metric_references"),
        ("CITATIONS_PER_YEAR", "metric_citations_year"),
        ("CITED_IN_CORPUS", "metric_cited_in_corpus"),
    ):
        value = magnitude(metrics.get(column))
        if value is not None:
            tags.append(f"{dimension}:{value}")
    if metrics.get("_pagerank_band"):
        tags.append(f"PAGERANK:{metrics['_pagerank_band']}")
    quality = metrics.get("metric_quality")
    if quality is not None and not (isinstance(quality, float) and math.isnan(quality)):
        tags.append(f"QUALITY:{int(min(quality, 100) // 10 * 10)}")
    if metrics.get("metric_venue_rank"):
        tags.append(f"VENUE_RANK:{metrics['metric_venue_rank']}")
    return tags


def annotate(
    data: pd.DataFrame,
    references: dict[str, list[str]],
    citers: dict[str, list[str]],
    today: date | None = None,
) -> int:
    """Write the metric columns and tags into ``data`` (in place); return rows tagged."""
    metrics = compute(data, references, citers, today)
    for column in metrics.columns:
        if not column.startswith("_"):
            data[column] = metrics[column].astype(object)
    if "tags" not in data.columns:
        data["tags"] = ""
    data["tags"] = data["tags"].astype(object)
    tagged = 0
    for index, row in metrics.to_dict("index").items():
        old = (
            [t.strip() for t in str(data.at[index, "tags"]).split(";")]
            if is_valid(data.at[index, "tags"])
            else []
        )
        kept = [
            t for t in old if t and t.split(":")[0].upper() not in METRIC_DIMENSIONS
        ]
        new = tags_for(row)
        data.at[index, "tags"] = ";".join(kept + new)
        tagged += bool(new)
    return tagged
