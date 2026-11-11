"""Regression tests for the pipeline bugs found on 2026-10-25."""

import logging
import threading
from unittest.mock import patch

import pandas as pd
import pytest
from pydantic import ValidationError

from scilex.pipeline.jobs import WorkerThreadFilter
from scilex.pipeline.orchestrator import AggregationCancelled
from scilex.pipeline.ranking import build_relevance_scorer
from scilex.pipeline.report import collection_warning
from scilex.settings import ScilexSettings
from tests.test_orchestrator_characterization import _build_config, _run

MINIMAL = {
    "name": "review",
    "search": {"keywords": [["a"]], "years": [2024], "apis": ["OpenAlex"]},
}


SEARCH_KEYS = {"keywords", "bonus_keywords", "years", "apis"}


def _with(**changes):
    raw = {**MINIMAL, "search": {**MINIMAL["search"]}}
    for key, value in changes.items():
        (raw["search"] if key in SEARCH_KEYS else raw)[key] = value
    return raw


# --- Cancellation -----------------------------------------------------------


def test_cancel_during_filters_stops_before_citations(tmp_path):
    config, _ = _build_config(tmp_path)
    cancel_event = threading.Event()

    def cancel_while_filtering(_ctx, df):
        cancel_event.set()
        return df

    with (
        patch(
            "scilex.pipeline.orchestrator._report_and_filter_abstracts",
            side_effect=cancel_while_filtering,
        ),
        patch("scilex.pipeline.orchestrator._process_citations") as citations,
        pytest.raises(AggregationCancelled),
    ):
        _run(config, cancel_event=cancel_event)
    citations.assert_not_called()


# --- Aggregated CSV ---------------------------------------------------------


def test_aggregated_csv_has_no_index_column(tmp_path):
    config, collect_dir = _build_config(tmp_path)
    _run(config)
    header = (collect_dir / "aggregated.csv").read_text().splitlines()[0]
    assert not header.startswith('"";') and not header.startswith(";")
    assert not list((collect_dir).glob(".aggregated_*.tmp"))


# --- Partial collection warning ----------------------------------------------


def _collection(tmp_path, complete_queries):
    config = {"keywords": [["a", "b"]], "years": [2024], "apis": ["HAL"]}
    for index in range(2):
        query_dir = tmp_path / "HAL" / str(index)
        query_dir.mkdir(parents=True)
        if index in complete_queries:
            (query_dir / "_complete").write_text("")
    return config


def test_partial_collection_is_reported(tmp_path):
    config = _collection(tmp_path, complete_queries={0})
    lines = collection_warning(str(tmp_path), config)
    assert "1 of 2 queries completed" in lines[0]
    assert "HAL (1/2)" in lines[0]


def test_complete_collection_has_no_warning(tmp_path):
    config = _collection(tmp_path, complete_queries={0, 1})
    assert collection_warning(str(tmp_path), config) == []


def test_reports_show_the_partial_warning(tmp_path):
    config, collect_dir = _build_config(tmp_path)
    (collect_dir / "HAL" / "0" / "_complete").unlink(missing_ok=True)
    _run(config)
    assert "partial collection" in (collect_dir / "prisma_report.md").read_text()
    assert "partial collection" in (collect_dir / "aggregation_report.md").read_text()


# --- Schema -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["../evil", "/abs", "a/b", "a\\b", ".hidden", "  "])
def test_name_must_be_a_plain_folder_name(name):
    with pytest.raises(ValidationError, match="name"):
        ScilexSettings.model_validate(_with(name=name))


def test_name_with_spaces_and_accents_is_accepted():
    ScilexSettings.model_validate(_with(name="Revue métabolomique 2024"))


def test_empty_keyword_is_rejected():
    with pytest.raises(ValidationError, match="empty strings"):
        ScilexSettings.model_validate(_with(keywords=[["a", " "]]))


def test_empty_bonus_keyword_is_rejected():
    with pytest.raises(ValidationError, match="empty strings"):
        ScilexSettings.model_validate(_with(bonus_keywords=[""]))


# --- Ranking ----------------------------------------------------------------

PAPER = {
    "title": "a study",
    "abstract": "a " * 10,
    "quality_score": 50,
    "itemType": "journalArticle",
    "nb_citation": 1000,
}


def _score(weights):
    config = {"quality_filters": {"relevance_weights": weights}} if weights else None
    return build_relevance_scorer([["a"]], has_citations=True, config=config)(
        pd.Series(PAPER)
    )


def test_default_weights_are_unchanged():
    assert _score(None) == _score(
        {"keywords": 0.45, "quality": 0.25, "itemtype": 0.2, "citations": 0.1}
    )


def test_weights_not_summing_to_one_stay_on_ten():
    weights = {"keywords": 4, "quality": 4, "itemtype": 4, "citations": 4}
    assert _score(weights) <= 10


# --- Job log filter -----------------------------------------------------------


@pytest.mark.parametrize(
    "thread_name, accepted",
    [
        ("Worker-OpenAlex", True),
        ("ThreadPoolExecutor-0_1", True),
        ("Thread-3", True),
        ("MainThread", False),
    ],
)
def test_worker_thread_filter_accepts_pipeline_threads(thread_name, accepted):
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "msg", None, None)
    record.threadName = thread_name
    record.thread = -1
    assert WorkerThreadFilter(set()).filter(record) is accepted
