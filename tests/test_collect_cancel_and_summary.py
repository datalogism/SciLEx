"""Regression tests: collection cancel, partial summary, scilex-report default folder."""

import threading
import time
from pathlib import Path

from scilex import report_charts
from scilex.crawlers.adaptive_rate_limiter import AdaptiveRateLimiter
from scilex.crawlers.collectors.base import API_collector
from scilex.gui.services.collect_summary import api_rows


def test_collector_stops_paginating_when_cancelled():
    collector = API_collector.__new__(API_collector)
    collector.api_name = "TestAPI"
    collector.collectId = 0
    collector.cancel_event = threading.Event()
    collector.cancel_event.set()
    assert collector._collect_endpoint("https://x/{}", {}, resume=False) is False


def test_cancelled_sleep_returns_immediately():
    collector = API_collector.__new__(API_collector)
    collector.cancel_event = threading.Event()
    collector.cancel_event.set()
    start = time.monotonic()
    collector._sleep(30)
    assert time.monotonic() - start < 1


def test_limiter_wait_is_interrupted_by_cancel():
    limiter = AdaptiveRateLimiter("TestAPI")
    limiter._extra_delay = 30
    limiter._last_call_time = time.monotonic()
    cancel_event = threading.Event()
    cancel_event.set()
    start = time.monotonic()
    limiter.wait(1.0, cancel_event)
    assert time.monotonic() - start < 1


def test_api_with_incomplete_queries_is_partial():
    stats = {"HAL": {"completed": 4, "total": 4, "articles": 10, "incomplete": 1}}
    (row,) = api_rows(stats, [], None, active=False)
    assert row.state == "partial"
    assert "1/4 queries incomplete" in row.reason


def test_api_with_all_queries_complete_is_done():
    stats = {"HAL": {"completed": 4, "total": 4, "articles": 10, "incomplete": 0}}
    (row,) = api_rows(stats, [], None, active=False)
    assert row.state == "done"


def test_report_defaults_to_the_configured_collect_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scilex.settings.resolve.resolve_main_config",
        lambda: {"output_dir": str(tmp_path), "collect_name": "My review"},
    )
    collect_dir = report_charts._configured_collect_dir()
    assert collect_dir.parent == Path(tmp_path)
    assert collect_dir.name  # normalized, non-empty folder name


def test_summary_counts_queries_never_started(caplog):
    from scilex.crawlers.collector_collection import _log_api_summary

    stats = {"completed": 1, "total": 3, "articles": 5, "incomplete": 0}
    with caplog.at_level("INFO"):
        _log_api_summary("HAL", stats)
    assert "Partial" in caplog.text and "2 of 3 queries not finished" in caplog.text

    caplog.clear()
    with caplog.at_level("INFO"):
        _log_api_summary("HAL", {**stats, "completed": 3})
    assert "Complete: 5 papers from 3 queries" in caplog.text
