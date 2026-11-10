"""Core of the Papers with Code CSV enrichment (no CLI, no ``sys.argv``).

``run_enrichment`` reads the aggregated CSV, looks each paper up on Papers with
Code (https://paperswithcode.co), adds the ``tags``, ``pwc_url`` and
``github_repo`` columns and writes the CSV back. It receives its configuration
and options as parameters, so the CLI (``scilex.enrich_with_pwc``), the GUI and
the web API call it the same way.
"""

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

import pandas as pd
from tqdm import tqdm

from scilex.config import SciLExConfig
from scilex.constants import MISSING_VALUE, is_valid
from scilex.io_utils import (
    load_aggregated_data,
    resolve_aggregate_path,
    write_aggregated_csv,
)
from scilex.PapersWithCode.client import PWCClient
from scilex.PapersWithCode.tag_formatter import TagFormatter
from scilex.PapersWithCode.title_matcher import TitleMatcher

logger = logging.getLogger(__name__)

ENRICHMENT_COLUMNS = ("tags", "pwc_url", "github_repo")
DEFAULT_CACHE_PATH = "output/pwc_cache.db"

# New-style arXiv identifier (e.g. 2307.03172), in a DOI or an arxiv.org URL.
_ARXIV_DOI = re.compile(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", re.IGNORECASE)
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE)

# progress_callback(processed, total, stats)
ProgressCallback = Callable[[int, int, dict], None]
# Narrows the rows an enrichment run handles (e.g. to the papers kept in screening).
RowFilter = Callable[[pd.DataFrame], pd.DataFrame]


def enrichment_settings(main_config: dict) -> dict:
    """Return the enrichment block of the legacy config.

    ``pwc_enrichment`` is the current key; ``hf_enrichment`` (before ADR 0006)
    is still read so older configurations keep working.
    """
    block = main_config.get("pwc_enrichment")
    if block is None:
        block = main_config.get("hf_enrichment")
    return dict(block or {})


@dataclass
class EnrichmentOptions:
    """Options of one enrichment run.

    Attributes:
        dry_run: Log the matches without modifying or writing the CSV.
        limit: Maximum number of papers to process (None or 0 = all).
        threshold: Fuzzy title matching threshold (0-100). When given (for
            example by ``--threshold``) it takes precedence over the config key
            ``enrichment.paperswithcode.fuzzy_match_threshold`` (default 85).
        collect_dir: Collect directory holding the aggregated CSV (overrides
            ``output_dir`` + ``collect_name`` from the config).
        workers: Papers searched concurrently. When given (for example by
            ``--workers``) it takes precedence over the config key
            ``enrichment.paperswithcode.workers`` (default 4). Network calls
            stay capped by the client's rate limiter, so more workers only
            hide latency.
    """

    dry_run: bool = False
    limit: int | None = None
    threshold: int | None = None
    collect_dir: str | None = None
    workers: int | None = None
    row_filter: RowFilter | None = None


@dataclass
class EnrichmentResult:
    """Outcome of ``run_enrichment``.

    Attributes:
        total: Papers in the CSV.
        processed: Papers examined (matched + skipped).
        matched: Papers found on Papers with Code with at least one tag.
        updated: Papers actually written to the CSV (0 in dry-run).
        skipped: Papers without match, without usable title, or in error.
        output_path: CSV path (written unless dry-run); None otherwise.
        disabled: True when enrichment is disabled in the config (nothing done).
    """

    total: int = 0
    processed: int = 0
    matched: int = 0
    updated: int = 0
    skipped: int = 0
    output_path: str | None = None
    disabled: bool = False


def extract_arxiv_id(paper_row: pd.Series) -> str | None:
    """Return the paper's arXiv identifier from its DOI or URLs, or None."""
    doi = paper_row.get("DOI")
    if is_valid(doi) and (match := _ARXIV_DOI.search(str(doi))):
        return match.group(1)
    for column in ("url", "pdf_url"):
        value = paper_row.get(column)
        if is_valid(value) and (match := _ARXIV_URL.search(str(value))):
            return match.group(1)
    return None


def find_paper(
    paper_row: pd.Series, client: PWCClient, matcher: TitleMatcher
) -> dict | None:
    """Find a paper on Papers with Code: by arXiv ID first, then by title.

    Returns:
        The summarized record (see ``summarize_paper``), or None.
    """
    title = paper_row.get("title")
    arxiv_id = extract_arxiv_id(paper_row)
    if arxiv_id and (paper := client.get_paper_by_arxiv(arxiv_id)):
        logging.debug(f"arXiv match: {arxiv_id}")
        return paper

    if not is_valid(title):
        return None
    candidates = client.search_papers(str(title), limit=10)
    best, score = matcher.find_best_match(str(title), candidates, key="title")
    if not best:
        return None
    logging.info(
        f"✓ Title match: '{str(title)[:40]}...' → {best['title'][:40]}... "
        f"(score: {score})"
    )
    return client.get_paper(best.get("arxiv_id") or best["id"])


def paper_tags(paper: dict, formatter: TagFormatter) -> list[str]:
    """Build the prefixed tags of a summarized Papers with Code record."""
    tags = [formatter.format_task_tag(task) for task in paper.get("tasks", [])]
    tags += [formatter.format_architecture_tag(m) for m in paper.get("methods", [])]
    tags += formatter.format_dataset_tags(paper.get("benchmarks", []))
    tags += [formatter.format_framework_tag(f) for f in paper.get("frameworks", [])]
    tags.append(formatter.format_github_stars_tag(paper.get("github_stars")))
    # Drop empty values and duplicates, keep order
    return list(dict.fromkeys(tag for tag in tags if tag))


def process_paper_for_csv(
    paper_row: pd.Series,
    client: PWCClient,
    matcher: TitleMatcher,
    formatter: TagFormatter,
) -> dict | None:
    """Process a single CSV row: find the paper, format its tags and links.

    Returns:
        ``{"tags": "TASK:QuestionAnswering;ARCHI:Transformer",
        "pwc_url": "https://paperswithcode.co/paper/...",
        "github_repo": "https://github.com/..."}``, or None when the paper is
        not found or has nothing to add.
    """
    paper = find_paper(paper_row, client, matcher)
    if paper is None:
        logging.debug(f"No Papers with Code match for: {paper_row.get('title')}")
        return None

    tags = paper_tags(paper, formatter)
    if not tags and not paper.get("github_repo"):
        return None

    return {
        "tags": ";".join(tags) if tags else MISSING_VALUE,
        "pwc_url": paper.get("url") or MISSING_VALUE,
        "github_repo": paper.get("github_repo") or MISSING_VALUE,
    }


def _rows_to_process(
    data: pd.DataFrame, limit: int | None, row_filter: RowFilter | None = None
) -> pd.DataFrame:
    """Return the rows an enrichment run handles: the first ``limit`` ones, or all.

    ``row_filter`` narrows them first (the other rows are kept, untouched).
    """
    if row_filter is not None:
        data = row_filter(data)
    return data.head(limit) if limit else data


def _enrich_rows(
    data: pd.DataFrame,
    client: PWCClient,
    matcher: TitleMatcher,
    formatter: TagFormatter,
    options: EnrichmentOptions,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[tuple[object, dict]], dict]:
    """Look up each row on Papers with Code, without modifying ``data``.

    Rows are searched concurrently (``options.workers`` threads); ``data`` is
    only read and results come back in row order.

    Args:
        data: Aggregated papers.
        client: PWCClient instance.
        matcher: TitleMatcher instance.
        formatter: TagFormatter instance.
        options: Run options (``limit``, ``dry_run`` and ``workers`` are used here).
        progress_callback: Optional ``callback(processed, total, stats)``,
            called after every row; ``total`` is the number of rows to
            process (``options.limit`` applied).

    Returns:
        ``(updates, stats)``: ``updates`` is the list of ``(row_label, result)``
        for matched rows, in row order; ``stats`` has the keys ``total``,
        ``matched``, ``skipped``.
    """
    stats = {"total": len(data), "matched": 0, "skipped": 0}
    updates: list[tuple[object, dict]] = []
    rows = _rows_to_process(data, options.limit, getattr(options, "row_filter", None))

    def search_row(item):
        """Run one paper's search; errors are returned, not raised."""
        idx, row = item
        try:
            result = process_paper_for_csv(row, client, matcher, formatter)
            return idx, row, result, None
        except Exception as error:
            return idx, row, None, error

    # map() yields in row order; counting and callbacks stay on this thread.
    # map() queues every row at once: if a callback raises (GUI cancel), the
    # queued searches are dropped instead of all running before the exit.
    executor = ThreadPoolExecutor(max_workers=max(1, options.workers or 4))
    try:
        outcomes = executor.map(search_row, rows.iterrows())
        for idx, row, result, error in tqdm(
            outcomes, total=len(rows), desc="Processing papers"
        ):
            if error is not None:
                logging.error(f"Error processing row {idx}: {error}")
                stats["skipped"] += 1
            elif result is None:
                stats["skipped"] += 1
            else:
                stats["matched"] += 1
                updates.append((idx, result))
                if options.dry_run:
                    logging.info(f"[DRY RUN] Would enrich: {row['title'][:50]}...")
                    logging.info(f"  Tags: {result['tags']}")
                    logging.info(f"  PwC URL: {result['pwc_url']}")
                    logging.info(f"  GitHub: {result['github_repo']}")

            if progress_callback:
                progress_callback(stats["matched"] + stats["skipped"], len(rows), stats)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    return updates, stats


def run_enrichment(
    config: SciLExConfig,
    options: EnrichmentOptions | None = None,
    progress_callback: ProgressCallback | None = None,
) -> EnrichmentResult:
    """Enrich the aggregated CSV with Papers with Code metadata.

    Args:
        config: Loaded configuration (``pwc_enrichment`` section, collection
            location).
        options: Run options (defaults to ``EnrichmentOptions()``).
        progress_callback: Optional ``callback(processed, total, stats)``.

    Returns:
        EnrichmentResult with counters and the CSV path.

    Raises:
        FileNotFoundError: If the aggregated CSV does not exist.
    """
    options = options or EnrichmentOptions()
    main_config = config.main

    pwc_config = enrichment_settings(main_config)
    if not pwc_config.get("enabled", True):
        logging.warning("Papers with Code enrichment is disabled in config. Exiting.")
        return EnrichmentResult(disabled=True)

    if options.workers is None:
        options = replace(options, workers=pwc_config.get("workers", 4))

    logging.info("Initializing Papers with Code enrichment...")
    client = PWCClient(
        cache_path=pwc_config.get("cache_path") or DEFAULT_CACHE_PATH,
        cache_ttl_days=pwc_config.get("cache_ttl_days", 30),
    )
    matcher = TitleMatcher(
        threshold=(
            options.threshold
            if options.threshold is not None
            else pwc_config.get("fuzzy_match_threshold", 85)
        )
    )
    formatter = TagFormatter()

    csv_path = resolve_aggregate_path(main_config, options.collect_dir)
    logging.info(f"Loading CSV: {csv_path}")
    data = load_aggregated_data(
        main_config, options.collect_dir, preserve_missing_marker=True
    )
    logging.info(f"Loaded {len(data)} papers")

    for column in ENRICHMENT_COLUMNS:
        if column not in data.columns:
            data[column] = MISSING_VALUE

    logging.info(f"Processing papers (limit: {options.limit})...")
    updates, stats = _enrich_rows(
        data,
        client,
        matcher,
        formatter,
        options,
        progress_callback=progress_callback,
    )

    updated = 0
    if not options.dry_run:
        for idx, result in updates:
            for column in ENRICHMENT_COLUMNS:
                data.at[idx, column] = result[column]
            updated += 1

    processed = stats["matched"] + stats["skipped"]
    if progress_callback:
        # Final progress report
        progress_callback(
            processed,
            len(_rows_to_process(data, options.limit, getattr(options, "row_filter", None))),
            {**stats, "updated": updated},
        )

    output_path = None
    if not options.dry_run:
        write_aggregated_csv(data, csv_path)
        output_path = str(csv_path)
        logging.info(f"✓ Updated CSV written: {csv_path}")

    return EnrichmentResult(
        total=stats["total"],
        processed=processed,
        matched=stats["matched"],
        updated=updated,
        skipped=stats["skipped"],
        output_path=output_path,
    )
