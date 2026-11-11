"""Tests for the Papers with Code client and the per-paper lookup (no network)."""

from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

import scilex.PapersWithCode.client as client_module
from scilex.constants import MISSING_VALUE
from scilex.PapersWithCode.client import PWCClient, summarize_paper
from scilex.PapersWithCode.tag_formatter import TagFormatter
from scilex.PapersWithCode.title_matcher import TitleMatcher
from scilex.pipeline.enrichment_pwc import (
    extract_arxiv_id,
    find_paper,
    process_paper_for_csv,
)

RECORD = {
    "id": "18067",
    "arxiv_id": "2307.03172",
    "title": "Lost in the Middle: How Language Models Use Long Contexts",
    "tasks": [{"id": "296", "name": "Question Answering", "slug": "qa"}],
    "methods": [{"name": "BERT"}, {"name": "Transformer"}],
    "evaluated_benchmarks": ["SQuAD 1.1"],
    "introduced_frameworks": None,
    "repositories": [
        {"url": "https://github.com/fork/x", "num_stars": 900, "is_official": False},
        {
            "url": "https://github.com/nelson-liu/lost",
            "num_stars": 399,
            "is_official": True,
        },
    ],
}


def _response(status, payload=None, headers=None):
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.headers = headers or {}
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(str(status))
    return response


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def client(tmp_path, session, monkeypatch):
    monkeypatch.setattr(client_module, "_throttle", lambda: None)
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    return PWCClient(cache_path=str(tmp_path / "cache.db"), session=session)


def test_summarize_prefers_official_repository():
    summary = summarize_paper(RECORD)
    assert summary["url"] == "https://paperswithcode.co/paper/2307.03172"
    assert summary["tasks"] == ["Question Answering"]
    assert summary["methods"] == ["BERT", "Transformer"]
    assert summary["benchmarks"] == ["SQuAD 1.1"]
    assert summary["frameworks"] == []
    assert summary["github_repo"] == "https://github.com/nelson-liu/lost"
    assert summary["github_stars"] == 399


def test_summarize_without_official_takes_most_starred_and_catalog_id():
    record = {
        "id": "42",
        "arxiv_id": None,
        "repositories": [
            {"url": "https://github.com/a/low", "num_stars": 3},
            {"url": "https://github.com/a/high", "num_stars": 30},
        ],
    }
    summary = summarize_paper(record)
    assert summary["github_repo"] == "https://github.com/a/high"
    assert summary["url"] == "https://paperswithcode.co/paper/42"


def test_get_paper_by_arxiv_is_cached(client, session):
    session.get.return_value = _response(200, RECORD)
    first = client.get_paper_by_arxiv("2307.03172")
    second = client.get_paper_by_arxiv("2307.03172")
    assert first == second
    assert session.get.call_count == 1
    url = session.get.call_args.args[0]
    assert url == "https://paperswithcode.co/api/v1/papers/arxiv/2307.03172"
    assert session.get.call_args.kwargs["params"] == {"include_resources": "true"}


def test_not_found_is_cached(client, session):
    session.get.return_value = _response(404)
    assert client.get_paper("999") is None
    assert client.get_paper("999") is None
    assert session.get.call_count == 1


def test_retry_after_on_429(client, session):
    session.get.side_effect = [
        _response(429, headers={"Retry-After": "1"}),
        _response(200, RECORD),
    ]
    assert client.get_paper("18067")["id"] == "18067"
    assert session.get.call_count == 2


def test_errors_return_empty_and_are_not_cached(client, session):
    session.get.return_value = _response(500)
    assert client.search_papers("anything") == []
    assert client.get_paper("1") is None
    session.get.return_value = _response(200, {"results": [{"id": "1", "title": "T"}]})
    assert client.search_papers("anything") == [
        {"id": "1", "arxiv_id": None, "title": "T"}
    ]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"DOI": "10.48550/arXiv.2307.03172"}, "2307.03172"),
        ({"DOI": "NA", "url": "https://arxiv.org/abs/2307.03172v2"}, "2307.03172"),
        ({"pdf_url": "https://arxiv.org/pdf/1810.04805.pdf"}, "1810.04805"),
        ({"DOI": "10.1145/3442188.3445922", "url": "https://doi.org/x"}, None),
    ],
)
def test_extract_arxiv_id(row, expected):
    assert extract_arxiv_id(pd.Series(row)) == expected


def test_find_paper_uses_arxiv_before_title():
    fake = MagicMock()
    fake.get_paper_by_arxiv.return_value = {"id": "1"}
    row = pd.Series({"title": "X", "DOI": "10.48550/arXiv.2307.03172"})
    assert find_paper(row, fake, TitleMatcher()) == {"id": "1"}
    fake.search_papers.assert_not_called()


def test_find_paper_falls_back_to_title_search():
    fake = MagicMock()
    fake.get_paper_by_arxiv.return_value = None
    fake.search_papers.return_value = [
        {"id": "7", "arxiv_id": None, "title": "Graph Neural Networks for Chemistry"},
        {"id": "8", "arxiv_id": "2401.00001", "title": "Something Else Entirely"},
    ]
    fake.get_paper.return_value = {"id": "7"}
    row = pd.Series(
        {
            "title": "Graph neural networks for chemistry",
            "url": "arxiv.org/abs/2401.99999",
        }
    )
    assert find_paper(row, fake, TitleMatcher()) == {"id": "7"}
    fake.get_paper.assert_called_once_with("7")


def test_find_paper_rejects_weak_title_match():
    fake = MagicMock()
    fake.search_papers.return_value = [{"id": "1", "title": "Unrelated work"}]
    row = pd.Series({"title": "Graph neural networks for chemistry"})
    assert find_paper(row, fake, TitleMatcher(threshold=85)) is None
    fake.get_paper.assert_not_called()


def test_process_paper_for_csv_builds_columns():
    fake = MagicMock()
    fake.get_paper_by_arxiv.return_value = summarize_paper(RECORD)
    row = pd.Series({"title": RECORD["title"], "DOI": "10.48550/arXiv.2307.03172"})
    result = process_paper_for_csv(row, fake, TitleMatcher(), TagFormatter())
    assert result == {
        "tags": "TASK:QuestionAnswering;PTM:Bert;ARCHI:Transformer;"
        "DATASET:Squad11;GITHUB_STARS:399",
        "pwc_url": "https://paperswithcode.co/paper/2307.03172",
        "github_repo": "https://github.com/nelson-liu/lost",
    }


def test_process_paper_for_csv_without_anything_to_add():
    fake = MagicMock()
    fake.get_paper.return_value = summarize_paper({"id": "1", "title": "T"})
    fake.search_papers.return_value = [{"id": "1", "title": "T"}]
    row = pd.Series({"title": "T"})
    assert process_paper_for_csv(row, fake, TitleMatcher(), TagFormatter()) is None


def test_process_paper_for_csv_repo_only():
    fake = MagicMock()
    fake.get_paper_by_arxiv.return_value = summarize_paper(
        {"id": "1", "repositories": [{"url": "https://github.com/a/b"}]}
    )
    row = pd.Series({"title": "T", "DOI": "10.48550/arXiv.2401.00001"})
    result = process_paper_for_csv(row, fake, TitleMatcher(), TagFormatter())
    assert result["tags"] == MISSING_VALUE
    assert result["github_repo"] == "https://github.com/a/b"
