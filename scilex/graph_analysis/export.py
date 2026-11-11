"""Export graph analysis results: clusters CSV and graph files (GEXF/GraphML)."""

import logging

import networkx as nx
import pandas as pd

from scilex.constants import normalize_doi

logger = logging.getLogger(__name__)


def export_clusters_csv(
    data: pd.DataFrame,
    partition: dict[str, int],
    pagerank: dict[str, float],
    output_path: str,
    doi_column: str = "DOI",
) -> None:
    """Augment the aggregated CSV with cluster_id and pagerank columns.

    Args:
        data: Original aggregated DataFrame.
        partition: ``{doi: cluster_id}`` from community detection.
        pagerank: ``{doi: score}`` from centrality analysis.
        output_path: Where to write the augmented CSV.
        doi_column: Column name containing DOIs.
    """
    # Graph nodes are normalized DOIs (lowercase, no doi.org prefix).
    dois = data[doi_column].map(normalize_doi)
    data["cluster_id"] = dois.map(partition).fillna(-1).astype(int)
    data["pagerank"] = dois.map(pagerank).fillna(0.0)
    data = data.sort_values(["cluster_id", "pagerank"], ascending=[True, False])

    data.to_csv(output_path, index=False)
    logger.info(f"Clusters CSV: {output_path} ({len(data)} papers)")


def export_graph(
    graph: nx.Graph,
    partition: dict[str, int],
    pagerank: dict[str, float],
    output_path: str,
    fmt: str = "gexf",
) -> None:
    """Export graph with community and centrality attributes.

    Args:
        graph: NetworkX graph to export.
        partition: ``{doi: cluster_id}`` — added as node attribute.
        pagerank: ``{doi: score}`` — added as node attribute.
        output_path: Output file path.
        fmt: ``"gexf"`` or ``"graphml"``.
    """
    for node in graph.nodes():
        graph.nodes[node]["cluster_id"] = partition.get(node, -1)
        graph.nodes[node]["pagerank"] = pagerank.get(node, 0.0)

    if fmt == "graphml":
        nx.write_graphml(graph, output_path)
    else:
        nx.write_gexf(graph, output_path)

    logger.info(f"Graph exported: {output_path} ({fmt})")
