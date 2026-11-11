"""Community detection and centrality analysis on citation graphs.

Uses Louvain algorithm (via community.best_partition from python-louvain)
with fallback to networkx greedy modularity if python-louvain is not installed.
"""

import logging

import networkx as nx

logger = logging.getLogger(__name__)


def detect_communities(
    graph: nx.Graph,
    resolution: float = 1.0,
) -> dict[str, int]:
    """Detect communities using Louvain, with greedy-modularity fallback.

    Args:
        graph: Undirected weighted graph (co-citation or coupling).
        resolution: Louvain resolution parameter. Higher values produce
            more (smaller) communities. Default 1.0.

    Returns:
        Dict mapping each node (DOI) to its community ID (int starting at 0).
    """
    if graph.number_of_nodes() == 0:
        return {}

    # Isolated nodes get their own community later
    connected = graph.subgraph([n for n in graph.nodes() if graph.degree(n) > 0]).copy()

    if connected.number_of_nodes() == 0:
        return {doi: i for i, doi in enumerate(graph.nodes())}

    partition = _louvain_partition(connected, resolution)

    # Assign isolated nodes to individual communities
    max_id = max(partition.values(), default=-1)
    for node in graph.nodes():
        if node not in partition:
            max_id += 1
            partition[node] = max_id

    n_communities = len(set(partition.values()))
    logger.info(f"Detected {n_communities} communities")
    return partition


def compute_centrality(graph: nx.Graph) -> dict[str, float]:
    """Compute centrality on the graph.

    Uses PageRank when scipy is available, falls back to weighted
    degree centrality (strength / max_strength) otherwise.

    Args:
        graph: NetworkX graph (can be directed or undirected).

    Returns:
        Dict mapping each node (DOI) to its centrality score.
    """
    if graph.number_of_nodes() == 0:
        return {}
    try:
        return nx.pagerank(graph, weight="weight")
    except ImportError:
        logger.info("scipy not available, using degree centrality fallback")
        return _degree_centrality_fallback(graph)


def _degree_centrality_fallback(graph: nx.Graph) -> dict[str, float]:
    """Weighted degree centrality normalized to sum to 1.0."""
    strength = {
        n: sum(d.get("weight", 1) for _, _, d in graph.edges(n, data=True))
        for n in graph.nodes()
    }
    total = sum(strength.values()) or 1.0
    return {n: s / total for n, s in strength.items()}


def _louvain_partition(graph: nx.Graph, resolution: float) -> dict[str, int]:
    """Run Louvain community detection with fallback."""
    try:
        import community as community_louvain

        partition = community_louvain.best_partition(
            graph, weight="weight", resolution=resolution
        )
        logger.info("Community detection: Louvain (python-louvain)")
        return partition
    except ImportError:
        logger.info(
            "python-louvain not installed, falling back to "
            "greedy_modularity_communities"
        )
        return _greedy_modularity_fallback(graph)


def _greedy_modularity_fallback(graph: nx.Graph) -> dict[str, int]:
    """Fallback community detection using networkx built-in."""
    communities = nx.community.greedy_modularity_communities(graph, weight="weight")
    partition = {}
    for community_id, members in enumerate(communities):
        for node in members:
            partition[node] = community_id
    return partition
