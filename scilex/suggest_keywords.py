"""Suggest new search keywords based on cluster analysis.

Extracts frequent terms from clustered papers that are not in the
current search configuration and outputs suggestions as Markdown
and a YAML snippet ready to paste into scilex.config.yml.

Usage:
    scilex-suggest-keywords [--input PATH] [--top-k N] [--min-freq N]

Output is written to:
    {output_dir}/{collect_name}/graph_analysis/keyword_suggestions.md
    {output_dir}/{collect_name}/graph_analysis/keyword_suggestions.yml
"""

import argparse
import logging
import os
import sys

import pandas as pd

from scilex.keyword_suggestions.extractor import (
    configured_keywords,
    extract_suggestions,
)
from scilex.keyword_suggestions.report import generate_keyword_report
from scilex.logging_config import setup_logging
from scilex.pipeline_utils import (
    find_clusters_csv,
    load_main_config,
    resolve_collect_dir,
)
from scilex.settings.cli import (
    add_config_arguments,
    apply_config_arguments,
    exit_on_config_error,
)
from scilex.settings.schema import ConfigFileNotFoundError, SettingsError

setup_logging()
logger = logging.getLogger(__name__)


@exit_on_config_error
def main():
    """Entry point for keyword suggestions."""
    parser = argparse.ArgumentParser(
        description="Suggest new search keywords from cluster analysis"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to clusters CSV (overrides auto-detection)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=30,
        help="Maximum number of suggestions (default: 30)",
    )
    parser.add_argument(
        "--min-freq",
        type=int,
        default=2,
        help="Minimum term frequency (default: 2)",
    )
    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)

    try:
        config = load_main_config()
        collect_dir = resolve_collect_dir(config)
        collect_name = config["collect_name"]
        analysis_dir = os.path.join(collect_dir, "graph_analysis")

        # Find clusters CSV
        csv_path = args.input if args.input else find_clusters_csv(analysis_dir)

        logger.info(f"Input: {csv_path}")

        # Load clusters data
        df = pd.read_csv(csv_path, dtype=str)
        if "cluster_id" in df.columns:
            df["cluster_id"] = (
                pd.to_numeric(df["cluster_id"], errors="coerce").fillna(-1).astype(int)
            )

        existing_keywords = configured_keywords(config)
        logger.info(f"Existing keywords: {len(existing_keywords)}")

        # Extract suggestions
        suggestions = extract_suggestions(
            df,
            existing_keywords,
            top_k=args.top_k,
            min_freq=args.min_freq,
        )

        if not suggestions:
            print("\nNo new keyword suggestions found.")
            return

        # Generate reports
        md_path, yml_path = generate_keyword_report(
            suggestions, analysis_dir, collect_name=collect_name
        )

        print(f"\nKeyword suggestions: {md_path}")
        print(f"YAML snippet: {yml_path}")

    except (SettingsError, ConfigFileNotFoundError):
        raise  # reported by @exit_on_config_error
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during keyword suggestion: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
