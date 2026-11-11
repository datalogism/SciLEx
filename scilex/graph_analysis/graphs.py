"""Build co-citation and bibliographic coupling graphs from citation caches.

Co-citation:
    Two corpus papers A and B are co-cited if some external paper C cites both.
    Edge weight = number of distinct papers that co-cite A and B.

Bibliographic coupling:
    Two corpus papers A and B are coupled if they share references.
    Edge weight = number of shared references.

Both approaches produce much denser graphs than direct citations,
which is essential for meaningful community detection (see issue #46).
"""

import logging
from collections import defaultdict
from itertools import combinations

import networkx as nx

from scilex.graph_analysis.loader import normalize_citation_map, normalize_dois

logger = logging.getLogger(__name__)


def build_cocitation_graph(
    references: dict[str, list[str]],
    citers: dict[str, list[str]],
    corpus_dois: set[str],
    min_weight: int = 1,
) -> nx.Graph:
    """Build a co-citation graph over corpus papers.

    Two corpus papers A and B get an edge if at least one paper (inside or
    outside the corpus) cites both A and B.  We find co-citers by inverting
    the citers map: for each external paper C that cites corpus papers,
    create edges between all pairs of corpus papers it cites.

    Args:
        references: ``{doi: [cited_dois]}`` — outgoing references.
        citers: ``{doi: [citing_dois]}`` — incoming citers.
        corpus_dois: Set of DOIs that belong to the user's collection.
        min_weight: Minimum co-citation count to keep an edge.

    Returns:
        Undirected weighted NetworkX graph over the normalized corpus DOIs.
    """
    references = normalize_citation_map(references)
    citers = normalize_citation_map(citers)
    corpus_dois = normalize_dois(corpus_dois)
    # Invert: for each external paper, which corpus papers does it cite?
    citer_to_corpus: dict[str, set[str]] = defaultdict(set)

    for corpus_doi in corpus_dois:
        for citing_doi in citers.get(corpus_doi, []):
            citer_to_corpus[citing_doi].add(corpus_doi)

    # Also check references: if corpus paper A references corpus paper B,
    # then A is a "citer" of B within the corpus
    for corpus_doi in corpus_dois:
        for ref_doi in references.get(corpus_doi, []):
            if ref_doi in corpus_dois:
                citer_to_corpus[corpus_doi].add(ref_doi)

    # Build edge weights from co-citation pairs
    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    for _citer, cited_set in citer_to_corpus.items():
        if len(cited_set) < 2:
            continue
        for a, b in combinations(sorted(cited_set), 2):
            edge_weights[(a, b)] += 1

    return _build_weighted_graph(corpus_dois, edge_weights, min_weight, "Co-citation")


def build_bibliographic_coupling_graph(
    references: dict[str, list[str]],
    corpus_dois: set[str],
    min_weight: int = 1,
) -> nx.Graph:
    """Build a bibliographic coupling graph over corpus papers.

    Two corpus papers A and B get an edge if they share at least one
    reference.  Edge weight = number of shared references.

    Args:
        references: ``{doi: [cited_dois]}`` — outgoing references.
        corpus_dois: Set of DOIs that belong to the user's collection.
        min_weight: Minimum shared-reference count to keep an edge.

    Returns:
        Undirected weighted NetworkX graph over the normalized corpus DOIs.
    """
    references = normalize_citation_map(references)
    corpus_dois = normalize_dois(corpus_dois)
    # Invert references: for each referenced paper, which corpus papers cite it?
    ref_to_corpus: dict[str, set[str]] = defaultdict(set)
    for corpus_doi in corpus_dois:
        for ref_doi in references.get(corpus_doi, []):
            ref_to_corpus[ref_doi].add(corpus_doi)

    # Build edge weights from shared references
    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    for _ref, citing_set in ref_to_corpus.items():
        if len(citing_set) < 2:
            continue
        for a, b in combinations(sorted(citing_set), 2):
            edge_weights[(a, b)] += 1

    return _build_weighted_graph(corpus_dois, edge_weights, min_weight, "Coupling")


def _build_weighted_graph(
    corpus_dois: set[str],
    edge_weights: dict[tuple[str, str], int],
    min_weight: int,
    label: str,
) -> nx.Graph:
    """Build a weighted graph from pre-computed edge weights and log stats."""
    g = nx.Graph()
    g.add_nodes_from(corpus_dois)

    for (a, b), weight in edge_weights.items():
        if weight >= min_weight:
            g.add_edge(a, b, weight=weight)

    logger.info(
        f"{label} graph: {g.number_of_nodes()} nodes, "
        f"{g.number_of_edges()} edges, density={nx.density(g):.4f}"
    )
    return g
