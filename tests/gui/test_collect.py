"""Collect screen: services (API rows, summary, resume) and page behaviour."""

import json
import time
from pathlib import Path

import pytest
import yaml
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services.collect_summary import (
    PREVIOUS_RESULTS_DIRNAME,
    api_rows,
    clear_collection,
    collected_api_dirs,
    collection_failure,
    detect_resume,
    load_summary,
    phase_steps,
    resume_config,
    target_collection_dir,
)
from scilex.gui.services.jobs import JobRunner
from scilex.gui.services.workspace import Workspace
from scilex.gui.state import AppContext
from scilex.pipeline import jobs as job_states


def _wait(job, timeout=60.0):
    deadline = time.time() + timeout
    while job.is_active and time.time() < deadline:
        time.sleep(0.02)
    assert not job.is_active


# --- services ---------------------------------------------------------------


def test_api_rows_states():
    stats = {
        "OpenAlex": {"completed": 4, "total": 4, "articles": 120},
        "Arxiv": {"completed": 1, "total": 4, "articles": 10},
        "DBLP": {"completed": 0, "total": 4, "articles": 0},
    }
    logs = ["10:00:00 [ERROR] DBLP request failed: HTTP 500"]
    rows = {r.api: r for r in api_rows(stats, logs, job_states.RUNNING, True)}
    assert rows["OpenAlex"].state == "done"
    assert rows["Arxiv"].state == "running"
    assert rows["DBLP"].state == "waiting"
    assert rows["DBLP"].errors == 1

    rows = {r.api: r for r in api_rows(stats, logs, job_states.CANCELLED, False)}
    assert rows["Arxiv"].state == "partial"
    assert rows["DBLP"].state == "failed"
    assert "HTTP 500" in rows["DBLP"].reason


def test_phase_steps():
    steps = dict(phase_steps("filtering", False))
    assert steps["Loading configuration"] == "done"
    assert steps["Applying filters"] == "current"
    assert steps["Ranking papers"] == "pending"
    assert {s for _, s in phase_steps(None, True)} == {"done"}


def _write_summary_files(collection_dir: Path):
    collection_dir.mkdir(parents=True, exist_ok=True)
    (collection_dir / "aggregation_stats.csv").write_text(
        "stat,value\npapers_loaded,500\npapers_after_dedup,300\npapers_output,80\n"
    )
    (collection_dir / "filtering_summary.json").write_text(
        json.dumps({"initial_count": 300, "final_count": 75, "stages": []})
    )
    (collection_dir / "prisma_report.md").write_text("# PRISMA flow\n")


def test_load_summary(tmp_path):
    assert load_summary(tmp_path / "missing") is None
    _write_summary_files(tmp_path)
    summary = load_summary(tmp_path)
    assert (summary.collected, summary.after_dedup, summary.kept) == (500, 300, 75)
    assert summary.prisma_report is not None
    assert summary.aggregation_report is None


def _interrupted_collection(review):
    used = {
        "collect_name": review.name,
        "apis": ["OpenAlex"],
        "years": [2023, 2024],
        "keywords": [["rag"]],
    }
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    (review.collection_dir / "config_used.yml").write_text(yaml.safe_dump(used))
    query_dir = review.collection_dir / "OpenAlex" / "0"
    query_dir.mkdir(parents=True)
    (query_dir / "_complete").write_text("")


def test_detect_and_apply_resume(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    assert detect_resume(review.collection_dir) is None
    _interrupted_collection(review)
    info = detect_resume(review.collection_dir)
    assert (info.done, info.total) == (1, 2)

    config = Workspace.load_config(review)
    resumed = resume_config(review.collection_dir, config)
    assert resumed.main["apis"] == ["OpenAlex"]
    assert resumed.main["years"] == [2023, 2024]
    assert resumed.main["output_dir"] == str(review.output_root)


def test_start_pipeline_forwards_since_and_resume(tmp_path):
    seen = {}

    def collection(config, progress_callback, cancel_event):
        seen["main"] = dict(config.main)

    runner = JobRunner(collection, lambda config, options, progress: None)
    workspace = Workspace(registry_path=tmp_path / "reg.yml")
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = Workspace.load_config(review)

    _wait(runner.start_pipeline(review, config, since="2024-03-01"))
    assert seen["main"]["since"] == "2024-03-01"

    with pytest.raises(ValueError):
        runner.start_pipeline(review, config, since="03/01/2024")
    with pytest.raises(FileNotFoundError):
        runner.start_pipeline(review, config, resume=True)

    _interrupted_collection(review)
    _wait(runner.start_pipeline(review, Workspace.load_config(review), resume=True))
    assert seen["main"]["apis"] == ["OpenAlex"]


def test_fresh_run_deletes_previous_raw_results(tmp_path):
    seen = {}

    def collection(config, progress_callback, cancel_event):
        seen["left"] = sorted(p.name for p in review.collection_dir.iterdir())

    runner = JobRunner(collection, lambda config, options, progress: None)
    workspace = Workspace(registry_path=tmp_path / "reg.yml")
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    _interrupted_collection(review)
    (review.collection_dir / "aggregated_results.csv").write_text("old")
    from scilex.gui.services import zotero_library as _zl

    _zl.save_source(review.folder, _zl.ZoteroSource("42", "group", None, ""))
    config = Workspace.load_config(review)
    assert target_collection_dir(config) == review.collection_dir
    assert [p.name for p in collected_api_dirs(review.collection_dir)] == ["OpenAlex"]

    _wait(runner.start_pipeline(review, config, fresh=True))
    assert seen["left"] == ["previous_results"]  # old aggregation moved aside


def test_target_collection_dir_of_since_run(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = Workspace.load_config(review)
    target = target_collection_dir(config, "2024-03-01")
    assert target.parent == review.collection_dir.parent
    assert target.name.startswith("rag_kg_since_")


def test_start_aggregation_skips_collection(tmp_path):
    calls = []

    def collection(config, progress_callback, cancel_event):
        calls.append("collect")

    def aggregation(config, options, progress_callback):
        calls.append(("aggregate", options.skip_citations))

    runner = JobRunner(collection, aggregation)
    workspace = Workspace(registry_path=tmp_path / "reg.yml")
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")

    job = runner.start_aggregation(
        review, Workspace.load_config(review), skip_citations=True
    )
    _wait(job)

    assert calls == [("aggregate", True)]
    assert job.status == job_states.COMPLETED


@pytest.mark.anyio
async def test_page_offers_aggregation_of_existing_collection(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_not_see(marker="aggregate-only")
    _interrupted_collection(review)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see(marker="aggregate-only")


def test_aggregation_phase_recorded(tmp_path):
    def aggregation(config, options, progress_callback):
        progress_callback("filtering", 30, "Applying filters...")

    runner = JobRunner(lambda *a, **k: None, aggregation)
    workspace = Workspace(registry_path=tmp_path / "reg.yml")
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    job = runner.start_pipeline(review, Workspace.load_config(review))
    _wait(job)
    assert job.aggregation_phase == "filtering"


# --- page -------------------------------------------------------------------

pytestmark_page = pytest.mark.anyio


@pytest.mark.anyio
async def test_page_shows_api_table_and_summary(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")

    def collection(config, progress_callback, cancel_event):
        progress_callback(
            {"OpenAlex": {"completed": 2, "total": 2, "articles": 42}}, 2, 2
        )

    def aggregation(config, options, progress_callback):
        progress_callback("filtering", 30, "Applying filters...")
        _write_summary_files(review.collection_dir)

    ctx.runner = JobRunner(collection, aggregation)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see(marker="preflight")
        user.find(marker="run").click()
        await user.should_see("Completed", retries=50)
        await user.should_see(marker="api-table")
        table = user.find(marker="api-table").elements.pop()
        assert table.rows[0]["api"] == "OpenAlex"
        assert table.rows[0]["papers"] == 42
        assert table.rows[0]["state"] == "done"
        await user.should_see("Applying filters")
        await user.should_see(marker="prisma-report", retries=20)
        await user.should_see("After deduplication")


@pytest.mark.anyio
async def test_page_shows_previous_results_and_resume(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    _write_summary_files(review.collection_dir)
    _interrupted_collection(review)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see("Last results")
        await user.should_see(marker="resume")


@pytest.mark.anyio
async def test_page_run_asks_before_deleting_previous_collection(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    _interrupted_collection(review)
    calls = []
    ctx.runner = JobRunner(
        lambda config, progress_callback, cancel_event: calls.append(1),
        lambda config, options, progress: None,
    )
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        user.find(marker="run").click()
        await user.should_see(marker="fresh-confirm")
        assert ctx.runner.active_job() is None
        user.find(marker="fresh-run").click()
        await user.should_see("Completed", retries=50)
    assert calls == [1]
    assert not (review.collection_dir / "OpenAlex").exists()


@pytest.mark.anyio
async def test_page_invalid_config_offers_fix(ctx, tmp_path, monkeypatch):
    from scilex.settings.schema import SettingsError

    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")

    def invalid(review, keys_path=None):
        raise SettingsError("search.apis: unknown API 'Foo'")

    monkeypatch.setattr(Workspace, "load_config", staticmethod(invalid))
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see(marker="preflight-error")
        await user.should_see(marker="fix-config")


@pytest.mark.anyio
async def test_page_failed_job_has_copy_log(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")

    def collection(config, progress_callback, cancel_event):
        raise RuntimeError("boom")

    ctx = AppContext(
        workspace=ctx.workspace,
        runner=JobRunner(collection),
        native=False,
        profile=ctx.profile,
    )
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        user.find(marker="run").click()
        await user.should_see("Failed", retries=50)
        await user.should_see(marker="pipeline-copy-log", retries=20)
        await user.should_see("boom")


@pytest.mark.anyio
async def test_page_does_not_scan_disk_on_every_tick(ctx, tmp_path, monkeypatch):
    from scilex.gui.pages import collect as collect_page

    calls = []
    real = collect_page.detect_resume
    monkeypatch.setattr(
        collect_page, "detect_resume", lambda path: calls.append(path) or real(path)
    )
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see("Collect")
        count_after_render = len(calls)
        await user.should_see("Collect", retries=10)
        time.sleep(1.3)
        await user.should_see("Collect")
    assert count_after_render == 1
    assert len(calls) == 1


@pytest.mark.anyio
async def test_placeholder_keywords_warning(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see(marker="placeholder-warning")
        await user.should_see(marker="run")


@pytest.mark.anyio
async def test_screening_kept_notice_when_decisions_exist(ctx, tmp_path):
    from scilex.gui.services.screening import Decision, save_decisions

    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True)
    key = "doi:10.1/abc"
    save_decisions(review, {key: Decision(paper_key=key, decision="include")})
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        await user.should_see(marker="screening-kept-notice")


def test_cancel_during_aggregation_ends_cancelled(tmp_path):
    from scilex.pipeline.orchestrator import AggregationCancelled

    def aggregation(config, options, progress_callback):
        assert options.cancel_event is not None
        options.cancel_event.wait(5)
        raise AggregationCancelled("stop")

    runner = JobRunner(lambda *a, **k: None, aggregation)
    workspace = Workspace(registry_path=tmp_path / "reg.yml")
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    job = runner.start_aggregation(review, Workspace.load_config(review))

    assert runner.cancel(job.id)
    _wait(job, timeout=5)

    assert job.status == job_states.CANCELLED


def test_screening_progress_is_exposed_as_fraction(tmp_path):
    from scilex.pipeline.orchestrator import SCREENING_PHASE

    def aggregation(config, options, progress_callback):
        progress_callback("filtering", 45, "Applying quality filters...")
        progress_callback(SCREENING_PHASE, 50, "LLM screening… 5/10 papers")

    runner = JobRunner(lambda *a, **k: None, aggregation)
    workspace = Workspace(registry_path=tmp_path / "reg.yml")
    review = workspace.create_review(tmp_path / "rag", name="rag_kg")
    job = runner.start_aggregation(review, Workspace.load_config(review))
    _wait(job)

    assert job.screening_fraction == 0.5
    assert job.aggregation_phase == "filtering"


def test_fresh_run_moves_previous_aggregation_aside(tmp_path):
    (tmp_path / "OpenAlex").mkdir()
    (tmp_path / "config_used.yml").write_text("a: 1\n")
    (tmp_path / "aggregated_results.csv").write_text("title\nOld\n")
    (tmp_path / "aggregation_stats.csv").write_text("stat,value\n")
    (tmp_path / "screening.csv").write_text("id,decision\n")
    clear_collection(tmp_path)
    assert not (tmp_path / "OpenAlex").exists()
    assert not (tmp_path / "aggregated_results.csv").exists()
    assert load_summary(tmp_path) is None  # old numbers no longer shown
    backup = tmp_path / PREVIOUS_RESULTS_DIRNAME
    assert (backup / "aggregated_results.csv").read_text() == "title\nOld\n"
    assert (tmp_path / "screening.csv").is_file()


FAILED_STATS = {
    "OpenAlex": {"completed": 1, "total": 1, "articles": 0, "incomplete": 1}
}


@pytest.mark.parametrize(
    ("log", "cause"),
    [
        ("[ERROR] OpenAlex: 401 Client Error: Unauthorized", "API key refused"),
        ("[ERROR] OpenAlex: ProxyError('Unable to connect')", "API unreachable"),
        ("[ERROR] OpenAlex: 429 Too Many Requests", "rate limited"),
    ],
)
def test_collection_failure_names_the_cause(tmp_path, log, cause):
    message = collection_failure(tmp_path, FAILED_STATS, [f"10:00:00 {log}"])
    assert message.startswith("No paper was collected.")
    assert f"OpenAlex: {cause}" in message


def test_collection_failure_without_errors_suggests_broader_search(tmp_path):
    stats = {"OpenAlex": {"completed": 1, "total": 1, "articles": 0, "incomplete": 0}}
    assert "broader" in collection_failure(tmp_path, stats, [])


def test_collection_with_papers_is_not_a_failure(tmp_path):
    stats = {"OpenAlex": {"completed": 1, "total": 1, "articles": 4, "incomplete": 0}}
    assert collection_failure(tmp_path, stats, []) is None
    # A resumed run that collected nothing new still has papers on disk.
    (tmp_path / "OpenAlex" / "0").mkdir(parents=True)
    (tmp_path / "OpenAlex" / "0" / "page_1").write_text("{}")
    assert collection_failure(tmp_path, FAILED_STATS, []) is None


def test_query_stopped_on_error_is_not_counted_as_finished():
    (row,) = api_rows(FAILED_STATS, [], job_states.COMPLETED, False)
    assert (row.queries_done, row.queries_total, row.state) == (0, 1, "partial")
