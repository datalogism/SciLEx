"""Tests for incremental re-collection from a date (issue #31)."""

import json
from datetime import date

import pytest
import yaml

from scilex.crawlers.collectors import (
    Arxiv_collector,
    OpenAlex_collector,
    PubMed_collector,
    SemanticScholar_collector,
)
from scilex.since_utils import (
    find_since_collections,
    parse_since,
    passes_since,
    prepare_since_config,
    years_since,
)

SINCE = date(2024, 6, 15)


def _query(year, since="2024-06-15"):
    query = {
        "keyword": ["graph"],
        "year": year,
        "max_articles_per_query": 10,
        "id_collect": 0,
        "total_art": 0,
        "coll_art": 0,
        "last_page": 0,
        "state": 0,
    }
    if since:
        query["since"] = since
    return query


class TestHelpers:
    def test_parse_since(self):
        assert parse_since("2024-06-15") == SINCE
        assert parse_since(None) is None
        with pytest.raises(ValueError):
            parse_since("15/06/2024")

    def test_years_since(self):
        assert years_since(SINCE, date(2026, 3, 1)) == [2024, 2025, 2026]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2024-06-14", False),
            ("2024-06-15", True),
            ("2023", False),
            ("2024", True),
            ("2024-05", False),
            ("2024-06", True),
            ("NA", True),
            ("garbage", True),
            (None, True),
        ],
    )
    def test_passes_since(self, value, expected):
        assert passes_since(value, SINCE) is expected

    def test_prepare_config_is_idempotent(self):
        config = {"collect_name": "demo", "years": [2020], "apis": ["OpenAlex"]}
        prepared = prepare_since_config(config, SINCE, date(2025, 1, 1))
        assert prepared["years"] == [2024, 2025]
        assert prepared["collect_name"] == "demo_since_2024-06-15"
        assert prepared["since"] == "2024-06-15"
        assert config["years"] == [2020]
        again = prepare_since_config(prepared, SINCE, date(2025, 1, 1))
        assert again["collect_name"] == prepared["collect_name"]


class TestNativeFilters:
    def test_openalex_from_publication_date(self):
        url = OpenAlex_collector(_query(2024), "/tmp/t", None).get_configurated_url()
        assert "from_publication_date:2024-06-15" in url

    def test_openalex_later_year_unrestricted(self):
        url = OpenAlex_collector(_query(2025), "/tmp/t", None).get_configurated_url()
        assert "from_publication_date" not in url

    def test_semantic_scholar_date_or_year(self):
        url = SemanticScholar_collector(
            _query(2024), "/tmp/t", None
        ).get_configurated_url()
        assert "publicationDateOrYear=2024-06-15:2024-12-31" in url
        assert "&year=" not in url
        later = SemanticScholar_collector(
            _query(2025), "/tmp/t", None
        ).get_configurated_url()
        assert "&year=2025" in later

    def test_arxiv_submitted_date(self):
        query = Arxiv_collector(_query(2024), "/tmp/t", None).construct_search_query()
        assert "submittedDate:%5B202406150000+TO+202412312359" in query
        default = Arxiv_collector(
            _query(2024, since=None), "/tmp/t", None
        ).construct_search_query()
        assert "submittedDate:%5B202401010000+TO+" in default

    def test_pubmed_mindate(self):
        query = PubMed_collector(_query(2024), "/tmp/t", None).construct_search_query()
        assert '"2024/06/15"[PDAT] : "2024/12/31"[PDAT]' in query


def test_find_since_collections_and_loading(tmp_path, monkeypatch):
    base = tmp_path / "demo"
    since_dir = tmp_path / "demo_since_2024-06-15"
    base.mkdir()
    (since_dir / "OpenAlex" / "0").mkdir(parents=True)
    config = {
        "collect_name": "demo_since_2024-06-15",
        "since": "2024-06-15",
        "keywords": [["graph"]],
        "years": [2024],
        "apis": ["OpenAlex"],
    }
    (since_dir / "config_used.yml").write_text(yaml.dump(config))
    (since_dir / "OpenAlex" / "0" / "page_1").write_text(
        json.dumps({"results": [{"id": "old"}, {"id": "new"}]})
    )
    assert find_since_collections(str(base)) == [str(since_dir)]

    dates = {"old": "2024-01-01", "new": "2024-09-01"}
    monkeypatch.setitem(
        __import__("scilex.crawlers.aggregate", fromlist=["x"]).FORMAT_CONVERTERS,
        "OpenAlex",
        lambda paper: {"date": dates[paper["id"]]},
    )
    from scilex.since_utils import load_since_collection_papers

    papers = load_since_collection_papers(str(since_dir))
    assert [paper["id"] for paper, _api, _kw in papers] == ["new"]
