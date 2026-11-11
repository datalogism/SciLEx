#!/usr/bin/env python3
"""Enrich aggregated papers with Papers with Code metadata (``scilex-enrich``).

This command:
1. Reads aggregated_results.csv
2. For each paper: looks it up on Papers with Code (arXiv ID, then title)
3. Adds columns: tags, pwc_url, github_repo
4. Writes updated CSV back

Examples:
    scilex-enrich                                   # collect dir from config
    scilex-enrich --collect-dir output/my_collect   # explicit collect dir
    scilex-enrich --dry-run                         # show matches only
    scilex-enrich --limit 100                       # first 100 papers only
"""

import argparse
import logging
import sys

from scilex.config import SciLExConfig
from scilex.logging_config import setup_logging
from scilex.pipeline.enrichment_pwc import EnrichmentOptions, run_enrichment
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.schema import ConfigFileNotFoundError, SettingsError

logger = logging.getLogger(__name__)


@exit_on_config_error
def main():
    """Command-line entry point for CSV enrichment."""
    parser = argparse.ArgumentParser(
        description="Enrich aggregated CSV with Papers with Code metadata"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show matches without updating CSV",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum papers to process",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help=(
            "Fuzzy matching threshold (0-100). Overrides "
            "enrichment.paperswithcode.fuzzy_match_threshold (default: 85)"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "Papers searched concurrently. Overrides "
            "enrichment.paperswithcode.workers (default: 4)"
        ),
    )
    parser.add_argument(
        "--collect-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="Path to the collect directory containing the aggregated CSV "
        "(overrides output_dir + collect_name from config)",
    )

    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)
    setup_logging()

    try:
        config = SciLExConfig.from_files()
        options = EnrichmentOptions(
            dry_run=args.dry_run,
            limit=args.limit,
            threshold=args.threshold,
            workers=args.workers,
            collect_dir=args.collect_dir,
        )
        result = run_enrichment(config, options)
    except (SettingsError, ConfigFileNotFoundError):
        raise  # reported by @exit_on_config_error
    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during enrichment: {e}", exc_info=True)
        sys.exit(1)

    if result.disabled:
        return

    logging.info("=" * 60)
    logging.info("Papers with Code Enrichment Summary")
    logging.info("=" * 60)
    logging.info(f"Total papers: {result.total}")
    logging.info(f"Matched: {result.matched}")
    logging.info(f"Updated: {result.updated}")
    logging.info(f"Skipped: {result.skipped}")
    logging.info("=" * 60)

    if args.dry_run:
        logging.info("✓ Dry run complete. No changes made to CSV.")
    else:
        logging.info("✓ Papers with Code enrichment complete!")


if __name__ == "__main__":
    main()
