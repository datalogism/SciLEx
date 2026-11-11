"""Semantic Scholar batch callers (snowball, author h-index) back off on 429/5xx."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from scilex.pipeline import author_metrics
from scilex.snowball import fetcher


@pytest.fixture(autouse=True)
def _no_sleep():
    """Neutralize tenacity waits and rate-limit windows (see test_citations_retry)."""
    with (
        patch("tenacity.nap.time.sleep"),
        patch("ratelimit.decorators.time.sleep"),
        patch(
            "ratelimit.decorators.RateLimitDecorator._RateLimitDecorator__period_remaining",
            return_value=0,
        ),
    ):
        yield


def _response(status=200, payload=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {}
    resp.json.return_value = payload if payload is not None else []
    if status >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
    return resp


@patch("scilex.snowball.fetcher.requests.post")
def test_snowball_retries_429_then_succeeds(mock_post):
    mock_post.side_effect = [_response(429), _response(200, [{"paperId": "p1"}])]
    assert fetcher._batch_request_with_key(["DOI:10.1/x"], "key") == [{"paperId": "p1"}]
    assert mock_post.call_count == 2


@patch("scilex.snowball.fetcher.requests.post")
def test_snowball_does_not_retry_403(mock_post):
    mock_post.return_value = _response(403)
    with pytest.raises(requests.exceptions.HTTPError):
        fetcher._batch_request_with_key(["DOI:10.1/x"], "bad-key")
    assert mock_post.call_count == 1


def test_author_batch_retries_429_then_succeeds():
    session = MagicMock()
    session.post.side_effect = [_response(429), _response(200, [{"hIndex": 7}])]
    assert author_metrics._post_batch("author", ["a1"], "hIndex", "key", session) == [
        {"hIndex": 7}
    ]
    assert session.post.call_count == 2


def test_author_batch_gives_up_after_three_attempts():
    session = MagicMock()
    session.post.return_value = _response(503)
    assert author_metrics._post_batch(
        "author", ["a1", "a2"], "hIndex", None, session
    ) == [
        None,
        None,
    ]
    assert session.post.call_count == 3
