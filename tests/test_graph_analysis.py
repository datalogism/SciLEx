"""Tests for the scilex.graph_analysis module.

All tests use synthetic graph data — no real files or API calls.
"""

import json
import os

import networkx as nx
import pandas as pd
import pytest

from scilex.graph_analysis.community import (
    compute_centrality,
    detect_communities,
)
from scilex.graph_analysis.export import export_clusters_csv, export_graph
from scilex.graph_analysis.graphs import (
    build_bibliographic_coupling_graph,
    build_cocitation_graph,
)
from scilex.graph_analysis.loader import load_citation_caches

# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------

# Corpus DOIs (the user's collection)
CORPUS_DOIS = {"10.1/a", "10.1/b", "10.1/c", "10.1/d", "10.1/e"}

# References: what each corpus paper cites
REFERENCES = {
    "10.1/a": ["10.9/ref1", "10.9/ref2", "10.9/ref3"],
    "10.1/b": ["10.9/ref1", "10.9/ref2", "10.9/ref4"],
    "10.1/c": ["10.9/ref3", "10.9/ref5"],
    "10.1/d": ["10.9/ref1", "10.9/ref5"],
    "10.1/e": [],
}

# Citers: who cites each corpus paper
CITERS = {
    "10.1/a": ["10.8/ext1", "10.8/ext2"],
    "10.1/b": ["10.8/ext1", "10.8/ext3"],
    "10.1/c": ["10.8/ext2"],
    "10.1/d": [],
    "10.1/e": [],
}


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


class TestLoader:
    def test_load_citation_caches(self, tmp_path):
        """Load both cache files from a temp directory."""
        ref_file = tmp_path / "citations_cache.json"
        citer_file = tmp_path / "citers_cache.json"
        ref_file.write_text(json.dumps(REFERENCES))
        citer_file.write_text(json.dumps(CITERS))

        refs, citers = load_citation_caches(str(tmp_path))
        assert len(refs) == 5
        assert len(citers) == 5
        assert refs["10.1/a"] == ["10.9/ref1", "10.9/ref2", "10.9/ref3"]

    def test_load_missing_caches_raises(self, tmp_path):
        """FileNotFoundError when neither cache exists."""
        with pytest.raises(FileNotFoundError, match="No citation caches"):
            load_citation_caches(str(tmp_path))

    def test_load_partial_caches(self, tmp_path):
        """One cache present, the other missing — should still work."""
        ref_file = tmp_path / "citations_cache.json"
        ref_file.write_text(json.dumps(REFERENCES))

        refs, citers = load_citation_caches(str(tmp_path))
        assert len(refs) == 5
        assert len(citers) == 0


# ---------------------------------------------------------------------------
# Co-citation graph tests
# ---------------------------------------------------------------------------


class TestCocitationGraph:
    def test_basic_cocitation(self):
        """Papers a and b should be co-cited (ext1 cites both)."""
        g = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS)

        assert g.number_of_nodes() == 5
        assert g.has_edge("10.1/a", "10.1/b")

    def test_cocitation_weight(self):
        """Edge weight reflects number of co-citing papers."""
        g = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS)

        # ext1 cites both a and b => weight >= 1
        assert g.has_edge("10.1/a", "10.1/b")
        assert g["10.1/a"]["10.1/b"]["weight"] >= 1

    def test_isolated_nodes_preserved(self):
        """Paper e has no citations — still appears as a node."""
        g = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS)
        assert "10.1/e" in g.nodes()

    def test_min_weight_filters(self):
        """Higher min_weight should reduce edges."""
        g_low = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS, min_weight=1)
        g_high = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS, min_weight=100)
        assert g_high.number_of_edges() <= g_low.number_of_edges()

    def test_empty_corpus(self):
        """Empty corpus produces empty graph."""
        g = build_cocitation_graph(REFERENCES, CITERS, set())
        assert g.number_of_nodes() == 0


# ---------------------------------------------------------------------------
# Bibliographic coupling graph tests
# ---------------------------------------------------------------------------


class TestCouplingGraph:
    def test_basic_coupling(self):
        """Papers a and b share ref1 and ref2 => coupled."""
        g = build_bibliographic_coupling_graph(REFERENCES, CORPUS_DOIS)

        assert g.has_edge("10.1/a", "10.1/b")
        assert g["10.1/a"]["10.1/b"]["weight"] == 2  # ref1 + ref2

    def test_no_coupling_for_disjoint(self):
        """Paper e has no references => no coupling edges."""
        g = build_bibliographic_coupling_graph(REFERENCES, CORPUS_DOIS)
        assert g.degree("10.1/e") == 0

    def test_coupling_weight_accuracy(self):
        """Papers a and c share ref3 => weight 1."""
        g = build_bibliographic_coupling_graph(REFERENCES, CORPUS_DOIS)

        assert g.has_edge("10.1/a", "10.1/c")
        assert g["10.1/a"]["10.1/c"]["weight"] == 1

    def test_min_weight_filters(self):
        """min_weight=2 should exclude single-shared-reference edges."""
        g = build_bibliographic_coupling_graph(REFERENCES, CORPUS_DOIS, min_weight=2)
        # Only a-b share 2 refs; other pairs share <=1
        for u, v in g.edges():
            assert g[u][v]["weight"] >= 2


# ---------------------------------------------------------------------------
# Community detection tests
# ---------------------------------------------------------------------------


class TestCommunityDetection:
    def test_detect_communities_returns_all_nodes(self):
        """Every node in the graph must get a community assignment."""
        g = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS)
        partition = detect_communities(g)

        assert set(partition.keys()) == CORPUS_DOIS

    def test_detect_communities_on_empty_graph(self):
        """Empty graph returns empty partition."""
        g = nx.Graph()
        partition = detect_communities(g)
        assert partition == {}

    def test_isolated_nodes_get_unique_communities(self):
        """Isolated nodes each get their own community."""
        g = nx.Graph()
        g.add_nodes_from(["a", "b", "c"])
        partition = detect_communities(g)

        assert len(partition) == 3
        # Each node has a different community
        assert len(set(partition.values())) == 3

    def test_connected_pair_same_community(self):
        """Two strongly connected nodes should be in the same community."""
        g = nx.Graph()
        g.add_edge("a", "b", weight=10)
        partition = detect_communities(g)
        assert partition["a"] == partition["b"]

    def test_resolution_affects_clusters(self):
        """Higher resolution should produce at least as many communities."""
        g = build_bibliographic_coupling_graph(REFERENCES, CORPUS_DOIS)
        p_low = detect_communities(g, resolution=0.1)
        p_high = detect_communities(g, resolution=5.0)

        n_low = len(set(p_low.values()))
        n_high = len(set(p_high.values()))
        # Higher resolution = more communities (or equal)
        assert n_high >= n_low


class TestCentrality:
    def test_pagerank_returns_all_nodes(self):
        """PageRank should return a score for every node."""
        g = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS)
        pr = compute_centrality(g)
        assert set(pr.keys()) == CORPUS_DOIS

    def test_pagerank_sums_to_one(self):
        """PageRank values should approximately sum to 1."""
        g = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS)
        pr = compute_centrality(g)
        assert abs(sum(pr.values()) - 1.0) < 0.01

    def test_pagerank_empty_graph(self):
        """Empty graph returns empty dict."""
        g = nx.Graph()
        assert compute_centrality(g) == {}


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExport:
    def _make_df(self):
        """Create a minimal DataFrame matching the corpus."""
        return pd.DataFrame(
            {
                "DOI": list(CORPUS_DOIS),
                "title": [f"Paper {d}" for d in CORPUS_DOIS],
            }
        )

    def test_export_clusters_csv(self, tmp_path):
        """CSV export adds cluster_id and pagerank columns."""
        df = self._make_df()
        partition = {d: 0 for d in CORPUS_DOIS}
        pagerank = {d: 0.2 for d in CORPUS_DOIS}

        output_path = str(tmp_path / "clusters.csv")
        export_clusters_csv(df, partition, pagerank, output_path)

        result = pd.read_csv(output_path)
        assert "cluster_id" in result.columns
        assert "pagerank" in result.columns
        assert len(result) == 5

    def test_export_gexf(self, tmp_path):
        """GEXF export creates a valid file."""
        g = build_cocitation_graph(REFERENCES, CITERS, CORPUS_DOIS)
        partition = {d: 0 for d in CORPUS_DOIS}
        pagerank = {d: 0.2 for d in CORPUS_DOIS}

        output_path = str(tmp_path / "test.gexf")
        export_graph(g, partition, pagerank, output_path, fmt="gexf")

        assert os.path.exists(output_path)
        loaded = nx.read_gexf(output_path)
        assert loaded.number_of_nodes() == 5

    def test_export_graphml(self, tmp_path):
        """GraphML export creates a valid file."""
        g = build_bibliographic_coupling_graph(REFERENCES, CORPUS_DOIS)
        partition = {d: 0 for d in CORPUS_DOIS}
        pagerank = {d: 0.2 for d in CORPUS_DOIS}

        output_path = str(tmp_path / "test.graphml")
        export_graph(g, partition, pagerank, output_path, fmt="graphml")

        assert os.path.exists(output_path)
        loaded = nx.read_graphml(output_path)
        assert loaded.number_of_nodes() == 5

    def test_export_graph_has_attributes(self, tmp_path):
        """Exported graph nodes should have cluster_id and pagerank."""
        g = nx.Graph()
        g.add_edge("a", "b", weight=1)
        partition = {"a": 0, "b": 1}
        pagerank = {"a": 0.6, "b": 0.4}

        output_path = str(tmp_path / "attrs.gexf")
        export_graph(g, partition, pagerank, output_path)

        loaded = nx.read_gexf(output_path)
        assert loaded.nodes["a"]["cluster_id"] == 0
        assert loaded.nodes["b"]["cluster_id"] == 1


# ---------------------------------------------------------------------------
# DOI case (DOIs are case-insensitive)
# ---------------------------------------------------------------------------


class TestDoiCase:
    def test_cache_merges_case_variants(self):
        from scilex.graph_analysis.loader import normalize_citation_map

        mapping = {
            "10.1/A": ["10.9/X", "https://doi.org/10.9/y"],
            "10.1/a": ["10.9/x", "NA", ""],
        }
        assert normalize_citation_map(mapping) == {"10.1/a": ["10.9/x", "10.9/y"]}

    def test_coupling_links_case_variants(self):
        graph = build_bibliographic_coupling_graph(
            {"10.1/A": ["10.9/X"], "10.1/b": ["10.9/x"]}, {"10.1/a", "10.1/B"}
        )
        assert graph.has_edge("10.1/a", "10.1/b")

    def test_cocitation_links_case_variants(self):
        graph = build_cocitation_graph(
            {}, {"10.1/a": ["10.8/C"], "10.1/b": ["10.8/c"]}, {"10.1/A", "10.1/b"}
        )
        assert graph.has_edge("10.1/a", "10.1/b")

    def test_clusters_csv_maps_mixed_case_dois(self, tmp_path):
        df = pd.DataFrame({"DOI": ["10.1/A", "https://doi.org/10.1/b"]})
        output = tmp_path / "clusters.csv"
        export_clusters_csv(
            df, {"10.1/a": 0, "10.1/b": 1}, {"10.1/a": 0.5}, str(output)
        )
        result = pd.read_csv(output)
        assert sorted(result["cluster_id"]) == [0, 1]
