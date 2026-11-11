"""Tests for the generic paginated collection loop (API_collector.runCollect).

No real HTTP: collectors are driven by scripted responses.
"""

import json
import os
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest
import requests

from scilex.crawlers import collector_collection as cc
from scilex.crawlers.circuit_breaker import CircuitBreakerOpenError
from scilex.crawlers.collectors.arxiv import Arxiv_collector
from scilex.crawlers.collectors.base import API_collector
from scilex.crawlers.collectors.elsevier import Elsevier_collector
from scilex.crawlers.collectors.springer import Springer_collector


def _data_query(max_articles=-1, last_page=0, coll_art=0, state=0, **extra):
    query = {
        "year": 2020,
        "keyword": ["kw"],
        "max_articles_per_query": max_articles,
        "id_collect": 0,
        "total_art": 0,
        "last_page": last_page,
        "coll_art": coll_art,
        "state": state,
    }
    query.update(extra)
    return query


def _page(n_results, total, page=1):
    return {
        "date_search": "2020-01-01",
        "id_collect": 0,
        "page": page,
        "total": total,
        "results": [{"title": f"t{i}"} for i in range(n_results)],
    }


def _fake_response(**attrs):
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.elapsed.total_seconds.return_value = 0.01
    for name, value in attrs.items():
        setattr(response, name, value)
    return response


class ScriptedCollector(API_collector):
    """Collector whose 'HTTP' answers come from a script (pages or exceptions)."""

    def __init__(self, tmp_path, script, **query_kwargs):
        super().__init__(_data_query(**query_kwargs), str(tmp_path), None)
        self.api_name = "Fake"
        self.rate_limit = 0
        self.max_by_page = 2
        self.script = list(script)
        self.requested_urls = []

    def get_configurated_url(self):
        return "http://fake/search?offset={}"

    def api_call_decorator(self, url, max_retries=3, headers=None):
        self.requested_urls.append(url)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _fake_response(page_data=item)

    def parsePageResults(self, response, page):
        return dict(response.page_data, page=page)


def _http_error(status):
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    return requests.exceptions.HTTPError(f"{status} error", response=response)


def _query_dir(tmp_path):
    return tmp_path / "Fake" / "0"


class TestRunCollectResilience:
    def test_full_run_marks_complete(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [_page(2, 3), _page(1, 3)])
        result = collector.runCollect()

        assert result["state"] == 1
        assert result["coll_art"] == 3
        assert result["total_art"] == 3
        assert set(result) == {
            "state",
            "last_page",
            "total_art",
            "coll_art",
            "update_date",
            "id_collect",
        }
        query_dir = _query_dir(tmp_path)
        assert (query_dir / "_complete").exists()
        assert not (query_dir / "_state").exists()
        saved = json.loads((query_dir / "page_1").read_text())
        assert set(saved) >= {"results", "total"}
        assert (query_dir / "page_2").exists()

    def test_buffered_pages_flushed_when_api_fails(self, tmp_path):
        collector = ScriptedCollector(
            tmp_path, [_page(2, 10), CircuitBreakerOpenError("Fake", 60)]
        )
        result = collector.runCollect()

        assert result["state"] == 0
        query_dir = _query_dir(tmp_path)
        assert (query_dir / "page_1").exists()
        assert not (query_dir / "_complete").exists()
        assert (query_dir / "_state").exists()

    def test_buffered_pages_flushed_on_unexpected_exception(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [_page(2, 10), _page(2, 10)])
        original_save = collector.savePageResults
        calls = []

        def exploding_save(data, page):
            original_save(data, page)
            calls.append(page)
            if len(calls) == 2:
                raise KeyboardInterrupt  # not an Exception: bypasses handlers

        collector.savePageResults = exploding_save
        with pytest.raises(KeyboardInterrupt):
            collector.runCollect()
        assert (_query_dir(tmp_path) / "page_1").exists()
        assert (_query_dir(tmp_path) / "page_2").exists()

    def test_parse_error_is_not_complete(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [_page(2, 10), {"broken": True}])
        result = collector.runCollect()
        assert result["state"] == 0
        assert not (_query_dir(tmp_path) / "_complete").exists()

    def test_http_error_is_not_complete(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [_http_error(500)])
        result = collector.runCollect()
        assert result["state"] == 0

    def test_persistent_throttle_is_not_complete(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [_page(2, 10), _http_error(429)])
        with patch.object(collector, "_try_vpn_rotation", return_value=False):
            result = collector.runCollect()
        assert result["state"] == 0
        assert not (_query_dir(tmp_path) / "_complete").exists()

    def test_throttle_retries_same_page_after_vpn_rotation(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [_http_error(429), _page(1, 1)])
        with patch.object(collector, "_try_vpn_rotation", return_value=True):
            result = collector.runCollect()
        assert result["state"] == 1
        assert collector.requested_urls == [
            "http://fake/search?offset=0",
            "http://fake/search?offset=0",
        ]

    def test_max_articles_reached_counts_as_done(self, tmp_path):
        collector = ScriptedCollector(
            tmp_path, [_page(2, 100), _page(2, 100)], max_articles=3
        )
        result = collector.runCollect()
        assert result["state"] == 1
        assert result["coll_art"] == 4
        assert (_query_dir(tmp_path) / "_complete").exists()

    def test_max_articles_precheck_before_first_fetch(self, tmp_path):
        """No UnboundLocalError when the limit is already met before any fetch."""
        collector = ScriptedCollector(
            tmp_path, [], max_articles=5, coll_art=5, last_page=2
        )
        result = collector.runCollect()
        assert result["state"] == 1
        assert collector.requested_urls == []

    def test_already_completed_returns_state_dict(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [], state=1)
        result = collector.runCollect()
        assert result["state"] == 1
        assert result["id_collect"] == 0

    def test_resume_starts_after_last_page(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [_page(1, 5)], last_page=2)
        collector.runCollect()
        assert collector.requested_urls == ["http://fake/search?offset=4"]
        assert (_query_dir(tmp_path) / "page_3").exists()


class TestWorkerClosesSession:
    def _run_worker(self, tmp_path, collector_class):
        progress = Queue()
        query = {"id_collect": 0, "keyword": ["a"], "year": 2020}
        with patch.dict(cc.api_collectors, {"FakeAPI": collector_class}):
            cc._run_job_collects_worker(
                "FakeAPI",
                [{"query": query, "api": "FakeAPI"}],
                {},
                str(tmp_path),
                "c",
                progress,
            )
        return progress.get_nowait()

    def test_close_session_called_on_success(self, tmp_path):
        closed = []

        class Fake:
            def __init__(self, *args):
                pass

            def load_rate_limit_from_config(self, rate_limits=None):
                pass

            def runCollect(self):
                return {"coll_art": 1}

            def close_session(self):
                closed.append(True)

        assert self._run_worker(tmp_path, Fake)["success"] is True
        assert closed == [True]

    def test_close_session_called_when_collect_raises(self, tmp_path):
        closed = []

        class Fake:
            def __init__(self, *args):
                pass

            def load_rate_limit_from_config(self, rate_limits=None):
                pass

            def runCollect(self):
                raise RuntimeError("boom ?apikey=SECRET")

            def close_session(self):
                closed.append(True)

        message = self._run_worker(tmp_path, Fake)
        assert message["success"] is False
        assert "SECRET" not in message["error"]
        assert closed == [True]


class TestSpringerEndpoints:
    def _springer(self, tmp_path, **query_kwargs):
        collector = Springer_collector(
            _data_query(**query_kwargs), str(tmp_path), "KEY"
        )
        collector.rate_limit = 0
        collector.max_by_page = 2
        return collector

    @staticmethod
    def _response(n_records, total):
        response = _fake_response()
        response.json.return_value = {
            "records": [{"title": f"r{i}"} for i in range(n_records)],
            "result": [{"total": str(total)}],
        }
        return response

    def test_urls_are_templates_with_one_placeholder(self, tmp_path):
        collector = self._springer(tmp_path)
        endpoints = collector._get_api_endpoints()
        assert len(endpoints) == 2
        assert all(url.endswith("&s={}") for url in endpoints)
        assert collector.get_configurated_url() == endpoints[0]
        assert "meta" in endpoints[0]
        assert "openaccess" in endpoints[1]

    def test_counts_progress_and_both_endpoints(self, tmp_path):
        collector = self._springer(tmp_path)
        responses = [
            self._response(2, 3),
            self._response(1, 3),  # meta endpoint done (3 records)
            self._response(2, 2),  # openaccess endpoint: single page
        ]
        with patch.object(
            collector, "api_call_decorator", side_effect=responses
        ) as call:
            result = collector.runCollect()

        urls = [c.args[0] for c in call.call_args_list]
        assert [u.rsplit("&s=", 1)[1] for u in urls] == ["1", "3", "1"]
        # Each record counted exactly once, progress is reported
        assert collector.nb_art_collected == 5
        assert result["coll_art"] == 5
        assert result["state"] == 1
        assert result["last_page"] == 3
        for page_number in (1, 2, 3):
            assert os.path.exists(
                os.path.join(collector.get_collectDir(), f"page_{page_number}")
            )

    def test_endpoint_failure_leaves_query_incomplete(self, tmp_path):
        collector = self._springer(tmp_path)
        responses = [self._response(2, 2), _http_error(500)]
        with patch.object(collector, "api_call_decorator", side_effect=responses):
            result = collector.runCollect()
        assert result["state"] == 0
        assert os.path.exists(os.path.join(collector.get_collectDir(), "page_1"))


class TestHooks:
    def test_default_endpoint_is_configurated_url(self, tmp_path):
        collector = ScriptedCollector(tmp_path, [])
        assert collector._get_api_endpoints() == ["http://fake/search?offset={}"]
        assert collector.get_auth_headers() is None

    def test_arxiv_none_entries_are_dropped_before_counting(self, tmp_path):
        collector = Arxiv_collector(_data_query(), str(tmp_path), None)
        collector.rate_limit = 0
        page = _page(0, 3)
        page["results"] = [{"id": 1}, None, {"id": 2}]
        cleaned = collector._post_process_page(page)
        assert cleaned["results"] == [{"id": 1}, {"id": 2}]

    def test_elsevier_headers_hook(self, tmp_path):
        collector = Elsevier_collector(_data_query(), str(tmp_path), "KEY", "TOK")
        assert collector.get_auth_headers() == {
            "X-ELS-APIKey": "KEY",
            "Accept": "application/json",
            "X-ELS-Insttoken": "TOK",
        }

    def test_elsevier_page_exposes_total_for_pagination(self, tmp_path):
        collector = Elsevier_collector(_data_query(), str(tmp_path), "KEY")
        response = MagicMock()
        response.json.return_value = {
            "search-results": {
                "opensearch:totalResults": "60",
                "entry": [{"dc:title": "x"}],
            }
        }
        page_data = collector.parsePageResults(response, 1)
        assert page_data["total"] == 60
        assert page_data["total_nb"] == 60


class TestOpenAlexRunCollect:
    @staticmethod
    def _response(n_results, next_cursor):
        response = _fake_response()
        response.json.return_value = {
            "meta": {"count": 10, "next_cursor": next_cursor},
            "results": [{"id": i} for i in range(n_results)],
        }
        return response

    def _collector(self, tmp_path, **query_kwargs):
        from scilex.crawlers.collectors.openalex import OpenAlex_collector

        collector = OpenAlex_collector(_data_query(**query_kwargs), str(tmp_path), None)
        collector.rate_limit = 0
        return collector

    def test_cursor_exhausted_marks_complete(self, tmp_path):
        collector = self._collector(tmp_path)
        responses = [self._response(2, "c2"), self._response(2, None)]
        with patch.object(collector, "api_call_decorator", side_effect=responses):
            result = collector.runCollect()
        assert result["state"] == 1
        assert result["coll_art"] == 4
        query_dir = tmp_path / "OpenAlex" / "0"
        assert (query_dir / "_complete").exists()
        assert (query_dir / "page_2").exists()

    def test_failure_flushes_buffer_and_stays_incomplete(self, tmp_path):
        collector = self._collector(tmp_path)
        responses = [self._response(2, "c2"), _http_error(429)]
        with (
            patch.object(collector, "api_call_decorator", side_effect=responses),
            patch.object(collector, "_try_vpn_rotation", return_value=False),
        ):
            result = collector.runCollect()
        assert result["state"] == 0
        query_dir = tmp_path / "OpenAlex" / "0"
        assert (query_dir / "page_1").exists()
        assert not (query_dir / "_complete").exists()
