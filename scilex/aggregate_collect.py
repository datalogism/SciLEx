import argparse
import logging
import sys

from scilex.config import SciLExConfig
from scilex.logging_config import log_section, setup_logging
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)


@exit_on_config_error
def main():
    """CLI entry point for aggregation. Thin wrapper around run_aggregation()."""
    from scilex.pipeline.orchestrator import AggregationOptions, run_aggregation

    # Set up logging
    setup_logging()

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Aggregate collected papers and fetch citations"
    )
    parser.add_argument(
        "--collection",
        metavar="COLLECT",
        default=None,
        help=(
            "Aggregate a specific collection by name or full path. "
            "Loads config_used.yml from that directory. "
            "If omitted, uses collect_name from scilex.config.yml."
        ),
    )
    parser.add_argument(
        "--use-current-config",
        action="store_true",
        help=(
            "Replay mode, with --collection: aggregate that collection with the "
            "current scilex.yml (filters, ranking, keywords) instead of its "
            "config_used.yml snapshot. Without --collection the current "
            "scilex.yml is always used."
        ),
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume from checkpoint if available"
    )
    parser.add_argument(
        "--skip-citations", action="store_true", help="Skip citation fetching entirely"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable citation caching (slower - not recommended)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Number of parallel workers for citation fetching (default: 2)",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=100,
        help="Save checkpoint every N papers (default: 100)",
    )
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=None,
        help="Number of parallel workers for batch processing (default: auto-detect CPU count - 1)",
    )
    parser.add_argument(
        "--load-workers",
        type=int,
        default=None,
        help="Number of parallel workers for JSON file loading (default: 4). "
        "Increase for fast local filesystems; keep low for WSL2/network paths.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Papers per batch for parallel processing (default: 5000)",
    )
    parser.add_argument(
        "--profile", action="store_true", help="Output detailed performance statistics"
    )
    parser.add_argument(
        "--no-abstract-enrichment",
        action="store_true",
        help=(
            "Skip abstract enrichment step entirely. By default, records without abstracts "
            "(e.g. from Elsevier, ORKG) are enriched via Semantic Scholar / OpenAlex "
            "before aggregation, and the fetched abstracts are saved back to the "
            "source JSON files."
        ),
    )
    parser.add_argument(
        "--cache-only-enrichment",
        action="store_true",
        help=(
            "Apply only already-cached abstracts during enrichment — no network calls. "
            "Useful for fast re-aggregations when the cache is already warm. "
            "Ignored if --no-abstract-enrichment is set."
        ),
    )
    parser.add_argument(
        "--enrich-workers",
        type=int,
        default=4,
        help="Parallel workers for abstract enrichment HTTP requests (default: 4)",
    )
    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)

    logger = logging.getLogger(__name__)

    # Load configuration (from a previous collection's snapshot if --collection)
    try:
        config = SciLExConfig.from_collection(
            args.collection, use_current_config=args.use_current_config
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Log aggregation start
    log_section(logger, "SciLEx Data Aggregation")

    # Build options from CLI args
    options = AggregationOptions(
        skip_citations=args.skip_citations,
        workers=args.workers,
        resume=args.resume,
        no_cache=args.no_cache,
        checkpoint_interval=args.checkpoint_interval,
        parallel_workers=args.parallel_workers,
        batch_size=args.batch_size,
        profile=args.profile,
        no_abstract_enrichment=args.no_abstract_enrichment,
        cache_only_enrichment=args.cache_only_enrichment,
        enrich_workers=args.enrich_workers,
        load_workers=args.load_workers,
    )

    # Run the pipeline
    run_aggregation(config, options)


if __name__ == "__main__":
    main()
