"""Extend a SciLEx collection via snowball sampling on citation networks.

Identifies papers outside the corpus that are frequently cited by or cite
corpus papers, fetches their metadata from Semantic Scholar, applies
quality filters, and merges them with the existing collection.

Usage:
    scilex-snowball [--direction both|backward|forward]
                    [--top-k N] [--min-frequency N]
                    [--depth N] [--dry-run] [--separate-file]

The new papers are added to the aggregated file itself
({output_dir}/{collect_name}/aggregated_results.csv), so that Zotero, BibTeX
and Turtle exports include them. The original is kept once as
aggregated_results_pre_snowball.csv. With --separate-file the collection is
left as is and the result goes to aggregated_results_snowball.csv.
"""

import argparse
import logging
import sys

from scilex.config_defaults import (
    DEFAULT_SNOWBALL_DIRECTION,
    DEFAULT_SNOWBALL_MIN_FREQUENCY,
    DEFAULT_SNOWBALL_TOP_K,
)
from scilex.crawlers.key_pool import first_key
from scilex.graph_analysis.loader import load_citation_caches
from scilex.io_utils import load_aggregated_data, resolve_aggregate_path
from scilex.logging_config import setup_logging
from scilex.pipeline_utils import (
    extract_corpus_dois,
    load_main_and_api_configs,
    resolve_collect_dir,
)
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.schema import ConfigFileNotFoundError, SettingsError
from scilex.snowball.candidates import extract_candidates
from scilex.snowball.fetcher import fetch_metadata_batch
from scilex.snowball.filter import apply_snowball_filters
from scilex.snowball.merge import merge_with_corpus, write_snowball_output

setup_logging()
logger = logging.getLogger(__name__)


@exit_on_config_error
def main():
    """Entry point for snowball sampling."""
    parser = argparse.ArgumentParser(
        description="Extend collection via snowball sampling on citation networks"
    )
    parser.add_argument(
        "--direction",
        choices=["both", "backward", "forward"],
        default=DEFAULT_SNOWBALL_DIRECTION,
        help=f"Citation direction to follow (default: {DEFAULT_SNOWBALL_DIRECTION})",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_SNOWBALL_TOP_K,
        help=f"Maximum candidates to fetch (default: {DEFAULT_SNOWBALL_TOP_K})",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=DEFAULT_SNOWBALL_MIN_FREQUENCY,
        help=f"Minimum corpus connections (default: {DEFAULT_SNOWBALL_MIN_FREQUENCY})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates without fetching metadata",
    )
    parser.add_argument(
        "--separate-file",
        action="store_true",
        help="Write aggregated_results_snowball.csv instead of adding the papers "
        "to the collection",
    )
    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)

    try:
        main_config, api_config = load_main_and_api_configs()
        collect_dir = resolve_collect_dir(main_config)

        # Load corpus and citation caches
        corpus_df = load_aggregated_data(main_config, preserve_missing_marker=True)
        corpus_dois = extract_corpus_dois(corpus_df)
        logger.info(f"Corpus: {len(corpus_df)} papers, {len(corpus_dois)} with DOIs")

        references, citers = load_citation_caches(collect_dir)

        # Extract candidates
        candidates = extract_candidates(
            references,
            citers,
            corpus_dois,
            direction=args.direction,
            top_k=args.top_k,
            min_frequency=args.min_frequency,
        )

        if not candidates:
            print("\nNo snowball candidates found. Try lowering --min-frequency.")
            return

        if args.dry_run:
            print(f"\n{'DOI':<60} {'Freq':>5}")
            print("-" * 66)
            for doi, freq in candidates[:50]:
                print(f"{doi:<60} {freq:>5}")
            if len(candidates) > 50:
                print(f"  ... and {len(candidates) - 50} more")
            print(f"\nTotal candidates: {len(candidates)}")
            return

        # Fetch metadata from Semantic Scholar
        ss_api_key = first_key(api_config.get("SemanticScholar", {}).get("api_key"))
        candidate_dois = [doi for doi, _freq in candidates]

        logger.info(f"Fetching metadata for {len(candidate_dois)} candidates...")
        papers = fetch_metadata_batch(candidate_dois, api_key=ss_api_key)
        logger.info(f"Fetched {len(papers)} papers from Semantic Scholar")

        if not papers:
            print(
                f"\nNo metadata could be fetched for the {len(candidate_dois)} "
                "candidates: Semantic Scholar requests failed (often rate limiting "
                "without a key). Add a Semantic Scholar key or try again later."
            )
            return

        # Apply quality filters (no keyword filter)
        filtered_df = apply_snowball_filters(papers)

        if filtered_df.empty:
            print("\nNo papers passed quality filters.")
            return

        # Merge with corpus
        merged_df = merge_with_corpus(corpus_df, filtered_df)

        # Export
        output_csv, backup_csv = write_snowball_output(
            merged_df,
            resolve_aggregate_path(main_config),
            add_to_collection=not args.separate_file,
        )

        separator = "=" * 60
        logger.info(
            "\n".join(
                [
                    separator,
                    "Snowball Sampling Summary",
                    separator,
                    f"Corpus papers:       {len(corpus_df)}",
                    f"Candidates found:    {len(candidates)}",
                    f"Metadata fetched:    {len(papers)}",
                    f"After filters:       {len(filtered_df)}",
                    f"Total merged:        {len(merged_df)}",
                    f"Output:              {output_csv}",
                    f"Backup:              {backup_csv or 'none (collection unchanged)'}",
                    separator,
                ]
            )
        )
        print(f"\nSnowball sampling complete: {output_csv}")

    except (SettingsError, ConfigFileNotFoundError):
        raise  # reported by @exit_on_config_error
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during snowball sampling: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
