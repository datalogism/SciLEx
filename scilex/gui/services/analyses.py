"""Analyses of the desktop GUI: charts, keywords, enrichment, snowball, graph, summaries.

Each ``run_*`` function reproduces the body of the matching ``scilex-*`` command
on the configuration of one review. The commands themselves cannot be called
(they parse ``sys.argv``, read global configuration and call ``sys.exit``), so
the building blocks they use are called directly with ``config.main`` / ``config.api``.
All outputs go to the review's collection directory.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from scilex.config import SciLExConfig
from scilex.pipeline_utils import (
    extract_corpus_dois,
    find_clusters_csv,
    resolve_collect_dir,
)

logger = logging.getLogger(__name__)

CHARTS_DIRNAME = "chart_aggregated_papers"
GRAPH_DIRNAME = "graph_analysis"
SNOWBALL_BACKUP_FILENAME = "aggregated_results_pre_snowball.csv"
SNOWBALL_SEPARATE_FILENAME = "aggregated_results_snowball.csv"

ProgressFn = Callable[[int, str], None]
CancelEvent = threading.Event | None


def _cancelled(cancel_event: CancelEvent) -> bool:
    return cancel_event is not None and cancel_event.is_set()


class _CancelledError(Exception):
    """Raised inside a callback to abort a building block that has no cancel hook."""


class AnalysisError(Exception):
    """A user-facing problem: missing input, nothing found."""


@dataclass
class AnalysisResult:
    """What a run produced: a message and the files it wrote."""

    message: str
    files: list[Path] = field(default_factory=list)


NO_EDGES_WARNING = (
    "Warning: no links found in the {graphs} graph: fetch citations for more "
    "papers in ⑥ Enrich (Citations tab), then run the graph again."
)
SNOWBALL_NO_METADATA = (
    "No metadata could be fetched for the {count} candidates: Semantic Scholar "
    "requests failed (often rate limiting without a key). Add a Semantic Scholar "
    "key in API keys, or try again later."
)
NO_SCIPY_WARNING = (
    "Warning: scipy is not installed, so papers are ranked by degree centrality "
    "instead of PageRank (communities are unaffected)."
)


@dataclass(frozen=True)
class AnalysisInfo:
    """Static description of one analysis tab."""

    name: str
    title: str
    description: str
    needs: str  # "results", "citations" or "clusters"
    cancel_note: str = "Stops at the next step."
    group: str = "analyse"  # step showing it: "enrich", "extend" or "analyse"


ANALYSES = (
    AnalysisInfo(
        "report",
        "Charts",
        "Draw charts of the aggregated papers: sources, publication types, years, keywords.",
        "results",
        "Stops between charts; the chart being drawn finishes first.",
    ),
    AnalysisInfo(
        "citations",
        "Citations",
        "Fetch the references and citing papers of the corpus (like scilex-enrich-citations), "
        "from Semantic Scholar with OpenCitations as fallback. "
        "Needed by Snowball and Graph; slow without a Semantic Scholar key.",
        "results",
        "Stops after the current paper; fetched data is kept and reused next time.",
        group="enrich",
    ),
    AnalysisInfo(
        "snowball",
        "Snowball",
        "Find papers outside the corpus that are often cited by, or cite, the corpus papers.",
        "citations",
        "Cannot stop while candidate metadata is being fetched; stops right after.",
        group="extend",
    ),
    AnalysisInfo(
        "graph",
        "Graph",
        "Build citation graphs and detect communities of related papers.",
        "citations",
        "Stops between graphs; the graph being built finishes first.",
    ),
    AnalysisInfo(
        "tags",
        "Annotations",
        "Analyse the DIMENSION:value annotation tags: coverage of each dimension, "
        "frequent values per year, close spellings to merge, and dimensions crossed "
        "two by two (empty cells are gaps of the corpus). Accept merges, cross the "
        "dimensions you choose and clean the spellings in Zotero.",
        "results",
        "Stops between charts.",
    ),
    AnalysisInfo(
        "keywords",
        "Keywords",
        "Suggest new search keywords from frequent terms in the paper clusters (run Graph in ⑦ Analyses first).",
        "clusters",
        group="extend",
    ),
    AnalysisInfo(
        "summaries",
        "Summaries",
        "Write a statistical report of each community found by Graph (run Graph first).",
        "clusters",
    ),
    AnalysisInfo(
        "enrich",
        "Papers with Code",
        "Add Papers with Code tasks, methods, benchmarks and GitHub repositories to the aggregated papers.",
        "results",
        "Stops between papers; nothing is written when cancelled.",
        group="enrich",
    ),
    AnalysisInfo(
        "crossref",
        "Crossref",
        "Fill empty abstracts, venues, volumes, pages, dates, publishers, licences and "
        "ISSNs from Crossref (by DOI), and add the Crossref type, citation count and "
        "funders. Existing values are never overwritten.",
        "results",
        "Stops between papers; what was fetched is cached and written.",
        group="enrich",
    ),
    AnalysisInfo(
        "lpwc",
        "Linked Papers With Code",
        "Add the tasks, methods, datasets, repositories and conference of each paper "
        "from Linked Papers With Code (by arXiv id, else exact title): the terms the "
        "knowledge graph links to.",
        "results",
        "Stops between batches; what was fetched is cached and written.",
        group="enrich",
    ),
    AnalysisInfo(
        "search_keywords",
        "Search keywords",
        "Tag each paper with the search keywords of scilex.yml found in its title or "
        "abstract (Collect_KW<n>:keyword, and BK:keyword for bonus keywords), as the "
        "collection does. Gives keywords to papers imported from Zotero, a knowledge "
        "graph or BibTeX, or added by snowballing. Existing tags are kept. "
        "No network needed.",
        "results",
        "Runs in a few seconds; nothing is written when cancelled.",
        group="enrich",
    ),
    AnalysisInfo(
        "orkg",
        "ORKG",
        "Add the Open Research Knowledge Graph paper, research fields and research "
        "problems of each paper (by DOI, else exact title).",
        "results",
        "Stops between papers; what was fetched is cached and written.",
        group="enrich",
    ),
    AnalysisInfo(
        "metrics",
        "Citation metrics",
        "Compute once, from the citation network (Citations tab, ideally the frozen "
        "Zotero snapshot), each paper's citations, references, citations per year, "
        "citations from inside the corpus and PageRank, plus its quality score and "
        "venue rank: metric_* columns and DIMENSION:value tags (CITATIONS:10^2, "
        "PAGERANK:top5%…) that the Zotero sync shares. Earlier metric tags are "
        "replaced; discarded papers are left out.",
        "citations",
        "Runs in a few seconds; nothing is written when cancelled.",
        group="enrich",
    ),
)


def in_group(group: str) -> tuple[AnalysisInfo, ...]:
    """Return the analyses shown by the step ``group`` (``enrich``, ``extend``, ``analyse``)."""
    return tuple(info for info in ANALYSES if info.group == group)


# How each analysis uses the review's aggregated results (see the resources of
# scilex.gui.services.jobs): readers never wait; column enrichers ("write")
# merge what they changed, so they run together; Snowball adding papers
# rewrites the rows.
RESULTS_MODE = {
    "report": "read",
    "graph": "read",
    "summaries": "read",
    "keywords": "read",
    "tags": "read",
    "citations": "read",  # writes its own caches, not the results
    "snowball": "rows",
    "enrich": "write",
    "crossref": "write",
    "lpwc": "write",
    "orkg": "write",
    "search_keywords": "write",
    "metrics": "write",
}


def results_mode(name: str, options: dict | None = None) -> str:
    """How analysis ``name`` with these (normalised) options uses the results."""
    options = options or {}
    if options.get("dry_run"):
        return "read"
    if name == "snowball" and not options.get("add_to_collection", True):
        return "read"  # writes aggregated_results_snowball.csv only
    return RESULTS_MODE.get(name, "rows")


# Analyses that can be limited to the papers kept in screening.
SCOPED = (
    "citations",
    "enrich",
    "crossref",
    "lpwc",
    "orkg",
    "tags",
    "search_keywords",
    "metrics",
)


def without_discarded(df: pd.DataFrame) -> pd.DataFrame:
    """The papers not tagged ``DELETED_BY:`` (discarded papers leave the analyses)."""
    from scilex import review_tags

    if df is None or "tags" not in df.columns:
        return df
    keep = [not review_tags.workflow(value).deleted for value in df["tags"]]
    return df[keep]


def _active(
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None,
) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """``row_filter`` applied after leaving out the discarded papers."""

    def apply(df: pd.DataFrame) -> pd.DataFrame:
        df = without_discarded(df)
        return row_filter(df) if row_filter is not None else df

    return apply


def collect_dir_of(config: SciLExConfig) -> Path:
    """Return the collection directory of the configured review."""
    return Path(resolve_collect_dir(config.main))


def graph_dir_of(collect_dir: Path) -> Path:
    """Return the directory of the graph analysis outputs."""
    return collect_dir / GRAPH_DIRNAME


# --- outputs already on disk -------------------------------------------------


def existing_outputs(collect_dir: Path, name: str) -> list[Path]:
    """List the output files of analysis ``name`` already present in ``collect_dir``."""
    graph_dir = graph_dir_of(collect_dir)
    patterns: dict[str, tuple[Path, list[str]]] = {
        "report": (collect_dir / CHARTS_DIRNAME, ["*.png"]),
        "keywords": (graph_dir, ["keyword_suggestions.md", "keyword_suggestions.yml"]),
        "snowball": (
            collect_dir,
            [SNOWBALL_BACKUP_FILENAME, SNOWBALL_SEPARATE_FILENAME],
        ),
        "graph": (graph_dir, ["clusters_*.csv", "*_graph.gexf", "*_graph.graphml"]),
        "summaries": (graph_dir, ["summary_report.md"]),
        "tags": (
            collect_dir / "annotation_analysis",
            ["annotation_report.md", "*.png"],
        ),
    }
    if name not in patterns:
        return []
    directory, globs = patterns[name]
    return sorted(path for glob in globs for path in directory.glob(glob))


# Inputs whose change makes the outputs of an analysis out of date.
STALE_INPUTS: dict[str, tuple[str, ...]] = {
    "report": ("aggregated_results.csv",),
    "graph": ("aggregated_results.csv", "citations_cache.json", "citers_cache.json"),
    "keywords": (f"{GRAPH_DIRNAME}/clusters_*.csv",),
    "summaries": (f"{GRAPH_DIRNAME}/clusters_*.csv",),
    "tags": ("aggregated_results.csv",),
}
# Writes within the same second as the outputs are not a change.
STALE_TOLERANCE_SECONDS = 1.0


def stale_warning(collect_dir: Path, name: str, files: list[Path]) -> str | None:
    """Return a warning when inputs of ``name`` changed after its outputs ``files``.

    Example: the graph was built, then the aggregation or a snowball rewrote
    ``aggregated_results.csv``; the graph shown no longer matches the corpus.
    """
    if name not in STALE_INPUTS or not files:
        return None
    outputs_time = min(path.stat().st_mtime for path in files)
    newer = sorted(
        {
            path.name
            for pattern in STALE_INPUTS[name]
            for path in collect_dir.glob(pattern)
            if path.stat().st_mtime > outputs_time + STALE_TOLERANCE_SECONDS
        }
    )
    if not newer:
        return None
    return (
        f"Out of date: {', '.join(newer)} changed after these results were made. "
        "Run again to update them."
    )


def missing_prerequisite(collect_dir: Path, needs: str) -> str | None:
    """Return a message when the input of an analysis is absent, else None."""
    if needs == "results":
        if not (collect_dir / "aggregated_results.csv").is_file():
            return "Run the collection first (step Collect): no aggregated results."
    elif needs == "citations":
        if not any(
            (collect_dir / name).is_file()
            for name in ("citations_cache.json", "citers_cache.json")
        ):
            return "No citation data yet. Fetch the citations in ⑥ Enrich (Citations)."
    elif needs == "clusters":
        try:
            find_clusters_csv(str(graph_dir_of(collect_dir)))
        except FileNotFoundError:
            return "No clusters yet. Run Graph in ⑦ Analyses first."
    return None


# --- runners -----------------------------------------------------------------


def run_report(
    config: SciLExConfig, progress: ProgressFn, *, cancel_event: CancelEvent = None
) -> AnalysisResult:
    """Generate the charts of the aggregated results (``scilex-report``)."""
    from scilex import report_charts as charts

    collect_dir = collect_dir_of(config)
    try:
        df = without_discarded(charts.load_data(collect_dir))
    except FileNotFoundError as exc:
        raise AnalysisError(str(exc)) from exc
    out_dir = collect_dir / CHARTS_DIRNAME
    out_dir.mkdir(exist_ok=True)
    steps = (
        ("API sources", charts.plot_chord_diagram),
        ("publication types", charts.plot_itemtype_pie),
        ("years", charts.plot_year_stacked_bar),
        ("keywords", charts.plot_keyword_bars),
        ("keyword heatmap", charts.plot_keyword_heatmap),
    )
    for index, (label, plot) in enumerate(steps):
        if _cancelled(cancel_event):
            return AnalysisResult("Cancelled.")
        progress(int(100 * index / len(steps)), f"Drawing {label}…")
        plot(df, out_dir)
    files = existing_outputs(collect_dir, "report")
    return AnalysisResult(f"{len(files)} charts for {len(df)} papers.", files)


def run_tags(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    cancel_event: CancelEvent = None,
    row_filter: Callable | None = None,
    review_folder: Path | None = None,
    from_zotero: bool = False,
    max_dimensions: int = 5,
    similarity: float = 88,
) -> AnalysisResult:
    """Analyse the annotation tags (see ``scilex.gui.services.tag_review``)."""
    row_filter = _active(row_filter)  # discarded papers left out
    from scilex.gui.services import tag_review

    try:
        message, files = tag_review.run(
            collect_dir_of(config),
            review_folder,
            progress,
            from_zotero=from_zotero,
            row_filter=row_filter,
            max_dimensions=max_dimensions,
            similarity=similarity,
            cancelled=lambda: _cancelled(cancel_event),
        )
    except tag_review.TagReviewError as exc:
        raise AnalysisError(str(exc)) from exc
    if _cancelled(cancel_event):
        return AnalysisResult("Cancelled.", files)
    return AnalysisResult(message, files)


def read_result_csv(path: str | Path, nrows: int | None = None) -> pd.DataFrame:
    """Read a result CSV whatever its delimiter, skipping malformed lines.

    The delimiter (``;``, ``,`` or tab) is guessed from the header line, and
    lines with a wrong number of fields are skipped with a warning instead of
    failing the whole file.

    Raises:
        ValueError: If the file cannot be parsed at all.
    """
    path = Path(path)
    with path.open(encoding="utf-8", errors="replace") as handle:
        header = handle.readline()
    separator = max((";", ",", "\t"), key=header.count)
    try:
        return pd.read_csv(
            path,
            sep=separator,
            dtype=str,
            nrows=nrows,
            engine="python",
            on_bad_lines="warn",
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError) as exc:
        raise ValueError(str(exc)) from exc


def _read_clusters(csv_path: str) -> pd.DataFrame:
    df = read_result_csv(csv_path)
    if "cluster_id" in df.columns:
        df["cluster_id"] = (
            pd.to_numeric(df["cluster_id"], errors="coerce").fillna(-1).astype(int)
        )
    if "pagerank" in df.columns:
        df["pagerank"] = pd.to_numeric(df["pagerank"], errors="coerce").fillna(0.0)
    return df


CLUSTER_CHOICES = {
    "auto": "Automatic (co-citation if available)",
    "cocitation": "Co-citation",
    "coupling": "Bibliographic coupling",
}
GRAPH_LABELS = {"cocitation": "co-citation", "coupling": "bibliographic coupling"}


def _clusters_csv(analysis_dir: str, clusters: str) -> tuple[str, str]:
    """Return the clusters CSV to read and the name of its graph.

    ``clusters`` is ``"auto"`` (co-citation first) or a graph of ``CLUSTER_CHOICES``.
    """
    try:
        csv_path = find_clusters_csv(
            analysis_dir, None if clusters == "auto" else clusters
        )
    except FileNotFoundError as exc:
        if clusters == "auto":
            raise AnalysisError(str(exc)) from exc
        raise AnalysisError(
            f"No {GRAPH_LABELS[clusters]} clusters yet: run the Graph analysis "
            f"with Graph set to {CLUSTER_CHOICES[clusters]} or Both."
        ) from exc
    graph = Path(csv_path).stem.removeprefix("clusters_")
    return csv_path, GRAPH_LABELS.get(graph, graph)


def run_keywords(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    top_k: int = 30,
    min_freq: int = 2,
    clusters: str = "auto",
    cancel_event: CancelEvent = None,
) -> AnalysisResult:
    """Suggest new keywords from the clusters (``scilex-suggest-keywords``)."""
    from scilex.keyword_suggestions.extractor import (
        configured_keywords,
        extract_suggestions,
    )
    from scilex.keyword_suggestions.report import generate_keyword_report

    collect_dir = collect_dir_of(config)
    analysis_dir = str(graph_dir_of(collect_dir))
    csv_path, graph_label = _clusters_csv(analysis_dir, clusters)
    if _cancelled(cancel_event):
        return AnalysisResult("Cancelled.")
    progress(30, "Extracting frequent terms…")
    suggestions = extract_suggestions(
        _read_clusters(csv_path),
        configured_keywords(config.main),
        top_k=top_k,
        min_freq=min_freq,
    )
    if not suggestions:
        return AnalysisResult("No new keyword suggestions found.")
    generate_keyword_report(
        suggestions, analysis_dir, collect_name=config.main["collect_name"]
    )
    return AnalysisResult(
        f"{len(suggestions)} keyword suggestions from the {graph_label} clusters.",
        existing_outputs(collect_dir, "keywords"),
    )


def _prepare_enrichment_config(config: SciLExConfig) -> None:
    """Adapt the Papers with Code settings to a run started from the GUI.

    Clicking the button is the request to enrich, so the ``enabled`` flag
    (``false`` by default, meant for the command line) is forced on. The
    default cache path ``output/pwc_cache.db`` is relative to the working
    directory, which is read-only in the packaged app and arbitrary in
    development: it is moved inside the review folder.
    """
    from scilex.pipeline.enrichment_pwc import (
        DEFAULT_CACHE_PATH,
        enrichment_settings,
    )

    pwc_config = enrichment_settings(config.main)
    cache_path = Path(pwc_config.get("cache_path") or DEFAULT_CACHE_PATH)
    if not cache_path.is_absolute():
        pwc_config["cache_path"] = str(collect_dir_of(config) / cache_path.name)
    pwc_config["enabled"] = True
    config.main["pwc_enrichment"] = pwc_config


def run_enrich(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    threshold: int | None = None,
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    cancel_event: CancelEvent = None,
) -> AnalysisResult:
    """Enrich the aggregated CSV with Papers with Code metadata (``scilex-enrich``).

    ``row_filter`` limits the papers looked up (e.g. to those kept in screening);
    the other rows are written back unchanged.
    """
    row_filter = _active(row_filter)  # discarded papers left out
    from scilex.gui.services import results_store
    from scilex.pipeline.enrichment_pwc import EnrichmentOptions, run_enrichment

    _prepare_enrichment_config(config)
    options = EnrichmentOptions(
        dry_run=dry_run,
        limit=limit or None,
        threshold=threshold or None,
        row_filter=row_filter,
        # Only the Papers with Code columns: other enrichers may write meanwhile.
        writer=lambda data, path, columns: results_store.write_columns(
            path, data, columns
        ),
    )

    def on_progress(processed: int, total: int, stats: dict) -> None:
        if _cancelled(cancel_event):
            raise _CancelledError
        progress(int(100 * processed / max(total, 1)), f"{processed}/{total} papers")

    try:
        result = run_enrichment(config, options, on_progress)
    except _CancelledError:
        return AnalysisResult("Cancelled.")
    except FileNotFoundError as exc:
        raise AnalysisError(str(exc)) from exc
    # A dry run updates nothing: every matched paper is one that would be.
    changed = (
        f"{result.matched} would be updated" if dry_run else f"{result.updated} updated"
    )
    files = [Path(result.output_path)] if result.output_path else []
    return AnalysisResult(
        f"{result.matched} of {result.processed} papers matched, {changed}.", files
    )


def run_citations(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    limit: int | None = None,
    skip_citers: bool = False,
    no_fallback: bool = False,
    source: str = "auto",
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    cancel_event: CancelEvent = None,
    review=None,
) -> AnalysisResult:
    """Fetch references and citers of the corpus (``scilex-enrich-citations``).

    ``source`` ``zotero`` reads instead the frozen snapshot of the citation
    notes of the review's Zotero library (``review`` required), see
    :mod:`scilex.gui.services.zotero_citations`.

    ``source``: ``auto`` (Semantic Scholar, then CrossRef, then OpenCitations),
    ``crossref`` (CrossRef then OpenCitations; citers from OpenCitations) or
    ``opencitations`` (OpenCitations only).

    ``row_filter`` limits the papers fetched (e.g. to those kept in screening).

    Writes ``citations_cache.json`` and ``citers_cache.json`` in the collection
    directory (what Snowball and Graph read). A cancellation is honoured before
    each paper and between fallback sources; the caches are reused on rerun.
    """
    row_filter = _active(row_filter)  # discarded papers left out
    if source == "zotero":
        return _citations_from_zotero(review, progress)
    from scilex.citations.reference_fetcher import (
        fetch_citers_batch,
        fetch_references_batch,
    )
    from scilex.constants import is_valid
    from scilex.crawlers.key_pool import first_key
    from scilex.io_utils import load_aggregated_data

    collect_dir = collect_dir_of(config)
    try:
        data = load_aggregated_data(config.main)
    except (FileNotFoundError, ValueError) as exc:
        raise AnalysisError(str(exc)) from exc
    if row_filter is not None:
        data = row_filter(data)
    if limit:
        data = data.head(limit)
    dois = [
        str(doi).strip()
        for doi in data.get("DOI", [])
        if is_valid(doi) and str(doi).strip()
    ]
    if not dois:
        raise AnalysisError(
            "No paper with a DOI among the papers kept in screening."
            if row_filter is not None
            else "No paper with a DOI in the aggregated results."
        )
    api_key = first_key(config.api.get("SemanticScholar", {}).get("api_key"))
    mailto = config.api.get("CrossRef", {}).get("mailto")
    collect_dir.mkdir(parents=True, exist_ok=True)

    def should_stop() -> bool:
        return _cancelled(cancel_event)

    stages = [
        (
            "references",
            collect_dir / "citations_cache.json",
            lambda cache, on_progress: fetch_references_batch(
                dois,
                api_key=api_key,
                cache_path=str(cache),
                fallback_opencitations=not no_fallback or source == "opencitations",
                use_semantic_scholar=source == "auto",
                use_crossref=source != "opencitations",
                mailto=mailto,
                should_stop=should_stop,
                on_progress=on_progress,
            ),
        )
    ]
    if not skip_citers:
        stages.append(
            (
                "citing papers",
                collect_dir / "citers_cache.json",
                lambda cache, on_progress: fetch_citers_batch(
                    dois,
                    api_key=api_key,
                    cache_path=str(cache),
                    fallback_opencitations=not no_fallback or source != "auto",
                    use_semantic_scholar=source == "auto",
                    should_stop=should_stop,
                    on_progress=on_progress,
                ),
            )
        )
    started = time.time()
    found: dict[str, bool] = dict.fromkeys(dois, False)
    for index, (label, cache, fetch) in enumerate(stages):

        def on_progress(done: int, to_fetch: int, index=index, label=label) -> None:
            if should_stop():
                return  # keep the "Cancelling…" message
            fraction = (index + done / max(to_fetch, 1)) / len(stages)
            progress(int(100 * fraction), f"Fetching {label}: {done}/{to_fetch}")

        if should_stop():
            break
        progress(int(100 * index / len(stages)), f"Fetching {label}…")
        fetched = fetch(cache, on_progress) or {}
        for doi, links in fetched.items():
            if links:
                found[doi] = True
    if should_stop():
        return AnalysisResult(
            "Cancelled; citation data fetched so far is kept and reused next time."
        )
    files = [cache for _, cache, _ in stages if cache.is_file()]
    with_data = sum(found.values())
    if not with_data:
        raise AnalysisError(
            "No citation data could be fetched: check your Semantic Scholar key "
            "in API keys or your connection."
        )
    elapsed = time.time() - started
    if with_data < len(dois):
        message = (
            f"Warning: citation data fetched for {with_data} of {len(dois)} papers "
            f"in {elapsed:.0f}s (the others returned nothing: failed requests "
            "or no known citations)."
        )
    else:
        message = f"Citation data fetched for {len(dois)} papers in {elapsed:.0f}s."
    return AnalysisResult(message, files)


def _citations_from_zotero(review, progress: ProgressFn) -> AnalysisResult:
    """The Citations tab with the Zotero snapshot as source."""
    from scilex.gui.services import zotero_citations

    if review is None:
        raise AnalysisError("The Zotero snapshot needs the review.")
    progress(10, "Reading the citation notes of the Zotero library…")
    try:
        report = zotero_citations.import_snapshot(review)
    except (ValueError, ConnectionError) as exc:
        raise AnalysisError(str(exc)) from exc
    folder = review.collection_dir
    files = [
        folder / zotero_citations.SNAPSHOT_FILENAME,
        folder / zotero_citations.REFERENCES_CACHE,
        folder / zotero_citations.CITERS_CACHE,
    ]
    return AnalysisResult(report.message(), files)


def run_metrics(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    tags: bool = True,
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    cancel_event: CancelEvent = None,
) -> AnalysisResult:
    """Citation and quality metrics of each paper (see :mod:`scilex.citation_metrics`).

    Written as cell changes, so enrichers running meanwhile keep their work.
    """
    from scilex import citation_metrics
    from scilex.graph_analysis.loader import load_citation_caches
    from scilex.gui.services.extend import read_results
    from scilex.gui.services.results_store import write_changes
    from scilex.io_utils import resolve_aggregate_path

    row_filter = _active(row_filter)
    collect_dir = collect_dir_of(config)
    path = Path(resolve_aggregate_path(config.main))
    try:
        data = read_results(path)
        references, citers = load_citation_caches(str(collect_dir))
    except (FileNotFoundError, ValueError) as exc:
        raise AnalysisError(str(exc)) from exc
    if data is None:
        raise AnalysisError("No aggregated results yet.")
    progress(20, "Computing the metrics…")
    before = row_filter(data).copy()
    after = before.copy()
    if tags:
        tagged = citation_metrics.annotate(after, references, citers)
    else:
        metrics = citation_metrics.compute(after, references, citers)
        for column in metrics.columns:
            if not column.startswith("_"):
                after[column] = metrics[column].astype(object)
        tagged = 0
    if _cancelled(cancel_event):
        return AnalysisResult("Cancelled; nothing was written.")
    written = write_changes(path, before, after)
    known = int(after["metric_citations"].notna().sum())
    message = (
        f"Metrics computed for {len(after)} papers ({known} with citation data); "
        f"{written} rows updated" + (f", {tagged} tagged." if tags else ".")
    )
    progress(100, message)
    return AnalysisResult(message, [path])


def run_snowball(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    direction: str = "both",
    top_k: int = 200,
    min_frequency: int = 2,
    dry_run: bool = False,
    add_to_collection: bool = True,
    cancel_event: CancelEvent = None,
) -> AnalysisResult:
    """Extend the corpus through citation links (``scilex-snowball``).

    ``add_to_collection`` False writes ``aggregated_results_snowball.csv`` and
    leaves ``aggregated_results.csv`` untouched.
    """
    from scilex.crawlers.key_pool import first_key
    from scilex.graph_analysis.loader import load_citation_caches
    from scilex.io_utils import load_aggregated_data, resolve_aggregate_path
    from scilex.snowball.candidates import extract_candidates
    from scilex.snowball.fetcher import fetch_metadata_batch
    from scilex.snowball.filter import apply_snowball_filters
    from scilex.snowball.merge import merge_with_corpus, write_snowball_output

    collect_dir = collect_dir_of(config)
    try:
        corpus_df = load_aggregated_data(config.main, preserve_missing_marker=True)
        references, citers = load_citation_caches(str(collect_dir))
    except (FileNotFoundError, ValueError) as exc:
        raise AnalysisError(str(exc)) from exc
    if _cancelled(cancel_event):
        return AnalysisResult("Cancelled.")
    progress(10, "Looking for candidates…")
    candidates = extract_candidates(
        references,
        citers,
        extract_corpus_dois(corpus_df),
        direction=direction,
        top_k=top_k,
        min_frequency=min_frequency,
    )
    if not candidates:
        return AnalysisResult("No candidates found. Try a lower minimum frequency.")
    if dry_run:
        preview = "\n".join(f"{doi}  ({freq})" for doi, freq in candidates[:50])
        return AnalysisResult(f"{len(candidates)} candidates (dry run).\n{preview}")
    if _cancelled(cancel_event):
        return AnalysisResult("Cancelled.")
    progress(30, f"Fetching metadata of {len(candidates)} candidates…")
    api_key = first_key(config.api.get("SemanticScholar", {}).get("api_key"))
    papers = fetch_metadata_batch([doi for doi, _ in candidates], api_key=api_key)
    if _cancelled(cancel_event):
        return AnalysisResult("Cancelled.")
    if not papers:
        raise AnalysisError(SNOWBALL_NO_METADATA.format(count=len(candidates)))
    filtered = apply_snowball_filters(papers)
    if filtered.empty:
        return AnalysisResult(
            f"None of the {len(papers)} candidates found passed the quality filters."
        )
    merged = merge_with_corpus(corpus_df, filtered)
    output_csv, _ = write_snowball_output(
        merged, resolve_aggregate_path(config.main), add_to_collection
    )
    added = len(merged) - len(corpus_df)
    where = (
        "added to the collection"
        if add_to_collection
        else f"written to {Path(output_csv).name} (collection unchanged)"
    )
    return AnalysisResult(
        f"{added} new papers {where} ({len(merged)} in total).", [Path(output_csv)]
    )


def _read_for_enrichment(config: SciLExConfig) -> tuple[Path, pd.DataFrame]:
    """Path and content of the aggregated results, read under the file's lock."""
    from scilex.gui.services.extend import read_results
    from scilex.io_utils import resolve_aggregate_path

    path = Path(resolve_aggregate_path(config.main))
    try:
        data = read_results(path)
    except ValueError as exc:  # damaged CSV
        raise AnalysisError(str(exc)) from exc
    if data is None:
        raise AnalysisError(f"No aggregated results yet: {path} is missing.")
    return path, data


def run_linked(
    config: SciLExConfig,
    progress: ProgressFn,
    source: str,
    *,
    limit: int | None = None,
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    cancel_event: CancelEvent = None,
) -> AnalysisResult:
    """Enrich the aggregated CSV from Crossref, Linked Papers With Code or ORKG.

    See :mod:`scilex.linked_enrichment`. Results already fetched are written even
    when the run is cancelled (they are also cached for the next run).
    """
    row_filter = _active(row_filter)  # discarded papers left out
    from scilex import linked_enrichment
    from scilex.gui.services import results_store

    collect_dir = collect_dir_of(config)
    path, data = _read_for_enrichment(config)
    before = data.copy()
    kwargs = {}
    if source == "crossref":
        kwargs["mailto"] = config.api.get("CrossRef", {}).get("mailto")
    try:
        report = linked_enrichment.ENRICHERS[source](
            data,
            collect_dir / f"{source}_cache.json",
            row_filter=row_filter,
            limit=limit or None,
            progress=progress,
            cancel=cancel_event,
            **kwargs,
        )
    except linked_enrichment.Cancelled:
        return AnalysisResult("Cancelled; what was fetched is cached for the next run.")
    # Only the cells this source filled: other enrichers may write meanwhile.
    results_store.write_changes(path, before, data)
    if report.looked_up == 0 and report.failed:
        raise AnalysisError(
            f"{report.source} could not be reached: check your connection."
        )
    return AnalysisResult(report.message(), [path])


def run_search_keywords(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    row_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    cancel_event: CancelEvent = None,
) -> AnalysisResult:
    """Tag the papers with the configured search keywords found in their text.

    See :mod:`scilex.keyword_annotation`.
    """
    row_filter = _active(row_filter)  # discarded papers left out
    from scilex import keyword_annotation
    from scilex.gui.services import results_store

    groups = keyword_annotation.keyword_groups(config.main)
    bonus = config.main.get("bonus_keywords") or []
    if not groups and not bonus:
        raise AnalysisError("No search keyword in scilex.yml: set them in ① Configure.")
    path, data = _read_for_enrichment(config)
    before = data.copy()
    progress(10, "Looking for the search keywords in titles and abstracts…")
    report = keyword_annotation.annotate_keywords(
        data, groups, bonus, row_filter=row_filter
    )
    if _cancelled(cancel_event):
        return AnalysisResult("Cancelled; nothing was written.")
    if report.updated:
        results_store.write_changes(path, before, data)
    progress(100, report.message())
    return AnalysisResult(report.message(), [path] if report.updated else [])


def run_graph(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    graph_type: str = "cocitation",
    resolution: float = 1.0,
    min_weight: int = 1,
    fmt: str = "gexf",
    cancel_event: CancelEvent = None,
) -> AnalysisResult:
    """Build citation graphs, detect communities and export them (``scilex-analyze``)."""
    from scilex.graph_analysis.community import compute_centrality, detect_communities
    from scilex.graph_analysis.export import export_clusters_csv, export_graph
    from scilex.graph_analysis.graphs import (
        build_bibliographic_coupling_graph,
        build_cocitation_graph,
    )
    from scilex.graph_analysis.loader import load_citation_caches
    from scilex.io_utils import load_aggregated_data

    collect_dir = collect_dir_of(config)
    analysis_dir = graph_dir_of(collect_dir)
    try:
        df = without_discarded(load_aggregated_data(config.main))
        references, citers = load_citation_caches(str(collect_dir))
    except (FileNotFoundError, ValueError) as exc:
        raise AnalysisError(str(exc)) from exc
    analysis_dir.mkdir(exist_ok=True)
    corpus_dois = extract_corpus_dois(df)

    builders = {
        "cocitation": lambda: build_cocitation_graph(
            references, citers, corpus_dois, min_weight=min_weight
        ),
        "coupling": lambda: build_bibliographic_coupling_graph(
            references, corpus_dois, min_weight=min_weight
        ),
    }
    names = list(builders) if graph_type == "both" else [graph_type]
    empty_graphs: list[str] = []
    for index, name in enumerate(names):
        if _cancelled(cancel_event):
            return AnalysisResult("Cancelled.")
        progress(int(100 * index / len(names)), f"Analysing {name} graph…")
        graph = builders[name]()
        if graph.number_of_edges() == 0:
            empty_graphs.append(name)
        partition = detect_communities(graph, resolution=resolution)
        pagerank = compute_centrality(graph)
        export_clusters_csv(
            df, partition, pagerank, os.path.join(analysis_dir, f"clusters_{name}.csv")
        )
        export_graph(
            graph,
            partition,
            pagerank,
            os.path.join(analysis_dir, f"{name}_graph.{fmt}"),
            fmt=fmt,
        )
    message = f"Graph analysis done ({', '.join(names)})."
    if empty_graphs:
        message += " " + NO_EDGES_WARNING.format(graphs=", ".join(empty_graphs))
    if importlib.util.find_spec("scipy") is None:
        message += " " + NO_SCIPY_WARNING
    return AnalysisResult(message, existing_outputs(collect_dir, "graph"))


def run_summaries(
    config: SciLExConfig,
    progress: ProgressFn,
    *,
    clusters: str = "auto",
    cancel_event: CancelEvent = None,
) -> AnalysisResult:
    """Write the community summary report (``scilex-summarize``)."""
    from scilex.summarize.report import generate_report
    from scilex.summarize.stats import compute_cluster_stats

    collect_dir = collect_dir_of(config)
    analysis_dir = graph_dir_of(collect_dir)
    csv_path, graph_label = _clusters_csv(str(analysis_dir), clusters)
    if _cancelled(cancel_event):
        return AnalysisResult("Cancelled.")
    progress(30, "Computing cluster statistics…")
    stats = compute_cluster_stats(_read_clusters(csv_path))
    if not stats:
        return AnalysisResult("No clusters found in the data.")
    if all(cluster.size <= 1 for cluster in stats):
        # A graph without edges leaves every paper alone in its own community.
        return AnalysisResult(
            f"No links found in the {graph_label} graph: fetch citations for more papers in the "
            "Citations tab of ⑥ Enrich. A summary of one-paper communities would be meaningless."
        )
    report_path = analysis_dir / "summary_report.md"
    generate_report(stats, str(report_path), collect_name=config.main["collect_name"])
    communities = sum(1 for cluster in stats if cluster.size > 1)
    return AnalysisResult(
        f"Summary of {communities} communities from the {graph_label} graph "
        f"({len(stats) - communities} one-paper communities left out).",
        [report_path],
    )


# --- options coming from the page --------------------------------------------

# name -> {option: caster}; options not listed are dropped.
OPTION_CASTS: dict[str, dict[str, Callable]] = {
    "report": {},
    "keywords": {"top_k": int, "min_freq": int, "clusters": str},
    "enrich": {"dry_run": bool, "limit": int, "threshold": int},
    "citations": {
        "limit": int,
        "skip_citers": bool,
        "no_fallback": bool,
        "source": str,
    },
    "snowball": {
        "direction": str,
        "top_k": int,
        "min_frequency": int,
        "dry_run": bool,
        "add_to_collection": bool,
    },
    "graph": {"graph_type": str, "resolution": float, "min_weight": int, "fmt": str},
    "summaries": {"clusters": str},
    "tags": {"max_dimensions": int, "similarity": float, "from_zotero": bool},
    "crossref": {"limit": int},
    "lpwc": {"limit": int},
    "orkg": {"limit": int},
    "search_keywords": {},
    "metrics": {"tags": bool},
}


def normalize_options(name: str, raw: dict) -> dict:
    """Cast the widget values of analysis ``name`` to the runner's keyword arguments.

    Unknown keys and empty values (None, "") are dropped so the runner defaults apply.
    """
    casts = OPTION_CASTS[name]
    return {
        key: casts[key](value)
        for key, value in raw.items()
        if key in casts and value not in (None, "")
    }


RUNNERS: dict[str, Callable[..., AnalysisResult]] = {
    "report": run_report,
    "keywords": run_keywords,
    "enrich": run_enrich,
    "citations": run_citations,
    "snowball": run_snowball,
    "graph": run_graph,
    "summaries": run_summaries,
    "tags": run_tags,
    "crossref": lambda config, progress, **kw: run_linked(
        config, progress, "crossref", **kw
    ),
    "lpwc": lambda config, progress, **kw: run_linked(config, progress, "lpwc", **kw),
    "orkg": lambda config, progress, **kw: run_linked(config, progress, "orkg", **kw),
    "search_keywords": run_search_keywords,
    "metrics": run_metrics,
}
