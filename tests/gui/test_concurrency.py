"""Jobs that run together: resources, merged writes, log attribution."""

import logging
import threading
import time
from pathlib import Path

import pandas as pd
import pytest

from scilex.gui.services import results_store
from scilex.gui.services.extend import read_results, write_results
from scilex.gui.services.jobs import (
    READ,
    ROWS,
    WRITE,
    JobConflictError,
    JobRunner,
    conflicts,
    results_resource,
    zotero_resource,
)
from scilex.gui.services.workspace import Review

CONFIG = object()


def wait_until_done(job, timeout=10.0):
    deadline = time.monotonic() + timeout
    while job.is_active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not job.is_active, f"job still {job.status}"


def make_review(tmp_path: Path, name: str) -> Review:
    review = Review(folder=tmp_path / name, name=name, output_root=tmp_path / "out")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    return review


def no_aggregation(config, options, progress_callback):
    pass


@pytest.fixture
def blocked_collect():
    """A runner whose collection waits for ``release``."""
    release = threading.Event()

    def collection(config, progress_callback, cancel_event):
        release.wait(10)

    runner = JobRunner(collection, no_aggregation)
    yield runner, release
    release.set()


def test_conflict_rules():
    assert not conflicts(READ, ROWS) and not conflicts(WRITE, READ)
    assert not conflicts(WRITE, WRITE)
    assert conflicts(WRITE, ROWS) and conflicts(ROWS, ROWS)


def test_second_collection_is_refused_and_names_the_first(tmp_path, blocked_collect):
    runner, release = blocked_collect
    first = make_review(tmp_path, "rag_kg")
    other = make_review(tmp_path, "survey_re")
    job = runner.start_pipeline(first, CONFIG)
    with pytest.raises(JobConflictError, match="collection on rag_kg"):
        runner.start_pipeline(other, CONFIG)  # APIs and VPN are shared
    release.set()
    wait_until_done(job)


def test_readers_and_other_reviews_run_during_a_collection(tmp_path, blocked_collect):
    runner, release = blocked_collect
    review = make_review(tmp_path, "rag_kg")
    other = make_review(tmp_path, "survey_re")
    collect = runner.start_pipeline(review, CONFIG)

    chart = runner.start_task(
        review,
        "analysis-report",
        lambda job: "charts",
        resources=[results_resource(review.id, READ)],
    )
    wait_until_done(chart)
    assert chart.message == "charts" and collect.is_active

    # Rows of the collected review are taken; another review is free.
    with pytest.raises(JobConflictError, match="collection on rag_kg"):
        runner.start_task(review, "consolidate", lambda job: None)
    elsewhere = runner.start_task(
        other,
        "analysis-crossref",
        lambda job: "ok",
        resources=[results_resource(other.id, WRITE)],
    )
    wait_until_done(elsewhere)
    assert elsewhere.message == "ok"
    release.set()
    wait_until_done(collect)


def test_rows_wait_for_an_enricher_of_the_same_review_only(tmp_path):
    runner = JobRunner(lambda *a, **k: None, no_aggregation)
    review = make_review(tmp_path, "rag_kg")
    other = make_review(tmp_path, "survey_re")
    release = threading.Event()
    enricher = runner.start_task(
        review,
        "analysis-orkg",
        lambda job: release.wait(5) and "done",
        resources=[results_resource(review.id, WRITE)],
    )
    try:
        assert runner.conflicting_job(review, "consolidate") is enricher
        with pytest.raises(JobConflictError, match="analysis-orkg on rag_kg"):
            runner.start_task(review, "consolidate", lambda job: None)
        # Another enricher of the same review merges its own cells: allowed.
        second = runner.start_task(
            review,
            "analysis-lpwc",
            lambda job: "ok",
            resources=[results_resource(review.id, WRITE)],
        )
        wait_until_done(second)
        # The same action twice on one review is refused.
        with pytest.raises(JobConflictError):
            runner.start_task(
                review,
                "analysis-orkg",
                lambda job: None,
                resources=[results_resource(review.id, WRITE)],
            )
        assert runner.conflicting_job(other, "consolidate") is None
    finally:
        release.set()
        wait_until_done(enricher)


def test_zotero_writes_to_one_library_are_exclusive(tmp_path):
    runner = JobRunner(lambda *a, **k: None, no_aggregation)
    a, b = make_review(tmp_path, "a"), make_review(tmp_path, "b")
    release = threading.Event()
    push = runner.start_task(
        a,
        "export",
        lambda job: release.wait(5) and "pushed",
        resources=[zotero_resource("group:1")],
    )
    try:
        with pytest.raises(JobConflictError):
            runner.start_task(
                b, "annotate", lambda job: None, resources=[zotero_resource("group:1")]
            )
        other = runner.start_task(
            b, "annotate", lambda job: "ok", resources=[zotero_resource("group:2")]
        )
        wait_until_done(other)
    finally:
        release.set()
        wait_until_done(push)


def _results(review: Review) -> None:
    write_results(
        pd.DataFrame(
            {
                "title": ["Graph RAG", "DocRED", "DocRED"],
                "itemType": ["journalArticle"] * 3,
                "DOI": ["10.1/a", "10.1/d", "10.1/d"],  # a paper kept twice on purpose
                "date": ["2024", "2019", "2019"],
                "abstract": ["NA", "NA", "NA"],
            }
        ),
        review.results_path,
    )


def test_two_enrichers_running_together_keep_both_changes(tmp_path):
    review = make_review(tmp_path, "rag_kg")
    _results(review)
    runner = JobRunner(lambda *a, **k: None, no_aggregation)
    both_read = threading.Barrier(2, timeout=5)

    def enricher(column: str, values: list[str]):
        def body(job):
            data = read_results(review.results_path)
            before = data.copy()
            both_read.wait()  # both read the same file before either writes
            data[column] = values
            results_store.write_changes(review.results_path, before, data)
            return column

        return body

    one = runner.start_task(
        review,
        "analysis-crossref",
        enricher("abstract", ["Retrieval.", "Docs.", "Docs (copy)."]),
        resources=[results_resource(review.id, WRITE)],
    )
    two = runner.start_task(
        review,
        "analysis-orkg",
        enricher("orkg_research_problems", ["RAG", "relation extraction", "RE"]),
        resources=[results_resource(review.id, WRITE)],
    )
    wait_until_done(one)
    wait_until_done(two)
    assert one.status == two.status == "completed", (one.error, two.error)

    data = read_results(review.results_path)
    assert data["abstract"].tolist() == ["Retrieval.", "Docs.", "Docs (copy)."]
    assert data["orkg_research_problems"].tolist() == [
        "RAG",
        "relation extraction",
        "RE",
    ]


def test_write_columns_keeps_rows_and_columns_it_does_not_own(tmp_path):
    review = make_review(tmp_path, "rag_kg")
    _results(review)
    mine = read_results(review.results_path)
    mine["pwc_tasks"] = ["T1", "T2", "T3"]

    # Meanwhile, another writer filled a column and a paper was added.
    other = read_results(review.results_path)
    other["abstract"] = ["A", "B", "C"]
    extra = pd.DataFrame(
        [{"title": "New", "itemType": "preprint", "DOI": "10.1/n", "date": "2025"}]
    )
    write_results(pd.concat([other, extra], ignore_index=True), review.results_path)

    results_store.write_columns(review.results_path, mine, ["pwc_tasks"])
    data = read_results(review.results_path)
    assert len(data) == 4
    assert data["abstract"].tolist()[:3] == ["A", "B", "C"]
    assert data["pwc_tasks"].tolist()[:3] == ["T1", "T2", "T3"]


def test_anonymous_pipeline_threads_log_to_the_collection_only(tmp_path):
    release = threading.Event()
    logged = threading.Event()

    def collection(config, progress_callback, cancel_event):
        def worker():
            logging.getLogger("scilex.test").warning("from a collector thread")
            logged.set()

        threading.Thread(target=worker, name="Worker-OpenAlex").start()
        release.wait(5)

    runner = JobRunner(collection, no_aggregation)
    review, other = make_review(tmp_path, "a"), make_review(tmp_path, "b")
    side = runner.start_task(
        other,
        "analysis-report",
        lambda job: release.wait(5) and "ok",
        resources=[results_resource(other.id, READ)],
    )
    collect = runner.start_pipeline(review, CONFIG)
    assert logged.wait(5)
    release.set()
    wait_until_done(collect)
    wait_until_done(side)
    assert any("from a collector thread" in line for line in collect.logs)
    assert not any("from a collector thread" in line for line in side.logs)
