"""Analyze citation networks: community detection, centrality, and export.

Reads citation caches produced by ``scilex-enrich-citations`` and builds
co-citation and/or bibliographic coupling graphs.  Detects communities
using Louvain and computes PageRank centrality.

Usage:
    scilex-analyze [--graph-type cocitation|coupling|both]
                   [--resolution FLOAT] [--min-weight INT]
                   [--format gexf|graphml]

Output is written to:
    {output_dir}/{collect_name}/graph_analysis/
"""

import argparse
import logging
import os
import sys

import pandas as pd

from scilex.config_defaults import (
    DEFAULT_GRAPH_FORMAT,
    DEFAULT_GRAPH_MIN_WEIGHT,
    DEFAULT_GRAPH_TYPE,
    DEFAULT_LOUVAIN_RESOLUTION,
)
from scilex.graph_analysis.community import compute_centrality, detect_communities
from scilex.graph_analysis.export import export_clusters_csv, export_graph
from scilex.graph_analysis.graphs import (
    build_bibliographic_coupling_graph,
    build_cocitation_graph,
)
from scilex.graph_analysis.loader import load_citation_caches
from scilex.io_utils import load_aggregated_data
from scilex.logging_config import setup_logging
from scilex.pipeline_utils import (
    extract_corpus_dois,
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
    """Entry point for graph analysis."""
    parser = argparse.ArgumentParser(
        description="Analyze citation networks: communities and centrality"
    )
    parser.add_argument(
        "--graph-type",
        choices=["cocitation", "coupling", "both"],
        default=DEFAULT_GRAPH_TYPE,
        help=f"Type of graph to build (default: {DEFAULT_GRAPH_TYPE})",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=DEFAULT_LOUVAIN_RESOLUTION,
        help=f"Louvain resolution — higher = more clusters (default: {DEFAULT_LOUVAIN_RESOLUTION})",
    )
    parser.add_argument(
        "--min-weight",
        type=int,
        default=DEFAULT_GRAPH_MIN_WEIGHT,
        help=f"Minimum edge weight to keep (default: {DEFAULT_GRAPH_MIN_WEIGHT})",
    )
    parser.add_argument(
        "--format",
        choices=["gexf", "graphml"],
        default=DEFAULT_GRAPH_FORMAT,
        help=f"Graph export format (default: {DEFAULT_GRAPH_FORMAT})",
    )
    add_config_arguments(parser)
    args = parser.parse_args()
    apply_config_arguments(args)

    try:
        config = load_main_config()
        collect_dir = resolve_collect_dir(config)

        # Output subdirectory
        analysis_dir = os.path.join(collect_dir, "graph_analysis")
        os.makedirs(analysis_dir, exist_ok=True)

        # Load data
        df = load_aggregated_data(config)
        corpus_dois = extract_corpus_dois(df)
        logger.info(f"Loaded {len(df)} papers, {len(corpus_dois)} with valid DOIs")
        references, citers = load_citation_caches(collect_dir)

        graph_type = args.graph_type
        fmt = args.format

        # Build graph(s) and run analysis
        if graph_type in ("cocitation", "both"):
            _analyze_graph(
                graph=build_cocitation_graph(
                    references, citers, corpus_dois, min_weight=args.min_weight
                ),
                name="cocitation",
                df=df,
                analysis_dir=analysis_dir,
                resolution=args.resolution,
                fmt=fmt,
            )

        if graph_type in ("coupling", "both"):
            _analyze_graph(
                graph=build_bibliographic_coupling_graph(
                    references, corpus_dois, min_weight=args.min_weight
                ),
                name="coupling",
                df=df,
                analysis_dir=analysis_dir,
                resolution=args.resolution,
                fmt=fmt,
            )

        print(f"\nGraph analysis complete: {analysis_dir}")

    except (SettingsError, ConfigFileNotFoundError):
        raise  # reported by @exit_on_config_error
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during graph analysis: {e}", exc_info=True)
        sys.exit(1)


def _analyze_graph(
    graph,
    name: str,
    df: pd.DataFrame,
    analysis_dir: str,
    resolution: float,
    fmt: str,
) -> None:
    """Run community detection + centrality on a graph and export results."""
    partition = detect_communities(graph, resolution=resolution)
    pagerank = compute_centrality(graph)

    # Export clusters CSV
    csv_path = os.path.join(analysis_dir, f"clusters_{name}.csv")
    export_clusters_csv(df, partition, pagerank, csv_path)

    # Export graph file
    graph_path = os.path.join(analysis_dir, f"{name}_graph.{fmt}")
    export_graph(graph, partition, pagerank, graph_path, fmt=fmt)


if __name__ == "__main__":
    main()
