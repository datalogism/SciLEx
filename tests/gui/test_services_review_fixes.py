"""Regression tests for the GUI service bugs found on 2026-10-25."""

import math
import time
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from scilex.gui.services import config_editor
from scilex.gui.services.jobs import JobRunner
from scilex.gui.services.screening import paper_key
from scilex.gui.services.workspace import Workspace
from scilex.pipeline import jobs as job_states
from scilex.pipeline.enrichment_pwc import _enrich_rows
from tests.gui.test_jobs import CONFIG, REVIEW, fake_collection, wait_until_done


@pytest.fixture
def review(tmp_path):
    workspace = Workspace(registry_path=tmp_path / "reg.yml")
    return workspace.create_review(tmp_path / "rev", name="demo")


# --- Config save --------------------------------------------------------------


def test_save_keeps_header_comments_and_explicit_defaults(review):
    review.config_path.write_text(
        "# My review on graphs\n# second line\n"
        "name: demo\nsearch:\n  keywords: [[a]]\n  years: [2020]\n  apis: [Arxiv]\n"
        "filters:\n  min_authors: 2\n",
        encoding="utf-8",
    )
    data = config_editor.load_editable(review)
    assert data["filters"]["min_authors"] == 2  # equal to the code default
    config_editor.save(review, data)

    text = review.config_path.read_text(encoding="utf-8")
    assert text.startswith("# My review on graphs\n# second line\n")
    assert yaml.safe_load(text)["filters"] == {"min_authors": 2}


# --- Jobs -----------------------------------------------------------------------


def test_system_exit_in_job_does_not_leave_it_running():
    def exiting_aggregation(config, options, progress_callback):
        raise SystemExit(2)

    runner = JobRunner(fake_collection, exiting_aggregation)
    job = runner.start_pipeline(REVIEW, CONFIG)
    wait_until_done(job)
    assert job.status == job_states.FAILED
    assert runner.active_job() is None


def test_job_error_is_sanitized():
    def leaking_aggregation(config, options, progress_callback):
        raise RuntimeError("GET https://api.example.org/?apikey=SECRET123 failed")

    runner = JobRunner(fake_collection, leaking_aggregation)
    job = runner.start_pipeline(REVIEW, CONFIG)
    wait_until_done(job)
    assert "SECRET123" not in (job.error or "")
    assert "SECRET123" not in job.message


# --- Screening keys ---------------------------------------------------------------


def test_papers_without_doi_and_title_get_distinct_keys():
    first = {"DOI": "NA", "title": math.nan, "archiveID": "hal-1", "date": "2024"}
    second = {"DOI": "NA", "title": math.nan, "archiveID": "hal-2", "date": "2024"}
    assert paper_key(first) != paper_key(second)
    assert "nan" not in paper_key(first)


# --- Papers with Code cancel -------------------------------------------------------------


def test_enrichment_cancel_drops_queued_searches(monkeypatch):
    searched = []

    def fake_process(row, *args, **kwargs):
        searched.append(row["title"])
        time.sleep(0.02)  # a real HF search takes far longer
        return None

    monkeypatch.setattr(
        "scilex.pipeline.enrichment_pwc.process_paper_for_csv", fake_process
    )
    rows = pd.DataFrame({"title": [f"paper {i}" for i in range(200)]})

    class Cancelled(Exception):
        pass

    def cancel_at_first_progress(processed, total, stats):
        raise Cancelled

    options = SimpleNamespace(workers=2, dry_run=False, limit=None)
    with pytest.raises(Cancelled):
        _enrich_rows(
            rows,
            None,
            None,
            None,
            options=options,
            progress_callback=cancel_at_first_progress,
        )
    assert len(searched) < 20


# --- Job panel log ------------------------------------------------------------------


def test_lines_after_returns_only_new_lines():
    from scilex.gui.components.job_panel import _lines_after

    assert _lines_after([], ["a", "b"]) == ["a", "b"]
    assert _lines_after(["a", "b"], ["a", "b", "c"]) == ["c"]
    # The window slid: the oldest lines were trimmed.
    assert _lines_after(["a", "b", "c"], ["b", "c", "d", "e"]) == ["d", "e"]
    assert _lines_after(["a", "b"], ["x", "y"]) is None
