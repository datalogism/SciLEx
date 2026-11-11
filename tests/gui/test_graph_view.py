"""Graph tab: joining the exported graph with the clusters CSV, and its drawing."""

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import analyses
from scilex.gui.services import graph_view as service

pytestmark = pytest.mark.anyio


def _write_graph(graph_dir: Path, name: str = "cocitation") -> None:
    """Three linked papers in two communities, plus one isolated paper."""
    graph_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "title": ["Paper A", "Paper B", "Paper C", "Lonely D"],
            "authors": ["Ann;Bob", "Cid", "Dan", "Eve"],
            "date": ["2021-03-01", "2023", "NA", "2020"],
            "DOI": ["https://doi.org/10.1/A", "10.1/b", "10.1/c", "10.1/d"],
            "cluster_id": [0, 0, 1, 2],
            "pagerank": [0.5, 0.3, 0.2, 0.0],
        }
    ).to_csv(graph_dir / f"clusters_{name}.csv", index=False)
    graph = nx.Graph()
    for node, cluster, rank in (
        ("10.1/a", 0, 0.5),
        ("10.1/b", 0, 0.3),
        ("10.1/c", 1, 0.2),
        ("10.1/d", 2, 0.0),
    ):
        graph.add_node(node, cluster_id=cluster, pagerank=rank)
    graph.add_edge("10.1/a", "10.1/b", weight=3)
    graph.add_edge("10.1/b", "10.1/c", weight=1)
    nx.write_gexf(graph, graph_dir / f"{name}_graph.gexf")


def test_view_keeps_linked_papers_only(tmp_path):
    _write_graph(tmp_path)
    view = service.build_graph_view(tmp_path, "cocitation")

    assert (view.total_papers, view.linked_papers, view.links) == (4, 3, 2)
    assert [node["title"] for node in view.nodes] == ["Paper A", "Paper B", "Paper C"]
    assert view.nodes[0]["year"] == "2021"
    assert {edge["value"] for edge in view.edges} == {3, 1}
    assert list(view.papers["title"]) == ["Paper A", "Paper B", "Paper C"]


def test_communities_are_sorted_and_described(tmp_path):
    _write_graph(tmp_path)
    view = service.build_graph_view(tmp_path, "cocitation")

    first, second = view.communities
    assert (first.cluster_id, first.size, first.years) == (0, 2, "2021–2023")
    assert first.top_titles == ["Paper A", "Paper B"]
    assert second.size == 1 and second.years == ""
    assert first.color != second.color


def test_max_nodes_keeps_most_central(tmp_path):
    _write_graph(tmp_path)
    view = service.build_graph_view(tmp_path, "cocitation", max_nodes=2)

    assert [node["id"] for node in view.nodes] == ["10.1/a", "10.1/b"]
    assert len(view.edges) == 1
    assert view.linked_papers == 3


def test_chart_filters_one_community(tmp_path):
    _write_graph(tmp_path)
    view = service.build_graph_view(tmp_path, "cocitation")
    series = service.chart_options(view, cluster=0)["series"][0]

    assert {node["id"] for node in series["data"]} == {"10.1/a", "10.1/b"}
    assert len(series["links"]) == 1


def test_colour_by_paper_type_and_collection(tmp_path):
    graph_dir = tmp_path / "graph_analysis"
    _write_graph(graph_dir)
    pd.DataFrame(
        {
            "title": ["A survey of A", "Paper B", "Paper C"],
            "itemType": ["journalArticle"] * 3,
            "DOI": ["10.1/a", "10.1/b", "10.1/c"],
            "tags": ["", "PAPER_TYPE:Dataset", ""],
            "zotero_collections": ["Core", "Core", "Extension 1"],
        }
    ).to_csv(tmp_path / "aggregated_results.csv", sep=";", index=False)
    view = service.build_graph_view(graph_dir, "cocitation")
    types = {node["id"]: node[service.PAPER_TYPE] for node in view.nodes}
    assert types == {
        "10.1/a": "Review or State of the art",  # default type, from the title
        "10.1/b": "Dataset",  # its tag
        "10.1/c": "Model or Method",
    }
    by_collection = service.chart_options(view, color_by=service.COLLECTION)
    colors = {
        n["id"]: n["itemStyle"]["color"] for n in by_collection["series"][0]["data"]
    }
    assert colors["10.1/a"] == colors["10.1/b"] != colors["10.1/c"]
    table = service.compare_groups(view, service.COLLECTION).set_index(
        "Zotero collection"
    )
    assert table.loc["Core", "Papers drawn"] == 2
    assert table.loc["Core", "Links inside"] == 1  # A-B
    assert table.loc["Extension 1", "Links to other groups"] == 1  # B-C
    assert service.compare_groups(view, service.COMMUNITY).empty


def test_tooltip_escapes_titles(tmp_path):
    _write_graph(tmp_path)
    path = tmp_path / "clusters_cocitation.csv"
    path.write_text(path.read_text().replace("Paper A", "<b>Paper A</b>"))
    view = service.build_graph_view(tmp_path, "cocitation")

    assert "&lt;b&gt;Paper A" in view.nodes[0]["tooltip"]


def test_missing_graph_file_gives_empty_view(tmp_path):
    _write_graph(tmp_path)
    (tmp_path / "cocitation_graph.gexf").unlink()
    view = service.build_graph_view(tmp_path, "cocitation")

    assert view.linked_papers == 0 and view.nodes == []


def test_available_graphs(tmp_path):
    _write_graph(tmp_path, "coupling")
    assert service.available_graphs(tmp_path) == ["coupling"]


async def test_graph_tab_draws_network(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text("title\nA\n")
    (review.collection_dir / "citations_cache.json").write_text("{}")
    _write_graph(analyses.graph_dir_of(review.collection_dir))

    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/analyses")
        user.find(marker="analysis-tab-graph").click()
        await user.should_see(marker="graph-chart")
        await user.should_see("3 of 4 papers are linked")
        await user.should_see(marker="graph-communities")
