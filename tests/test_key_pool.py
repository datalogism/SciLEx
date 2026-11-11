"""Tests for the API key pool and its collector integration (issue #6)."""

import threading
from unittest.mock import MagicMock

import pytest
import requests

from scilex.crawlers.collectors import PubMed_collector, SemanticScholar_collector
from scilex.crawlers.key_pool import KeyPool, first_key, get_shared_pool, normalize_keys
from scilex.crawlers.utils import sanitize_secrets


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TestKeyPool:
    def test_round_robin(self):
        pool = KeyPool(["a", "b", "c"])
        assert [pool.next_key() for _ in range(5)] == ["a", "b", "c", "a", "b"]

    def test_failed_key_skipped_then_recovers(self):
        clock = FakeClock()
        pool = KeyPool(["a", "b"], clock=clock)
        pool.mark_failed("a", cooldown=10)
        assert [pool.next_key() for _ in range(3)] == ["b", "b", "b"]
        clock.now = 11
        assert {pool.next_key(), pool.next_key()} == {"a", "b"}

    def test_all_failed_returns_soonest_to_recover(self):
        clock = FakeClock()
        pool = KeyPool(["a", "b"], clock=clock)
        pool.mark_failed("a", cooldown=100)
        pool.mark_failed("b", cooldown=10)
        assert pool.next_key() == "b"

    def test_thread_safe_distribution(self):
        pool = KeyPool(["a", "b", "c", "d"])
        results = []

        def work():
            results.extend(pool.next_key() for _ in range(400))

        threads = [threading.Thread(target=work) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert all(results.count(key) == 800 for key in "abcd")

    def test_normalize_and_first(self):
        assert normalize_keys(None) == []
        assert normalize_keys("k") == ["k"]
        assert normalize_keys(["a", "", " ", "b"]) == ["a", "b"]
        assert first_key(["x", "y"]) == "x"
        assert first_key(None) is None

    def test_shared_pool_identity(self):
        assert get_shared_pool(["s1", "s2"]) is get_shared_pool(["s1", "s2"])

    def test_empty_pool_rejected(self):
        with pytest.raises(ValueError):
            KeyPool([])


def _query():
    return {
        "keyword": ["graph"],
        "year": 2024,
        "id_collect": 0,
        "total_art": 0,
        "coll_art": 0,
        "last_page": 0,
        "state": 0,
    }


def _response(status):
    response = MagicMock()
    response.status_code = status
    if status >= 400:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=response
        )
    return response


class TestCollectorIntegration:
    def test_string_key_unchanged(self):
        collector = SemanticScholar_collector(_query(), "/tmp/t", "single")
        assert collector.api_key == "single"
        assert collector._key_pool is None

    def test_list_key_rotates_headers_per_request(self):
        collector = SemanticScholar_collector(_query(), "/tmp/t", ["k1", "k2"])
        collector.session = MagicMock()
        collector.session.get.return_value = _response(200)
        collector._rate_limit_wait = lambda: None
        for _ in range(2):
            collector.api_call_decorator(
                "http://x", headers=collector.get_auth_headers()
            )
        sent = [
            call.kwargs["headers"]["x-api-key"]
            for call in collector.session.get.call_args_list
        ]
        assert sorted(sent) == ["k1", "k2"]

    def test_key_in_url_is_rewritten_and_429_fails_over(self):
        keys = ["pm-key-A", "pm-key-B"]
        collector = PubMed_collector(_query(), "/tmp/t", keys)
        collector.session = MagicMock()
        collector._rate_limit_wait = lambda: None
        collector.session.get.side_effect = [_response(429), _response(200)]
        url = "http://x?term=a&api_key=pm-key-A"
        collector.api_call_decorator(url)
        first_url = collector.session.get.call_args_list[0].args[0]
        second_url = collector.session.get.call_args_list[1].args[0]
        assert first_url != second_url
        assert {first_url[-8:], second_url[-8:]} == {"pm-key-A", "pm-key-B"}

    def test_auth_error_switches_key_then_succeeds(self):
        collector = SemanticScholar_collector(_query(), "/tmp/t", ["bad", "good"])
        collector.session = MagicMock()
        collector._rate_limit_wait = lambda: None
        collector.session.get.side_effect = [_response(403), _response(200)]
        response = collector.api_call_decorator(
            "http://x", headers=collector.get_auth_headers()
        )
        assert response.status_code == 200
        assert collector.session.get.call_count == 2

    def test_single_key_auth_error_still_raises(self):
        collector = SemanticScholar_collector(_query(), "/tmp/t", "only")
        collector.session = MagicMock()
        collector._rate_limit_wait = lambda: None
        collector.session.get.return_value = _response(401)
        with pytest.raises(requests.exceptions.HTTPError):
            collector.api_call_decorator("http://x")
        assert collector.session.get.call_count == 1


def test_sanitize_masks_every_pool_key():
    text = "GET http://x?api_key=AAA111&other=1 then apikey=BBB222"
    masked = sanitize_secrets(text)
    assert "AAA111" not in masked and "BBB222" not in masked
