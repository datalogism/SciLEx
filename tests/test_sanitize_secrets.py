"""Secrets must never reach logs: shared sanitizer and collector URL building."""

import pytest

from scilex.crawlers.collectors import IEEE_collector, Springer_collector
from scilex.crawlers.collectors.base import API_collector
from scilex.crawlers.utils import sanitize_secrets


@pytest.mark.parametrize(
    "text",
    [
        "https://x.org/s?q=a&apikey=SECRET&p=1",
        "https://x.org/s?q=a&apiKey=SECRET&p=1",
        "https://x.org/s?q=a&api_key=SECRET&p=1",
        "https://x.org/s?q=a&api-key=SECRET&p=1",
        "https://x.org/s?q=a&key=SECRET",
        "https://x.org/s?token=SECRET",
        "https://x.org/s?inst_token=SECRET",
        "https://x.org/s?access_token=SECRET",
        "HTTPError: 500 for url: https://x.org/s?APIKEY=SECRET (Caused by X)",
    ],
)
def test_secret_values_are_masked(text):
    cleaned = sanitize_secrets(text)
    assert "SECRET" not in cleaned
    assert "***REDACTED***" in cleaned


def test_non_secret_params_survive():
    url = "https://x.org/s?q=monkey+business&year=2020&api_key=K&p=100"
    cleaned = sanitize_secrets(url)
    assert "q=monkey+business" in cleaned
    assert "year=2020" in cleaned
    assert "p=100" in cleaned


def test_url_wrapper_shares_the_implementation():
    text = "https://x.org/s?api-key=SECRET&q=1"
    assert API_collector._sanitize_url(text) == sanitize_secrets(text)


def _query():
    return {
        "keyword": ["kw"],
        "year": 2024,
        "id_collect": 0,
        "total_art": 0,
        "coll_art": 0,
        "last_page": 0,
        "state": 0,
    }


def test_ieee_url_without_api_key_does_not_crash(tmp_path):
    collector = IEEE_collector(_query(), str(tmp_path), None)
    url = collector.get_configurated_url()
    assert "apikey=&" in url
    assert url.endswith("start_record={}")


def test_springer_endpoint_logging_hides_keys(tmp_path, caplog):
    collector = Springer_collector(_query(), str(tmp_path), "SECRETKEY")
    with caplog.at_level("DEBUG"):
        collector._get_api_endpoints()
    assert "SECRETKEY" not in caplog.text
