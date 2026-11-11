"""Tests for the GUI background job runner (pipeline functions mocked)."""

import logging
import threading
import time
from pathlib import Path

import pytest

from scilex.gui.services.jobs import JobConflictError, JobRunner
from scilex.gui.services.workspace import Review
from scilex.pipeline import jobs as job_states

REVIEW = Review(folder=Path("/tmp/review"), name="rag", output_root=Path("/tmp/out"))
CONFIG = object()  # the runner only forwards it to the pipeline functions


def wait_until_done(job, timeout=5.0):
    """Wait for the job thread to reach a terminal state."""
    deadline = time.monotonic() + timeout
    while job.is_active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not job.is_active, f"job still {job.status}"


def fake_collection(config, progress_callback, cancel_event):
    """Report two progress steps and log a line, like the real collector."""
    logging.getLogger("scilex.test").warning("collecting from fake API")
    progress_callback({"OpenAlex": {"articles": 3}}, 1, 2)
    progress_callback({"OpenAlex": {"articles": 5}}, 2, 2)


def fake_aggregation(config, options, progress_callback):
    """Report aggregation progress."""
    progress_callback("ranking", 50, "Ranking papers…")


def test_successful_pipeline():
    seen_options = []

    def aggregation(config, options, progress_callback):
        seen_options.append(options)
        fake_aggregation(config, options, progress_callback)

    runner = JobRunner(fake_collection, aggregation)
    job = runner.start_pipeline(REVIEW, CONFIG, skip_citations=True)
    wait_until_done(job)

    assert job.status == job_states.COMPLETED
    assert job.progress == 100
    assert job.api_stats == {"OpenAlex": {"articles": 5}}
    assert seen_options[0].skip_citations is True
    assert any("collecting from fake API" in line for line in job.logs)
    assert job.finished_at is not None


def test_failure_in_aggregation_marks_job_failed():
    def broken_aggregation(config, options, progress_callback):
        raise ValueError("no config_used.yml")

    runner = JobRunner(fake_collection, broken_aggregation)
    job = runner.start_pipeline(REVIEW, CONFIG)
    wait_until_done(job)

    assert job.status == job_states.FAILED
    assert job.error == "no config_used.yml"
    assert "no config_used.yml" in job.message


def test_cancel_during_collection_skips_aggregation():
    started = threading.Event()
    aggregation_calls = []

    def slow_collection(config, progress_callback, cancel_event):
        started.set()
        assert cancel_event.wait(5)

    runner = JobRunner(slow_collection, lambda *args: aggregation_calls.append(args))
    job = runner.start_pipeline(REVIEW, CONFIG)
    assert started.wait(5)

    assert runner.cancel(job.id)
    wait_until_done(job)

    assert job.status == job_states.CANCELLED
    assert aggregation_calls == []


def test_only_one_active_job():
    release = threading.Event()

    def blocking_collection(config, progress_callback, cancel_event):
        release.wait(5)

    runner = JobRunner(blocking_collection, fake_aggregation)
    job = runner.start_pipeline(REVIEW, CONFIG)
    try:
        with pytest.raises(JobConflictError):
            runner.start_pipeline(REVIEW, CONFIG)
        assert runner.active_job() is job
    finally:
        release.set()
        wait_until_done(job)

    assert runner.latest_for(REVIEW.id) is job
    assert runner.active_job() is None


def test_cancel_finished_job_is_refused():
    runner = JobRunner(fake_collection, fake_aggregation)
    job = runner.start_pipeline(REVIEW, CONFIG)
    wait_until_done(job)

    assert runner.cancel(job.id) is False
    assert runner.cancel("unknown") is False
    assert job.status == job_states.COMPLETED


@pytest.mark.parametrize("terminal", job_states.TERMINAL_STATUSES)
def test_transitions_never_leave_terminal_states(terminal):
    assert not job_states.transition_allowed(terminal, job_states.RUNNING)


def test_cancelling_never_returns_to_running():
    assert not job_states.transition_allowed(job_states.CANCELLING, job_states.RUNNING)
    assert job_states.transition_allowed(job_states.CANCELLING, job_states.CANCELLED)


def test_generic_task_reports_result_and_logs():
    def body(job):
        logging.getLogger("scilex.test").warning("exporting")
        job.progress = 50
        job.result = "/tmp/out.bib"
        return "Exported 3 papers."

    runner = JobRunner(fake_collection, fake_aggregation)
    job = runner.start_task(REVIEW, "export", body)
    wait_until_done(job)

    assert job.status == job_states.COMPLETED
    assert job.kind == "export"
    assert job.result == "/tmp/out.bib"
    assert job.message == "Exported 3 papers."
    assert any("exporting" in line for line in job.logs)
    assert runner.latest_for(REVIEW.id, "export") is job
    assert runner.latest_for(REVIEW.id, "pipeline") is None


def test_generic_task_failure_and_conflict():
    release = threading.Event()

    def slow(job):
        release.wait(2)

    runner = JobRunner(fake_collection, fake_aggregation)
    first = runner.start_task(REVIEW, "snowball", slow)
    with pytest.raises(JobConflictError):
        runner.start_task(REVIEW, "export", lambda job: None)
    release.set()
    wait_until_done(first)

    def broken(job):
        raise RuntimeError("Zotero refused the key")

    job = runner.start_task(REVIEW, "zotero", broken)
    wait_until_done(job)
    assert job.status == job_states.FAILED
    assert "Zotero refused the key" in job.error
