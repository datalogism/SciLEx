"""Tests for OpenCitations retry policy and CrossRef batch bisection (HTTP mocked)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from scilex.citations import citations_tools as ct


@pytest.fixture(autouse=True)
def _no_sleep():
    """Neutralize tenacity waits and rate-limit windows.

    Patching ``sleep`` alone is not enough: ``sleep_and_retry`` would then
    busy-loop until the rate-limit period elapses. Reporting an elapsed
    period makes the limiter reset its counter on every call.
    """
    with (
        patch("tenacity.nap.time.sleep"),
        patch("ratelimit.decorators.time.sleep"),
        patch(
            "ratelimit.decorators.RateLimitDecorator._RateLimitDecorator__period_remaining",
            return_value=0,
        ),
    ):
        yield


def _response(status=200, payload=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.json.return_value = payload if payload is not None else []
    if status >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
    return resp


@patch("scilex.citations.citations_tools.requests.get")
def test_oc_retries_on_5xx_then_succeeds(mock_get):
    mock_get.side_effect = [_response(503), _response(200, [{"citing": "10.1/a"}])]
    ok, resp, status = ct.getCitations("10.1/x")
    assert (ok, status) == (True, "success")
    assert mock_get.call_count == 2
    assert resp.json() == [{"citing": "10.1/a"}]


@patch("scilex.citations.citations_tools.requests.get")
def test_oc_does_not_retry_404(mock_get):
    mock_get.return_value = _response(404)
    assert ct.getReferences("10.1/x") == (False, None, "error")
    assert mock_get.call_count == 1


@patch("scilex.citations.citations_tools.requests.get")
def test_oc_retries_timeouts_then_reports_timeout(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout()
    assert ct.getCitations("10.1/x") == (False, None, "timeout")
    assert mock_get.call_count == 3


@patch("scilex.citations.citations_tools.requests.get")
def test_oc_retries_connection_error(mock_get):
    mock_get.side_effect = [requests.exceptions.ConnectionError(), _response(200)]
    assert ct.getCitations("10.1/x")[0] is True
    assert mock_get.call_count == 2


@patch("scilex.citations.citations_tools.requests.get")
def test_oc_url_uses_normalized_and_quoted_doi(mock_get):
    mock_get.return_value = _response(200)
    ct.getCitations("https://doi.org/10.1/A B#c")
    url = mock_get.call_args[0][0]
    assert url == "https://api.opencitations.net/index/v1/citations/10.1/a%20b%23c"


def test_retry_after_is_honored_and_capped():
    exc = requests.exceptions.HTTPError(
        response=_response(429, headers={"Retry-After": "500"})
    )
    state = MagicMock()
    state.outcome.exception.return_value = exc
    assert ct.wait_retry_after_or_backoff(state) == 60
    exc = requests.exceptions.HTTPError(
        response=_response(429, headers={"Retry-After": "3"})
    )
    state.outcome.exception.return_value = exc
    assert ct.wait_retry_after_or_backoff(state) == 3


@patch("scilex.citations.citations_tools.requests.get")
def test_crossref_400_bisects_to_isolate_bad_doi(mock_get):
    bad = "10.1/bad"

    def fake_get(url, timeout):
        filter_part = url.split("filter=")[1].split("&")[0]
        dois = [piece[len("doi:") :] for piece in filter_part.split(",")]
        if bad in dois:
            return _response(400)
        items = [
            {"DOI": d.upper(), "is-referenced-by-count": 1, "references-count": 2}
            for d in dois
        ]
        return _response(200, {"message": {"items": items}})

    mock_get.side_effect = fake_get
    result = ct.getCrossRefCitationsBatch(
        ["10.1/a", "10.1/b", bad, "10.1/c", "https://doi.org/10.1/D"]
    )
    assert result == {
        "10.1/a": (1, 2),
        "10.1/b": (1, 2),
        "10.1/c": (1, 2),
        "10.1/d": (1, 2),
    }


@patch("scilex.citations.citations_tools.requests.get")
def test_crossref_400_not_retried_for_single_doi(mock_get):
    mock_get.return_value = _response(400)
    assert ct.getCrossRefCitationsBatch(["10.1/bad"]) == {}
    assert mock_get.call_count == 1


@patch("scilex.citations.citations_tools.requests.get")
def test_crossref_retries_5xx(mock_get):
    ok = _response(
        200,
        {
            "message": {
                "items": [
                    {
                        "DOI": "10.1/a",
                        "is-referenced-by-count": 5,
                        "references-count": 6,
                    }
                ]
            }
        },
    )
    mock_get.side_effect = [_response(502), ok]
    assert ct.getCrossRefCitationsBatch(["10.1/a"]) == {"10.1/a": (5, 6)}
    assert mock_get.call_count == 2


@patch("scilex.citations.citations_tools.requests.get")
def test_crossref_filter_normalizes_doi_prefix(mock_get):
    mock_get.return_value = _response(200, {"message": {"items": []}})
    ct.getCrossRefCitationsBatch(["https://doi.org/10.1/A", "NA"])
    url = mock_get.call_args[0][0]
    assert "filter=doi:10.1/a&" in url
    assert "rows=1" in url
