"""Run history: "last run" chips (red never, green recent, grey older) on costly actions."""

import json
import time
from datetime import datetime, timedelta

import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.components.run_status import COLORS
from scilex.gui.services import analyses as service
from scilex.gui.services import run_history

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 10, 12, 0)


def _review(ctx, tmp_path, results=True):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True)
    if results:
        review.results_path.write_text("title\nA\n")
    return review


# --- service -------------------------------------------------------------------


def test_freshness_thresholds():
    assert run_history.freshness(None, NOW) == run_history.NEVER
    recent = run_history.RunRecord("k", NOW - timedelta(days=run_history.RECENT_DAYS))
    old = run_history.RunRecord("k", NOW - timedelta(days=run_history.RECENT_DAYS + 1))
    assert run_history.freshness(recent, NOW) == run_history.RECENT
    assert run_history.freshness(old, NOW) == run_history.OLD


def test_describe():
    assert run_history.describe(None) == "Never run"
    assert run_history.ago(NOW - timedelta(seconds=10), NOW) == "just now"
    assert run_history.ago(NOW - timedelta(minutes=5), NOW) == "5 min ago"
    assert run_history.ago(NOW - timedelta(hours=3), NOW) == "3 h ago"
    assert run_history.ago(NOW - timedelta(days=1), NOW) == "yesterday"
    assert run_history.ago(datetime(2026, 1, 2), NOW) == "on 02 Jan 2026"


def test_record_and_load_round_trip(tmp_path):
    run_history.record(tmp_path, "analysis-citations", NOW, "120 papers")
    run_history.record(tmp_path, "export-bibtex", NOW - timedelta(days=60))
    loaded = run_history.load(tmp_path)
    assert loaded["analysis-citations"].finished_at == NOW
    assert loaded["analysis-citations"].message == "120 papers"
    assert set(loaded) == {"analysis-citations", "export-bibtex"}


def test_broken_history_is_ignored(tmp_path):
    run_history.history_path(tmp_path).write_text("{not json")
    assert run_history.load(tmp_path) == {}
    run_history.history_path(tmp_path).write_text(
        json.dumps({"ok": {"finished_at": NOW.isoformat()}, "bad": {"x": 1}})
    )
    assert set(run_history.load(tmp_path)) == {"ok"}


def test_last_run_inferred_from_files(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    assert run_history.last_run(review, "analysis-crossref") is None  # in-place, no file
    assert run_history.last_run(review, "analysis-citations") is None
    (review.collection_dir / "citations_cache.json").write_text("{}")
    inferred = run_history.last_run(review, "analysis-citations")
    assert inferred is not None and inferred.inferred
    pipeline = run_history.last_run(review, run_history.PIPELINE)
    assert pipeline is not None and pipeline.inferred
    # The history wins over the files.
    run_history.record(review.folder, "analysis-citations", NOW, "done")
    assert not run_history.last_run(review, "analysis-citations").inferred


# --- job runner ----------------------------------------------------------------


def _wait(job):
    for _ in range(200):
        if not job.is_active:
            return
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_completed_task_is_recorded(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    _wait(ctx.runner.start_task(review, "analysis-crossref", lambda job: "42 filled"))
    run = run_history.load(review.folder)["analysis-crossref"]
    assert run.message == "42 filled"


def test_failed_and_dry_runs_are_not_recorded(ctx, tmp_path):
    review = _review(ctx, tmp_path)

    def fail(job):
        raise RuntimeError("boom")

    _wait(ctx.runner.start_task(review, "analysis-crossref", fail))
    _wait(ctx.runner.start_task(review, "analysis-enrich", lambda j: "x", history_key=""))
    assert run_history.load(review.folder) == {}


def test_pipeline_modes_have_their_own_keys(ctx, tmp_path):
    from scilex.gui.services.workspace import Workspace

    review = _review(ctx, tmp_path, results=False)
    config = Workspace.load_config(review)
    _wait(ctx.runner.start_pipeline(review, config))
    _wait(ctx.runner.start_aggregation(review, config))
    assert {run_history.PIPELINE, run_history.AGGREGATE} <= set(
        run_history.load(review.folder)
    )


# --- pages ---------------------------------------------------------------------


def _tab_alert(user, name):
    tab = next(iter(user.find(marker=f"analysis-tab-{name}").elements))
    return tab.props.get("alert")


async def test_enrich_tabs_show_colours(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    run_history.record(review.folder, "analysis-citations", datetime.now(), "ok")
    run_history.record(review.folder, "analysis-crossref", datetime(2025, 1, 1))
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/enrich")
        assert _tab_alert(user, "citations") == COLORS[run_history.RECENT]
        assert _tab_alert(user, "crossref") == COLORS[run_history.OLD]
        assert _tab_alert(user, "orkg") == COLORS[run_history.NEVER]
        await user.should_see("Last run just now")


async def test_running_an_analysis_turns_it_green(ctx, tmp_path, monkeypatch):
    review = _review(ctx, tmp_path)
    monkeypatch.setitem(
        service.RUNNERS,
        "orkg",
        lambda config, progress, **kw: service.AnalysisResult("orkg done", []),
    )
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/enrich")
        user.find(marker="analysis-tab-orkg").click()
        await user.should_see("Never run")
        user.find(marker="analysis-run-orkg").click()
        await user.should_see("orkg done", retries=50)
        await user.should_see("Last run just now", retries=50)
        assert _tab_alert(user, "orkg") == COLORS[run_history.RECENT]


async def test_collect_extend_and_export_show_chips(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see(marker=f"run-status-{run_history.PIPELINE}")
        await user.should_see(marker=f"run-status-{run_history.AGGREGATE}")
        await user.open(f"/review/{review.id}/extend")
        await user.should_see(marker=f"run-status-{run_history.EXTEND_ADD}")
        await user.should_see(marker=f"run-status-{run_history.EXTEND_REAGGREGATE}")
        await user.open(f"/review/{review.id}/export")
        await user.should_see(marker="run-status-export-bibtex")
