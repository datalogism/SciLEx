"""PubMed / PubMed Central must not silently truncate a page on errors.

A failed EFetch batch or an unparsable response has to raise so that
``runCollect`` leaves the query incomplete (it is then resumed next run).
"""

from unittest.mock import MagicMock

import pytest
import requests

from scilex.crawlers.collectors import PubMed_collector, PubMedCentral_collector

ESEARCH_XML = (
    b"<eSearchResult><Count>2</Count><IdList><Id>1</Id><Id>2</Id></IdList>"
    b"</eSearchResult>"
)


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


@pytest.fixture(params=[PubMed_collector, PubMedCentral_collector])
def collector(request, tmp_path):
    instance = request.param(_query(), str(tmp_path), "SECRETKEY")
    instance.rate_limit = 0
    return instance


def _esearch_response(content=ESEARCH_XML):
    response = MagicMock()
    response.content = content
    return response


def test_failed_efetch_batch_raises(collector):
    collector.api_call_decorator = MagicMock(
        side_effect=requests.exceptions.ConnectionError("down")
    )
    with pytest.raises(requests.exceptions.ConnectionError):
        collector.parsePageResults(_esearch_response(), 1)


def test_unparsable_esearch_raises(collector):
    with pytest.raises(Exception):  # noqa: B017 - lxml XMLSyntaxError
        collector.parsePageResults(_esearch_response(b"<not xml"), 1)


def test_unparsable_efetch_raises(collector):
    efetch = MagicMock()
    efetch.content = b"<broken"
    collector.api_call_decorator = MagicMock(return_value=efetch)
    with pytest.raises(Exception):  # noqa: B017 - lxml XMLSyntaxError
        collector.parsePageResults(_esearch_response(), 1)


def test_empty_idlist_is_a_normal_empty_page(collector):
    page = collector.parsePageResults(
        _esearch_response(b"<eSearchResult><Count>0</Count><IdList/></eSearchResult>"),
        1,
    )
    assert page["results"] == []
    assert page["total"] == 0
