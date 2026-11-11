"""Pipeline orchestrator — programmatic entry points for SciLEx pipelines.

Provides run_aggregation() and run_collection() as pure function calls,
replacing the need for sys.argv manipulation or subprocess calls.
"""

import contextlib
import csv
import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import yaml

from scilex.abstract_validation import (
    SCORING_COLUMNS,
    validate_dataframe_abstracts,
)
from scilex.config import SciLExConfig
from scilex.config_defaults import (
    DEFAULT_AGGREGATED_FILENAME,
    DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD,
    DEFAULT_DOI_RECOVERY_MIN_SIMILARITY,
    DEFAULT_ENRICH_AUTHOR_HINDEX,
    DEFAULT_ENRICH_UNPAYWALL,
    DEFAULT_GENERATE_PRISMA_REPORT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RECOVER_MISSING_DOIS,
    DEFAULT_SINCE,
    DEFAULT_UNPAYWALL_EMAIL,
    DEFAULT_USE_VENUE_RANKING,
    MAX_ABSTRACT_WORDS,
    MIN_ABSTRACT_QUALITY_SCORE,
    MIN_ABSTRACT_WORDS,
)
from scilex.constants import normalize_path_component
from scilex.crawlers.aggregate import quality_scores
from scilex.crawlers.collector_collection import CollectCollection
from scilex.crawlers.key_pool import first_key
from scilex.duplicate_tracking import (
    analyze_and_report_duplicates,
    generate_itemtype_distribution_report,
)
from scilex.io_utils import write_aggregated_csv
from scilex.keyword_validation import generate_keyword_validation_report
from scilex.llm_relevance import (
    CACHE_FILENAME,
    LLMScreeningConfig,
    apply_llm_screening,
)
from scilex.logging_config import add_file_log_handler
from scilex.pipeline.bonus_keywords import (
    generate_bonus_keyword_stats,
    tag_papers_with_bonus_keywords,
)
from scilex.pipeline.canonical_citations import apply_canonical_citations
from scilex.pipeline.citation_filter import apply_time_aware_citation_filter
from scilex.pipeline.enrichment import (
    fill_missing_urls_from_doi,
    use_openalex_citations_fallback,
    use_semantic_scholar_citations_fallback,
)
from scilex.pipeline.itemtype_filter import apply_itemtype_bypass, apply_itemtype_filter
from scilex.pipeline.ranking import apply_relevance_ranking
from scilex.pipeline.report import (
    collection_warning,
    write_aggregation_report,
    write_prisma_report,
)
from scilex.pipeline.tracker import FilteringTracker
from scilex.quality_validation import (
    apply_quality_filters,
    generate_data_completeness_report,
)
from scilex.since_utils import (
    find_since_collections,
    parse_since,
    prepare_since_config,
)

logger = logging.getLogger(__name__)


# Progress phase of the LLM screening; percents are inside this range of the
# overall aggregation progress.
SCREENING_PHASE = "screening"
SCREENING_PERCENT_RANGE = (45, 55)


class AggregationCancelled(Exception):
    """Raised by run_aggregation() when ``options.cancel_event`` was set."""


@dataclass
class AggregationOptions:
    """Options for run_aggregation(), replacing argparse arguments."""

    skip_citations: bool = False
    workers: int = 2
    resume: bool = False
    no_cache: bool = False
    checkpoint_interval: int = 100
    parallel_workers: int | None = None
    batch_size: int = 5000
    profile: bool = False
    # Abstract enrichment pre-step (Semantic Scholar / OpenAlex by DOI)
    no_abstract_enrichment: bool = False
    cache_only_enrichment: bool = False
    enrich_workers: int = 4
    # Workers for JSON file loading (None = parallel_aggregate default)
    load_workers: int | None = None
    # Set to stop the run at the next checkpoint (between stages, between LLM
    # requests); run_aggregation then raises AggregationCancelled.
    cancel_event: threading.Event | None = None


def run_collection(
    config: SciLExConfig,
    progress_callback: Callable | None = None,
    cancel_event=None,
    run_label: str = "new run",
) -> None:
    """Run paper collection programmatically.

    Warnings and errors raised during the run are also written to
    ``{output_dir}/{collect_name}/collect_errors.log`` (with a session header
    and footer) so they survive the console progress bar.

    Args:
        config: Loaded SciLExConfig instance.
        progress_callback: Optional callback(api_stats, completed, total).
        cancel_event: Optional threading.Event to signal cancellation.
        run_label: Short description written in the error-log session header
            (e.g. "new run" or "resumed: <collection>").
    """
    main_config = config.main
    api_config = config.api

    # Incremental re-collection: restrict years, redirect to the since directory
    since = parse_since(main_config.get("since", DEFAULT_SINCE))
    if since:
        main_config = prepare_since_config(main_config, since)
        logger.info(
            f"Since-run from {since.isoformat()}: years {main_config['years']}, "
            f"collection {main_config['collect_name']}"
        )

    output_dir = main_config.get("output_dir", DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    # Resolve collection directory and attach the error log file
    collect_name = main_config.get("collect_name", "unknown")
    dir_collect = os.path.join(output_dir, collect_name)
    os.makedirs(dir_collect, exist_ok=True)
    log_path = os.path.join(dir_collect, "collect_errors.log")
    file_handler = add_file_log_handler(log_path, level=logging.WARNING)

    # Session-start separator (written directly so it is always present)
    separator = "=" * 70
    apis = main_config.get("apis", [])
    years = main_config.get("years", [])
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n{separator}\n")
        log_file.write(
            f"=== SciLEx collect — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            f" ({run_label}) ===\n"
        )
        log_file.write(f"    APIs: {', '.join(apis)}\n")
        log_file.write(f"    Years: {', '.join(str(y) for y in years)}\n")
        log_file.write(f"{separator}\n")
    logger.info(f"Error log: {log_path}")

    session_start = datetime.now()
    try:
        # CollectCollection handles writing config_used.yml to the correct
        # {output_dir}/{collect_name}/ subdirectory — no duplicate write needed here.
        collector = CollectCollection(
            main_config,
            api_config,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
        collector.create_collects_jobs()
    finally:
        session_end = datetime.now()
        elapsed = (session_end - session_start).total_seconds()
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(
                f"=== Run ended — {session_end.strftime('%Y-%m-%d %H:%M:%S')}"
                f" (duration: {elapsed / 60:.1f} min) ===\n\n"
            )
        logging.getLogger().removeHandler(file_handler)
        file_handler.close()


@dataclass
class _AggregationContext:
    """Values shared by every step of run_aggregation()."""

    options: AggregationOptions
    progress_callback: Callable[[str, int, str], None] | None
    run_start: datetime
    main_config: dict
    api_config: dict
    quality_filters: dict
    dir_collect: str
    collect_name: str
    output_filename: str
    get_citation: bool
    keyword_groups: list
    bonus_keywords: list | None
    tracker: FilteringTracker

    def report_progress(self, phase: str, percent: int, message: str) -> None:
        """Forward a progress update to the optional callback."""
        if self.progress_callback:
            self.progress_callback(phase, percent, message)


def _build_context(
    config: SciLExConfig,
    options: AggregationOptions,
    progress_callback: Callable[[str, int, str], None] | None,
) -> _AggregationContext:
    """Resolve paths, flags and shared settings from the configuration.

    Args:
        config: Loaded SciLExConfig instance.
        options: Aggregation options.
        progress_callback: Optional callback(phase, progress_pct, message).

    Returns:
        The shared context. ``quality_filters`` is a fresh dict (defaults merged
        with the user's values, see ``SciLExConfig.quality_filters``): the
        ``year_range`` auto-population done later is not visible to the caller.
    """
    main_config = config.main
    output_dir = main_config.get("output_dir", DEFAULT_OUTPUT_DIR)
    collect_name = normalize_path_component(main_config.get("collect_name"))
    return _AggregationContext(
        options=options,
        progress_callback=progress_callback,
        run_start=datetime.now(),
        main_config=main_config,
        api_config=config.api,
        # SciLExConfig property: user overrides merged with defaults
        quality_filters=config.quality_filters,
        dir_collect=os.path.join(output_dir, collect_name),
        collect_name=collect_name,
        output_filename=normalize_path_component(
            main_config.get("aggregate_file", DEFAULT_AGGREGATED_FILENAME)
        ),
        get_citation=bool(
            main_config.get("aggregate_get_citations", True)
            and not options.skip_citations
        ),
        keyword_groups=main_config.get("keywords", []),
        bonus_keywords=main_config.get("bonus_keywords", None),
        tracker=FilteringTracker(),
    )


def _load_collection_metadata(dir_collect: str) -> dict:
    """Load the ``config_used.yml`` snapshot written at collection time.

    Args:
        dir_collect: Collection directory.

    Returns:
        The parsed snapshot.

    Raises:
        FileNotFoundError: If the collection has no metadata snapshot.
    """
    config_used_path = os.path.join(dir_collect, "config_used.yml")
    if not os.path.isfile(config_used_path):
        raise FileNotFoundError(
            f"No collection metadata found in: {dir_collect}. "
            f"Run collection first or check 'collect_name' in scilex.config.yml"
        )
    with open(config_used_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _enrich_source_abstracts(ctx: _AggregationContext) -> None:
    """Pre-step: patch missing abstracts in the collected files by DOI.

    Args:
        ctx: Shared aggregation context.
    """
    if ctx.options.no_abstract_enrichment:
        logging.info("Abstract enrichment skipped")
        return

    from scilex.abstract_enrichment import enrich_collection_abstracts

    ss_key = first_key((ctx.api_config or {}).get("SemanticScholar", {}).get("api_key"))
    enrich_stats = enrich_collection_abstracts(
        ctx.dir_collect,
        ss_api_key=ss_key,
        num_workers=ctx.options.enrich_workers,
        cache_only=ctx.options.cache_only_enrichment,
        # Skip papers the year pre-filter will drop anyway (matters for ORKG,
        # which has no server-side year filter).
        year_range=_year_range_set(ctx),
    )
    if enrich_stats["dois_found"] > 0:
        logging.info(
            f"Abstract enrichment complete: "
            f"{enrich_stats['enriched']}/{enrich_stats['dois_found']} abstracts available "
            f"({enrich_stats.get('cache_hits', 0)} from cache, "
            f"{enrich_stats.get('newly_fetched', 0)} newly fetched), "
            f"{enrich_stats['patched_records']} records updated in source files"
        )


def _year_range_set(ctx: _AggregationContext) -> set[int] | None:
    """Years kept by aggregation, shared by abstract enrichment and the pre-filters.

    Derived from the main config's "years" list (same list used during
    collection); quality_filters.year_range can override it explicitly.
    """
    year_list = ctx.quality_filters.get("year_range") or ctx.main_config.get(
        "years", []
    )
    return {int(y) for y in year_list} if year_list else None


def _build_pre_filters(ctx: _AggregationContext) -> dict:
    """Build the cheap early filters pushed into the batch workers.

    Papers failing the year or itemType criteria then never reach text
    filtering or deduplication.

    Args:
        ctx: Shared aggregation context.

    Returns:
        Dict with optional ``allowed_item_types`` and ``year_range`` sets
        (empty when no early filter applies).
    """
    quality_filters = ctx.quality_filters
    pre_filters: dict = {}
    if quality_filters.get("enable_itemtype_filter", False) and quality_filters.get(
        "allowed_item_types", []
    ):
        pre_filters["allowed_item_types"] = set(quality_filters["allowed_item_types"])

    year_range = _year_range_set(ctx)
    if year_range:
        pre_filters["year_range"] = year_range

    if pre_filters:
        logging.info(
            "Pre-filters configured for batch workers: "
            + (
                f"itemTypes={sorted(pre_filters['allowed_item_types'])} "
                if "allowed_item_types" in pre_filters
                else ""
            )
            + (
                f"years={sorted(pre_filters['year_range'])}"
                if "year_range" in pre_filters
                else ""
            )
        )
    return pre_filters


def _log_performance_stats(parallel_stats: dict) -> None:
    """Log the per-stage statistics of the parallel aggregation (``--profile``).

    Args:
        parallel_stats: Stage name to stats dict, as returned by
            ``parallel_aggregate``.
    """
    logging.info("\n" + "=" * 70)
    logging.info("PERFORMANCE STATISTICS")
    logging.info("=" * 70)
    for stage, stats in parallel_stats.items():
        logging.info(f"\n{stage.upper()}:")
        for key, value in stats.items():
            if isinstance(value, float):
                logging.info(f"  {key}: {value:.2f}")
            else:
                logging.info(
                    f"  {key}: {value:,}"
                    if isinstance(value, int)
                    else f"  {key}: {value}"
                )
    logging.info("=" * 70 + "\n")


def _load_and_deduplicate(
    ctx: _AggregationContext, config_used: dict
) -> tuple[pd.DataFrame, dict]:
    """Load, convert, text-filter and deduplicate the collected papers.

    Also merges the ``<collect>_since_<date>/`` incremental collections.

    Args:
        ctx: Shared aggregation context.
        config_used: Collection metadata snapshot.

    Returns:
        Tuple of the deduplicated DataFrame and the parallel-stage statistics.
    """
    from scilex.crawlers.aggregate_parallel import parallel_aggregate

    ctx.report_progress("aggregating", 10, "Running parallel aggregation...")

    # In cache-only mode, load the SQLite abstract cache once so workers can
    # inject abstracts on the fly.
    cached_abstracts: dict | None = None
    if ctx.options.cache_only_enrichment:
        from scilex.abstract_enrichment import load_all_cached_abstracts

        logging.info(
            "Loading abstract cache for inline injection during aggregation..."
        )
        cached_abstracts = load_all_cached_abstracts(ctx.dir_collect)
        logging.info(f"  {len(cached_abstracts):,} cached abstracts loaded")

    pre_filters = _build_pre_filters(ctx)
    df, parallel_stats = parallel_aggregate(
        dir_collect=ctx.dir_collect,
        config_used=config_used,
        txt_filters=True,
        num_workers=ctx.options.parallel_workers,
        batch_size=ctx.options.batch_size,
        keyword_groups=ctx.keyword_groups,
        load_workers=ctx.options.load_workers,
        bonus_keywords=ctx.bonus_keywords if ctx.bonus_keywords else None,
        cached_abstracts=cached_abstracts,
        pre_filters=pre_filters if pre_filters else None,
        since_collect_dirs=find_since_collections(ctx.dir_collect),
    )

    if ctx.options.profile:
        _log_performance_stats(parallel_stats)
    return df, parallel_stats


def _recover_dois_and_fill_urls(
    ctx: _AggregationContext, df: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    """Recover missing DOIs (opt-in, CrossRef) then derive missing URLs from DOIs.

    Args:
        ctx: Shared aggregation context.
        df: Deduplicated papers.

    Returns:
        Tuple of the updated DataFrame and the URL fallback statistics.
    """
    quality_filters = ctx.quality_filters
    if quality_filters.get("recover_missing_dois", DEFAULT_RECOVER_MISSING_DOIS):
        from scilex.pipeline.doi_recovery import recover_missing_dois

        logging.info("\n=== DOI Recovery (CrossRef) ===")
        df, _doi_stats = recover_missing_dois(
            df,
            min_similarity=quality_filters.get(
                "doi_recovery_min_similarity", DEFAULT_DOI_RECOVERY_MIN_SIMILARITY
            ),
            mailto=(ctx.api_config or {}).get("CrossRef", {}).get("mailto"),
            cache_path=os.path.join(ctx.dir_collect, "doi_recovery_cache.json"),
        )

    logging.info("\n=== URL Fallback from DOI ===")
    return fill_missing_urls_from_doi(df)


def _apply_itemtype_whitelist(
    ctx: _AggregationContext, df: pd.DataFrame
) -> pd.DataFrame:
    """Keep only the whitelisted itemTypes when the filter is enabled.

    Args:
        ctx: Shared aggregation context.
        df: Papers to filter.

    Returns:
        The filtered DataFrame (possibly empty).
    """
    if not ctx.quality_filters.get("enable_itemtype_filter", False):
        logging.info("ItemType filtering: DISABLED (all itemTypes allowed)")
        return df

    allowed_item_types = ctx.quality_filters.get("allowed_item_types", [])
    logging.info("\n=== ItemType Filtering (Whitelist Mode) ===")
    df, _itemtype_stats = apply_itemtype_filter(df, allowed_item_types, True)
    ctx.tracker.add_stage(
        "ItemType Filter",
        len(df),
        f"Whitelist filtering: Only {len(allowed_item_types)} allowed itemTypes kept",
    )
    if len(df) == 0:
        logging.warning(
            "All papers filtered out by itemType filter. No papers to process."
        )
    return df


def _report_duplicates_and_score(
    ctx: _AggregationContext, df: pd.DataFrame
) -> pd.DataFrame:
    """Report duplicate sources and itemType distribution, add ``quality_score``.

    Args:
        ctx: Shared aggregation context.
        df: Papers after the itemType whitelist.

    Returns:
        ``df`` with the new ``quality_score`` column.
    """
    generate_quality_report = ctx.quality_filters.get("generate_quality_report", True)

    if ctx.quality_filters.get("track_duplicate_sources", True):
        logging.info("Analyzing duplicate sources and API overlap...")
        analyze_and_report_duplicates(df, generate_report=generate_quality_report)

    if generate_quality_report:
        logging.info("Generating itemType distribution report...")
        logging.info(generate_itemtype_distribution_report(df))

    logging.info("Calculating quality scores...")
    df["quality_score"] = quality_scores(df)
    return df


def _apply_quality_filters_with_bypass(
    ctx: _AggregationContext, df: pd.DataFrame
) -> pd.DataFrame:
    """Split off bypass itemTypes, quality-filter the rest, then merge back.

    Args:
        ctx: Shared aggregation context.
        df: Scored papers.

    Returns:
        The papers that passed (bypass papers first, then filtered ones).
    """
    quality_filters = ctx.quality_filters
    bypass_item_types = quality_filters.get("bypass_item_types", [])
    enable_bypass = quality_filters.get("enable_itemtype_bypass", False)

    if enable_bypass and bypass_item_types:
        logging.info("\n=== ItemType Bypass Filter ===")
        df_bypass, df_non_bypass = apply_itemtype_bypass(df, bypass_item_types)
        # The split removes nothing: record the total so the next stage's
        # removal count (non-bypass papers rejected) is not negative.
        ctx.tracker.add_stage(
            "ItemType Bypass Split",
            len(df),
            f"Split: {len(df_bypass):,} high-quality papers auto-pass ({', '.join(bypass_item_types)}), "
            f"{len(df_non_bypass):,} papers continue through quality validation",
        )
    else:
        df_bypass = pd.DataFrame()
        df_non_bypass = df

    if quality_filters and len(df_non_bypass) > 0:
        logging.info("Applying quality filters to non-bypass papers...")
        df_filtered, _quality_report = apply_quality_filters(
            df_non_bypass,
            quality_filters,
            quality_filters.get("generate_quality_report", True),
        )
        logging.info(
            f"After quality filtering: {len(df_filtered)} papers remaining "
            f"(from {len(df_non_bypass)} non-bypass papers)"
        )

        if len(df_bypass) > 0:
            df = pd.concat([df_bypass, df_filtered], ignore_index=True)
            logging.info(
                f"Merged: {len(df_bypass)} bypass + {len(df_filtered)} filtered = {len(df)} total papers"
            )
        else:
            df = df_filtered

        ctx.tracker.add_stage(
            "Quality Filter",
            len(df),
            "Papers meeting quality requirements (DOI, abstract, year, author count, etc.)",
        )
    elif enable_bypass and bypass_item_types:
        # Nothing went through quality validation (all papers bypassed, or no
        # quality filters): record the kept total so the last tracker stage
        # matches the papers that continue down the pipeline.
        ctx.tracker.add_stage(
            "Quality Filter",
            len(df),
            "No quality validation applied: bypassed papers kept as-is",
        )
    return df


def _report_and_filter_abstracts(
    ctx: _AggregationContext, df: pd.DataFrame
) -> pd.DataFrame:
    """Log completeness/keyword reports and apply the abstract quality filter.

    Args:
        ctx: Shared aggregation context.
        df: Papers after the quality filters.

    Returns:
        The papers with acceptable abstracts (unchanged if the filter is off).
    """
    quality_filters = ctx.quality_filters
    generate_quality_report = quality_filters.get("generate_quality_report", True)

    if generate_quality_report:
        logging.info(generate_data_completeness_report(df))

    if ctx.keyword_groups and generate_quality_report:
        logging.info(
            generate_keyword_validation_report(
                df,
                ctx.keyword_groups,
                bonus_keywords=ctx.bonus_keywords if ctx.bonus_keywords else None,
            )
        )

    if not quality_filters.get("validate_abstracts", False):
        return df

    logging.info("Validating abstract quality...")
    min_quality_score = quality_filters.get(
        "min_abstract_quality_score", MIN_ABSTRACT_QUALITY_SCORE
    )
    # Score every abstract once, then filter on the same acceptability mask
    df_scored, _abstract_stats = validate_dataframe_abstracts(
        df,
        min_quality_score=min_quality_score,
        generate_report=generate_quality_report,
        min_words=quality_filters.get("min_abstract_words", MIN_ABSTRACT_WORDS),
        max_words=quality_filters.get("max_abstract_words", MAX_ABSTRACT_WORDS),
    )
    if "abstract_quality_acceptable" in df_scored.columns:
        df = df_scored[df_scored["abstract_quality_acceptable"]].drop(
            columns=SCORING_COLUMNS
        )
    logging.info(f"After abstract quality filtering: {len(df)} papers remaining")
    ctx.tracker.add_stage(
        "Abstract Quality Filter",
        len(df),
        f"Abstracts meeting quality threshold (min score: {min_quality_score})",
    )
    return df


def _screen_with_llm(ctx: _AggregationContext, df: pd.DataFrame) -> pd.DataFrame:
    """Optional LLM abstract screening, run after the keyword/quality filters.

    Args:
        ctx: Shared aggregation context.
        df: Papers after abstract validation.

    Returns:
        The screened papers (unchanged when screening is disabled).
    """
    screening_config = LLMScreeningConfig.from_dict(
        ctx.main_config.get("llm_screening")
    )
    if not (screening_config.enabled and len(df) > 0):
        return df

    logging.info("\n=== LLM Abstract Screening ===")
    df = apply_llm_screening(
        df,
        screening_config,
        api_config=ctx.api_config,
        cache_path=os.path.join(ctx.dir_collect, CACHE_FILENAME),
        cancel_event=ctx.options.cancel_event,
        progress_callback=lambda done, total: ctx.report_progress(
            SCREENING_PHASE,
            SCREENING_PERCENT_RANGE[0]
            + round(
                (SCREENING_PERCENT_RANGE[1] - SCREENING_PERCENT_RANGE[0])
                * done
                / max(total, 1)
            ),
            f"LLM screening… {done}/{total} papers",
        ),
    )
    _check_cancelled(ctx)
    if screening_config.threshold is not None:
        ctx.tracker.add_stage(
            "LLM Screening",
            len(df),
            f"Papers with llm_relevance_score >= {screening_config.threshold}",
        )
    return df


def _process_citations(
    ctx: _AggregationContext, df: pd.DataFrame
) -> tuple[pd.DataFrame, dict | None]:
    """Fetch citations, resolve the canonical count and apply the age filter.

    Args:
        ctx: Shared aggregation context.
        df: Papers after screening.

    Returns:
        Tuple of the updated DataFrame and the fetch statistics (None when
        citations are disabled or there is nothing to fetch).
    """
    if not ctx.get_citation:
        return df, None
    if len(df) == 0:
        logging.warning("Skipping citation fetching - no papers to process")
        return df, None

    from scilex.citations.fetcher import fetch_citations_for_dataframe

    quality_filters = ctx.quality_filters
    checkpoint_path = os.path.join(ctx.dir_collect, "citation_checkpoint.json")
    crossref_mailto = ctx.api_config.get("CrossRef", {}).get("mailto")

    extras, nb_citeds, nb_citations, stats = fetch_citations_for_dataframe(
        df,
        num_workers=ctx.options.workers,
        checkpoint_interval=ctx.options.checkpoint_interval,
        checkpoint_path=checkpoint_path,
        resume=ctx.options.resume,
        use_cache=not ctx.options.no_cache,
        crossref_mailto=crossref_mailto,
        # Shared by every collection of the output folder; never cwd-relative.
        cache_dir=os.path.dirname(ctx.dir_collect),
        use_opencitations=quality_filters.get("use_opencitations", True),
    )

    df["extra"] = extras
    df["nb_cited"] = nb_citeds
    df["nb_citation"] = nb_citations

    total_with_doi = stats["success"] + stats["error"] + stats["timeout"]
    if total_with_doi > 0:
        failure_rate = (stats["error"] + stats["timeout"]) / total_with_doi * 100
        if failure_rate > 10:
            logging.warning(
                f"High failure rate: {failure_rate:.1f}% of API calls failed"
            )

    if quality_filters.get("use_semantic_scholar_citations", True):
        df = use_semantic_scholar_citations_fallback(df)

    if quality_filters.get("use_openalex_citations", True):
        df = use_openalex_citations_fallback(df)

    df = apply_canonical_citations(
        df,
        quality_filters.get(
            "canonical_citation_discrepancy_threshold",
            DEFAULT_CANONICAL_CITATION_DISCREPANCY_THRESHOLD,
        ),
    )

    if quality_filters.get("apply_citation_filter", True):
        df = apply_time_aware_citation_filter(df)
        ctx.tracker.add_stage(
            "Citation Filter",
            len(df),
            "Papers meeting time-aware citation thresholds",
        )

    with contextlib.suppress(OSError):
        os.remove(checkpoint_path)
    return df, stats


def _enrich_metadata(ctx: _AggregationContext, df: pd.DataFrame) -> pd.DataFrame:
    """Opt-in enrichments: Unpaywall OA status, author h-index, venue rank.

    Args:
        ctx: Shared aggregation context.
        df: Papers after the citation step.

    Returns:
        The enriched DataFrame (unchanged when empty or all enrichments off).
    """
    if len(df) == 0:
        return df

    quality_filters = ctx.quality_filters
    api_config = ctx.api_config or {}

    if quality_filters.get("enrich_unpaywall", DEFAULT_ENRICH_UNPAYWALL):
        from scilex.pipeline.open_access import enrich_with_unpaywall

        unpaywall_email = (
            quality_filters.get("unpaywall_email")
            or api_config.get("Unpaywall", {}).get("email")
            or DEFAULT_UNPAYWALL_EMAIL
        )
        df = enrich_with_unpaywall(df, unpaywall_email)

    if quality_filters.get("enrich_author_hindex", DEFAULT_ENRICH_AUTHOR_HINDEX):
        from scilex.pipeline.author_metrics import enrich_with_author_hindex

        semantic_scholar_key = api_config.get("SemanticScholar", {}).get("api_key")
        df = enrich_with_author_hindex(df, api_key=semantic_scholar_key)

    if quality_filters.get("use_venue_ranking", DEFAULT_USE_VENUE_RANKING):
        from scilex.pipeline.venue_ranking import add_venue_rank

        df = add_venue_rank(df)
    return df


def _rank_papers(ctx: _AggregationContext, df: pd.DataFrame) -> pd.DataFrame:
    """Apply the composite relevance ranking when enabled.

    Args:
        ctx: Shared aggregation context.
        df: Enriched papers.

    Returns:
        The ranked (and possibly truncated) DataFrame.
    """
    quality_filters = ctx.quality_filters
    if not quality_filters.get("apply_relevance_ranking", True):
        return df

    top_n = quality_filters.get("max_papers", None)
    df = apply_relevance_ranking(
        df,
        keyword_groups=ctx.keyword_groups,
        top_n=top_n,
        has_citations=ctx.get_citation and len(df) > 0,
        config={
            **ctx.main_config,
            "quality_filters": {
                **(ctx.main_config.get("quality_filters") or {}),
                "use_venue_ranking": quality_filters.get(
                    "use_venue_ranking", DEFAULT_USE_VENUE_RANKING
                ),
            },
        },
        bonus_keywords=ctx.bonus_keywords,
    )
    ctx.tracker.add_stage(
        "Relevance Ranking",
        len(df),
        f"{'Top ' + str(top_n) + ' ' if top_n else ''}Papers ranked by normalized relevance score (0-10 scale)",
    )
    return df


def _write_filtering_summary(ctx: _AggregationContext) -> None:
    """Log the filtering report and save it as ``filtering_summary.json``.

    Args:
        ctx: Shared aggregation context.
    """
    tracker = ctx.tracker
    logging.info(tracker.generate_report())

    summary_data = {
        "initial_count": tracker.initial_count,
        "final_count": tracker.stages[-1]["papers"] if tracker.stages else 0,
        "stages": tracker.stages,
    }
    summary_path = os.path.join(ctx.dir_collect, "filtering_summary.json")
    try:
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
        logging.info(f"Filtering summary saved to {summary_path}")
    except OSError as e:
        logging.warning(f"Could not save filtering summary: {e}")


def _write_results(
    ctx: _AggregationContext,
    df: pd.DataFrame,
    parallel_stats: dict,
    citation_stats: dict | None,
    url_stats: dict,
) -> pd.DataFrame:
    """Tag bonus keywords, write the CSV, the aggregation report and PRISMA.

    Args:
        ctx: Shared aggregation context.
        df: Final ranked papers.
        parallel_stats: Statistics of the parallel aggregation.
        citation_stats: Citation fetch statistics (None if not fetched).
        url_stats: URL fallback statistics.

    Returns:
        ``df`` with the ``bonus_keyword_tags`` column.
    """
    if ctx.bonus_keywords:
        logging.info("Tagging papers with bonus keywords...")
        df = tag_papers_with_bonus_keywords(df, ctx.bonus_keywords)
        generate_bonus_keyword_stats(df, ctx.bonus_keywords)
    else:
        df["bonus_keyword_tags"] = ""

    output_path = os.path.join(ctx.dir_collect, ctx.output_filename)
    logging.info(f"Saving {len(df)} aggregated papers to {output_path}")
    write_aggregated_csv(df, output_path, quoting=csv.QUOTE_NONNUMERIC)
    logging.info(f"Aggregation complete! Results saved to {output_path}")

    warning_lines = collection_warning(ctx.dir_collect, ctx.main_config)
    write_aggregation_report(
        dir_collect=ctx.dir_collect,
        collect_name=ctx.collect_name,
        run_date=ctx.run_start,
        duration_seconds=(datetime.now() - ctx.run_start).total_seconds(),
        main_config=ctx.main_config,
        parallel_stats=parallel_stats,
        filtering_tracker=ctx.tracker,
        citation_stats=citation_stats,
        url_stats=url_stats,
        df_clean=df,
        collection_warning_lines=warning_lines,
    )

    # PRISMA 2020 flow report (reuses the tracker and parallel stats numbers)
    if ctx.main_config.get("generate_prisma_report", DEFAULT_GENERATE_PRISMA_REPORT):
        try:
            write_prisma_report(
                dir_collect=ctx.dir_collect,
                collect_name=ctx.collect_name,
                run_date=ctx.run_start,
                parallel_stats=parallel_stats,
                filtering_tracker=ctx.tracker,
                final_count=len(df),
                collection_warning_lines=warning_lines,
            )
        except OSError as e:
            logging.warning(f"Could not write PRISMA report: {e}")
    return df


def _check_cancelled(ctx: _AggregationContext) -> None:
    """Raise AggregationCancelled if the caller asked to stop."""
    event = ctx.options.cancel_event
    if event is not None and event.is_set():
        raise AggregationCancelled("Aggregation cancelled")


def _log_collection_status(ctx: _AggregationContext) -> None:
    """Print the collection completeness report (best effort)."""
    try:
        from scilex.collect_status import build_status, print_status

        print_status(build_status(ctx.dir_collect, ctx.main_config))
    except Exception as e:
        logging.warning(f"Could not build collection status report: {e}")


def _autopopulate_year_range(ctx: _AggregationContext) -> None:
    """Default ``quality_filters['year_range']`` to the configured years."""
    quality_filters = ctx.quality_filters
    if quality_filters.get("validate_year_range", False):
        year_range = quality_filters.get("year_range", [])
        if not year_range:
            year_range = ctx.main_config.get("years", [])
            quality_filters["year_range"] = year_range
            logging.info(f"Auto-populated year_range from main config: {year_range}")


def run_aggregation(
    config: SciLExConfig,
    options: AggregationOptions | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> pd.DataFrame:
    """Run the full aggregation pipeline programmatically.

    This is the core function that replaces the body of aggregate_collect.main().
    It can be called from CLI, web API, or tests without sys.argv manipulation.

    Args:
        config: Loaded SciLExConfig instance.
        options: Aggregation options (defaults applied if None).
        progress_callback: Optional callback(phase, progress_pct, message).

    Returns:
        pd.DataFrame: The aggregated and filtered results.

    Raises:
        FileNotFoundError: If the collection has no ``config_used.yml``.
    """
    ctx = _build_context(config, options or AggregationOptions(), progress_callback)

    logging.info(f"Collection directory: {ctx.dir_collect}")
    logging.info(f"Citation fetching: {'enabled' if ctx.get_citation else 'disabled'}")
    ctx.report_progress("initializing", 5, "Loading configuration...")
    _log_collection_status(ctx)
    _autopopulate_year_range(ctx)
    config_used = _load_collection_metadata(ctx.dir_collect)

    _enrich_source_abstracts(ctx)
    _check_cancelled(ctx)
    df, parallel_stats = _load_and_deduplicate(ctx, config_used)
    _check_cancelled(ctx)
    ctx.tracker.set_initial(len(df), "Papers after deduplication")

    ctx.report_progress("filtering", 30, "Applying filters...")
    df, url_stats = _recover_dois_and_fill_urls(ctx, df)
    _check_cancelled(ctx)
    df = _apply_itemtype_whitelist(ctx, df)
    if len(df) == 0:
        return df

    df = _report_duplicates_and_score(ctx, df)
    _check_cancelled(ctx)
    ctx.report_progress("filtering", 45, "Applying quality filters...")
    df = _apply_quality_filters_with_bypass(ctx, df)
    df = _report_and_filter_abstracts(ctx, df)
    _check_cancelled(ctx)
    df = _screen_with_llm(ctx, df)
    _check_cancelled(ctx)

    ctx.report_progress("citations", 55, "Fetching citations...")
    df, citation_stats = _process_citations(ctx, df)
    _check_cancelled(ctx)
    df = _enrich_metadata(ctx, df)
    _check_cancelled(ctx)

    ctx.report_progress("ranking", 85, "Applying relevance ranking...")
    df = _rank_papers(ctx, df)

    _write_filtering_summary(ctx)
    df = _write_results(ctx, df, parallel_stats, citation_stats, url_stats)

    ctx.report_progress("completed", 100, "Aggregation completed!")
    return df
