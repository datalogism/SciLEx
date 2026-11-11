"""Regression tests for the query bugs found on a real collection (2026-10-25)."""

import urllib.parse
from unittest.mock import MagicMock

from scilex.crawlers.aggregate import HALtoZoteroFormat
from scilex.crawlers.collectors import (
    HAL_collector,
    OpenAIRE_collector,
    SemanticScholar_collector,
)
from scilex.crawlers.collectors.base import _describe_unexpected_response


def _data_query(keywords, year=2023):
    return {
        "keyword": keywords,
        "year": year,
        "id_collect": 0,
        "total_art": 0,
        "coll_art": 0,
        "last_page": 0,
        "state": 0,
    }


def _query_params(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url.format(0)).query)


def test_hal_year_is_a_solr_filter_query():
    """A bare ``&submittedDateY_i:[2023]`` parameter is ignored by HAL."""
    collector = HAL_collector(
        _data_query(["knowledge graph", "metabolomics"]), "/tmp", None
    )
    params = _query_params(collector.get_configurated_url())
    assert params["fq"] == ["submittedDateY_i:2023"]


def test_hal_keywords_are_quoted_phrases():
    collector = HAL_collector(
        _data_query(["knowledge graph", "metabolomics"]), "/tmp", None
    )
    params = _query_params(collector.get_configurated_url())
    assert params["q"] == ['("knowledge graph" AND "metabolomics")']


def test_openaire_does_not_send_explicit_and():
    """OpenAIRE answers HTTP 409 to an explicit AND between terms."""
    collector = OpenAIRE_collector(
        _data_query(["knowledge graph", "metabolomics"]), "/tmp", None
    )
    keywords = _query_params(collector.get_configurated_url())["keywords"][0]
    assert keywords == '"knowledge graph" "metabolomics"'
    assert "AND" not in keywords


def test_semantic_scholar_does_not_restrict_field_of_study():
    collector = SemanticScholar_collector(
        _data_query(["knowledge graph", "metabolomics"]), "/tmp", None
    )
    assert "fieldsOfStudy=" not in collector.get_configurated_url()


def test_hal_preprints_and_books_are_typed():
    assert HALtoZoteroFormat({"docType_s": "UNDEFINED"})["itemType"] == "preprint"
    assert HALtoZoteroFormat({"docType_s": "OUV"})["itemType"] == "book"
    assert HALtoZoteroFormat({"docType_s": "COUV"})["itemType"] == "bookSection"


def test_html_bot_check_is_explained():
    response = MagicMock(
        status_code=202,
        headers={"Content-Type": "text/html; charset=utf-8"},
        text="<title>Making sure you're not a bot!</title>",
    )
    message = _describe_unexpected_response(response)
    assert "HTML page (HTTP 202)" in message
    assert "anti-bot" in message


def test_json_parse_error_keeps_generic_message():
    response = MagicMock(headers={"Content-Type": "application/json"})
    assert "Response type" in _describe_unexpected_response(response)
