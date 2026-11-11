"""Tests for the citation graph Turtle export (HTTP mocked)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from rdflib import Graph

from scilex.rdf import citation_graph as cg
from scilex.rdf.namespaces import BIBO

TURTLE = """@prefix dct: <http://purl.org/dc/terms/> .
<https://doi.org/10.1/a> dct:title "Paper A" .
"""


def _response(status=200, text=TURTLE):
    response = MagicMock()
    response.status_code = status
    response.text = text
    return response


def test_fetch_doi_turtle_sends_accept_header():
    with patch.object(cg, "_rate_limited_get", return_value=_response()) as get:
        assert cg.fetch_doi_turtle("10.1/a", "me@x.org") == TURTLE
    url, headers = get.call_args.args
    assert str(url) == "https://doi.org/10.1/a"
    assert headers["Accept"] == "text/turtle"
    assert "me@x.org" in headers["User-Agent"]


def test_fetch_doi_turtle_not_found_returns_none():
    with patch.object(cg, "_rate_limited_get", return_value=_response(404)):
        assert cg.fetch_doi_turtle("10.1/zzz") is None


def test_fetch_doi_turtle_retries_on_503():
    with (
        patch.object(
            cg, "_rate_limited_get", side_effect=[_response(503), _response()]
        ),
        patch("tenacity.nap.time.sleep"),
    ):
        assert cg.fetch_doi_turtle("10.1/a") == TURTLE


def test_build_graph_edges_only():
    graph = cg.build_citation_graph(
        ["10.1/A", "10.1/b"],
        {"10.1/a": ["10.2/x", "https://doi.org/10.2/Y"]},
        include_doi_metadata=False,
    )
    assert len(graph) == 2
    assert (cg.doi_uri("10.1/a"), BIBO.cites, cg.doi_uri("10.2/y")) in graph


def test_build_graph_merges_metadata_and_uses_cache(tmp_path):
    cache_path = str(tmp_path / "cache.json")
    with patch.object(cg, "fetch_doi_turtle", return_value=TURTLE) as fetch:
        graph = cg.build_citation_graph(
            ["10.1/a"], {"10.1/a": ["10.2/x"]}, cache_path=cache_path
        )
        assert fetch.call_count == 1
    assert len(graph) == 2
    assert json.loads(Path(cache_path).read_text())["10.1/a"] == TURTLE

    with patch.object(cg, "fetch_doi_turtle") as fetch:
        cg.build_citation_graph(["10.1/a"], {}, cache_path=cache_path)
        fetch.assert_not_called()


def test_write_citation_graph_roundtrip(tmp_path):
    with patch.object(cg, "fetch_doi_turtle", return_value=None):
        path = cg.write_citation_graph(
            ["10.1/a"], str(tmp_path), {"10.1/a": ["10.2/x"]}
        )
    assert path.endswith("citation_graph.ttl")
    assert len(Graph().parse(path, format="turtle")) == 1
