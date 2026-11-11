"""Generate summary reports for detected communities.

Reads cluster CSV(s) from graph analysis output and produces
a Markdown report with statistics and Mermaid mindmap.

Usage:
    scilex-summarize [--input PATH]

Output is written to:
    {output_dir}/{collect_name}/graph_analysis/summary_report.md
"""

import argparse
import logging
import os
import sys

import pandas as pd

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
from scilex.summarize.report import generate_report
from scilex.summarize.stats import compute_cluster_stats

setup_logging()
logger = logging.getLogger(__name__)


@exit_on_config_error
def main():
    """Entry point for cluster summarization."""
    parser = argparse.ArgumentParser(
        description="Generate summary reports for detected communities"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Path to clusters CSV (overrides auto-detection)",
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

        # Load and analyze
        df = pd.read_csv(csv_path, dtype=str)
        # Ensure numeric columns
        if "cluster_id" in df.columns:
            df["cluster_id"] = (
                pd.to_numeric(df["cluster_id"], errors="coerce").fillna(-1).astype(int)
            )
        if "pagerank" in df.columns:
            df["pagerank"] = pd.to_numeric(df["pagerank"], errors="coerce").fillna(0.0)

        stats = compute_cluster_stats(df)

        if not stats:
            print("\nNo clusters found in the data.")
            return

        # Generate report
        report_path = os.path.join(analysis_dir, "summary_report.md")
        generate_report(stats, report_path, collect_name=collect_name)

        print(f"\nSummary report: {report_path}")

    except (SettingsError, ConfigFileNotFoundError):
        raise  # reported by @exit_on_config_error
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during summarization: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
