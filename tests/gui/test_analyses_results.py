"""Robust reading of result CSVs and graph warnings."""

import importlib.util

import pandas as pd
import pytest

from scilex.gui.services import analyses as service


def test_read_result_csv_guesses_delimiter(tmp_path):
    comma = tmp_path / "a.csv"
    comma.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    semicolon = tmp_path / "b.csv"
    semicolon.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    assert list(service.read_result_csv(comma).columns) == ["a", "b", "c"]
    assert list(service.read_result_csv(semicolon).columns) == ["a", "b", "c"]


def test_read_result_csv_skips_malformed_lines(tmp_path):
    path = tmp_path / "clusters_cocitation.csv"
    path.write_text(
        "cluster_id,title,pagerank\n1,A,0.1\n1,B,0.2\n2,x,y,z,1,2,3,4,5,6\n2,C,0.3\n",
        encoding="utf-8",
    )
    frame = service.read_result_csv(path)
    assert list(frame["title"]) == ["A", "B", "C"]


def test_read_result_csv_unreadable_raises_value_error(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    try:
        service.read_result_csv(path)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_warnings_texts():
    assert "Citations tab" in service.NO_EDGES_WARNING
    assert "PageRank" in service.NO_SCIPY_WARNING
    assert importlib.util.find_spec("pandas") is not None


def test_summaries_warn_instead_of_listing_one_paper_communities(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    graph_dir = review.collection_dir / service.GRAPH_DIRNAME
    graph_dir.mkdir(parents=True)
    (graph_dir / "clusters_cocitation.csv").write_text(
        "cluster_id,title\n0,A\n1,B\n2,C\n", encoding="utf-8"
    )
    result = service.run_summaries(config, lambda percent, message: None)
    assert "No links found in the co-citation graph" in result.message
    assert result.files == []


def _review_with_both_clusters(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    graph_dir = service.graph_dir_of(review.collection_dir)
    graph_dir.mkdir(parents=True)
    for graph, titles in {
        "cocitation": ["Graph Memory Agents", "Graph Memory Systems"],
        "coupling": ["Temporal Reasoning Models", "Temporal Reasoning Agents"],
    }.items():
        pd.DataFrame(
            {"title": titles, "cluster_id": [0, 0], "pagerank": [0.5, 0.4]}
        ).to_csv(graph_dir / f"clusters_{graph}.csv", index=False)
    return review


def test_summaries_use_the_chosen_clusters(ctx, tmp_path):
    review = _review_with_both_clusters(ctx, tmp_path)
    config = ctx.workspace.load_config(review)
    result = service.run_summaries(config, lambda p, m: None, clusters="coupling")
    assert "bibliographic coupling graph" in result.message
    assert "temporal reasoning" in result.files[0].read_text()


def test_keywords_default_to_cocitation_clusters(ctx, tmp_path):
    review = _review_with_both_clusters(ctx, tmp_path)
    config = ctx.workspace.load_config(review)
    result = service.run_keywords(config, lambda p, m: None, min_freq=2)
    assert "co-citation clusters" in result.message


def test_missing_chosen_clusters_explains_how_to_get_them(ctx, tmp_path):
    review = _review_with_both_clusters(ctx, tmp_path)
    (service.graph_dir_of(review.collection_dir) / "clusters_coupling.csv").unlink()
    config = ctx.workspace.load_config(review)
    with pytest.raises(service.AnalysisError, match="Bibliographic coupling or Both"):
        service.run_summaries(config, lambda p, m: None, clusters="coupling")
