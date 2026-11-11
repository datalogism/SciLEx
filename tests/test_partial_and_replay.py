"""Aggregating a partial collection and replaying with the current config."""

import json

import yaml

from scilex.config import SciLExConfig
from scilex.crawlers.aggregate_parallel import parallel_load_all_files

CONFIG_USED = {"keywords": [["graph"]], "years": [2024], "apis": ["OpenAlex"]}


def _write_partial_collection(collect_dir):
    """Query 0 finished, query 1 interrupted (``_state`` marker, one page)."""
    collect_dir.mkdir(parents=True)
    (collect_dir / "config_used.yml").write_text(yaml.dump(CONFIG_USED))
    for query_idx, marker in (("0", "_complete"), ("1", "_state")):
        query_dir = collect_dir / "OpenAlex" / query_idx
        query_dir.mkdir(parents=True)
        (query_dir / "page_1.json").write_text(json.dumps({"results": [{"id": "x"}]}))
        (query_dir / marker).write_text("incomplete" if marker == "_state" else "")


def test_state_marker_is_not_loaded_as_a_page(tmp_path, caplog):
    collect_dir = tmp_path / "partial"
    _write_partial_collection(collect_dir)

    with caplog.at_level("ERROR"):
        parallel_load_all_files(str(collect_dir), CONFIG_USED)

    assert "_state" not in caplog.text


def test_replay_uses_current_config_on_collection_dir(tmp_path, monkeypatch):
    collect_dir = tmp_path / "out" / "review"
    _write_partial_collection(collect_dir)
    current = SciLExConfig({"collect_name": "other", "output_dir": "elsewhere"}, {})
    monkeypatch.setattr(
        SciLExConfig, "from_files", classmethod(lambda *_, **__: current)
    )

    replayed = SciLExConfig.from_collection(str(collect_dir), use_current_config=True)

    assert replayed.main["output_dir"] == str(tmp_path / "out")
    assert replayed.main["collect_name"] == "review"
    assert replayed.main is current.main


def test_llm_scoring_stops_when_cancelled(monkeypatch):
    import threading

    import pandas as pd

    from scilex.llm_relevance import LLMScreeningConfig, score_dataframe

    requests_sent = []
    monkeypatch.setattr(
        "scilex.llm_relevance.request_score",
        lambda *args, **kwargs: requests_sent.append(args) or 5.0,
    )
    cancel_event = threading.Event()
    cancel_event.set()
    papers = pd.DataFrame(
        {"title": ["a", "b"], "DOI": ["NA", "NA"], "abstract": ["x", "y"]}
    )
    config = LLMScreeningConfig.from_dict({"enabled": True, "topic": "t"})

    scored = score_dataframe(papers, config, "key", cancel_event=cancel_event)

    assert requests_sent == []
    assert scored["llm_relevance_score"].isna().all()


def test_aggregation_raises_when_cancelled(tmp_path):
    import threading

    import pytest

    from scilex.pipeline.orchestrator import (
        AggregationCancelled,
        AggregationOptions,
        run_aggregation,
    )

    collect_dir = tmp_path / "out" / "review"
    _write_partial_collection(collect_dir)
    config = SciLExConfig(
        {"collect_name": "review", "output_dir": str(tmp_path / "out")}, {}
    )
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(AggregationCancelled):
        run_aggregation(config, AggregationOptions(cancel_event=cancel_event))


def test_llm_scoring_reports_progress(monkeypatch):
    import pandas as pd

    from scilex.llm_relevance import LLMScreeningConfig, score_dataframe

    monkeypatch.setattr("scilex.llm_relevance.PROGRESS_EVERY", 2)
    monkeypatch.setattr(
        "scilex.llm_relevance.request_score", lambda *args, **kwargs: 5.0
    )
    papers = pd.DataFrame(
        {
            "title": list("abcde"),
            "DOI": ["NA"] * 5,
            "abstract": ["x"] * 5,
        }
    )
    config = LLMScreeningConfig.from_dict({"enabled": True, "topic": "t"})
    reports = []

    score_dataframe(
        papers, config, "key", progress_callback=lambda *args: reports.append(args)
    )

    assert reports == [(2, 5), (4, 5), (5, 5)]
