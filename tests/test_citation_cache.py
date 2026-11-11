"""Tests for DOI normalization and the SQLite citation cache."""

import threading

import pytest

from scilex.citations import cache
from scilex.constants import normalize_doi


@pytest.fixture(autouse=True)
def _close_after_test():
    yield
    cache.close_connections()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("10.1/ABC", "10.1/abc"),
        ("https://doi.org/10.1/ABC", "10.1/abc"),
        ("http://dx.doi.org/10.1/abc", "10.1/abc"),
        ("HTTPS://DOI.ORG/10.1/abc", "10.1/abc"),
        ("doi.org/10.1/abc", "10.1/abc"),
        ("DOI:10.1/abc", "10.1/abc"),
        ("  doi: 10.1/abc  ", "10.1/abc"),
        (None, None),
        ("", None),
        ("NA", None),
        (float("nan"), None),
    ],
)
def test_normalize_doi(raw, expected):
    assert normalize_doi(raw) == expected


def _store(doi, path, cit="success", ref="success"):
    cache.cache_citations_batch(
        [
            {
                "doi": doi,
                "citations_json": "{}",
                "nb_cited": 1,
                "nb_citations": 2,
                "api_stats": {"cit_status": cit, "ref_status": ref},
            }
        ],
        path,
    )


def test_lookup_hits_across_doi_spellings(tmp_path):
    path = cache.initialize_cache(tmp_path / "c.db")
    _store("10.1/ABC", path)
    assert "https://doi.org/10.1/abc" in cache.get_cached_citations_batch(
        ["https://doi.org/10.1/abc"], path
    )
    assert (
        cache.get_cached_citations_batch(["doi:10.1/Abc"], path)["doi:10.1/Abc"][
            "nb_cited"
        ]
        == 1
    )


def test_batch_roundtrip_with_mixed_spellings(tmp_path):
    path = cache.initialize_cache(tmp_path / "c.db")
    cache.cache_citations_batch(
        [
            {
                "doi": "https://doi.org/10.1/X",
                "citations_json": "{}",
                "nb_cited": 3,
                "nb_citations": 4,
                "api_stats": {"cit_status": "success", "ref_status": "success"},
            }
        ],
        path,
    )
    found = cache.get_cached_citations_batch(["10.1/x", "10.9/none"], path)
    assert list(found) == ["10.1/x"]
    assert found["10.1/x"]["nb_cited"] == 3
    assert found["10.1/x"]["nb_citations"] == 4


def test_different_paths_get_different_connections(tmp_path):
    path_a = cache.initialize_cache(tmp_path / "a.db")
    path_b = cache.initialize_cache(tmp_path / "b.db")
    _store("10.1/a", path_a)
    assert cache.get_cached_citations_batch(["10.1/a"], path_b) == {}
    assert "10.1/a" in cache.get_cached_citations_batch(["10.1/a"], path_a)


def test_close_connections_closes_other_threads(tmp_path):
    path = tmp_path / "t.db"
    worker = threading.Thread(target=cache.initialize_cache, args=(path,))
    worker.start()
    worker.join()
    cache.initialize_cache(path)
    assert len(cache._connections) == 2
    cache.close_connections()
    assert cache._connections == {}
    # Usable again after close
    cache.initialize_cache(path)
    assert len(cache._connections) == 1


@pytest.mark.parametrize(
    "cit,ref,expected",
    [
        ("success", "success", True),
        ("success", "error", False),
        ("timeout", "success", False),
        ("unknown", "unknown", False),
    ],
)
def test_should_cache_result(cit, ref, expected):
    result = {"api_stats": {"cit_status": cit, "ref_status": ref}}
    assert cache.should_cache_result(result) is expected


def test_should_cache_result_without_stats():
    assert cache.should_cache_result({}) is False
