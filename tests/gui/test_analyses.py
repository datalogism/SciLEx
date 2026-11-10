"""Analyses screen and service (analysis functions mocked, no network)."""

import os
from pathlib import Path

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import analyses as service

pytestmark = pytest.mark.anyio

NAMES = [info.name for info in service.ANALYSES]
# Step page showing each analysis.
STEP = {
    info.name: {"enrich": "enrich", "extend": "extend", "analyse": "analyses"}[
        info.group
    ]
    for info in service.ANALYSES
}


def _prepare_outputs(collect_dir: Path) -> None:
    """Create the inputs every analysis needs."""
    graph_dir = collect_dir / service.GRAPH_DIRNAME
    graph_dir.mkdir(parents=True, exist_ok=True)
    (collect_dir / "aggregated_results.csv").write_text("title\nA\n")
    (collect_dir / "citations_cache.json").write_text("{}")
    (graph_dir / "clusters_cocitation.csv").write_text("cluster_id,title\n0,A\n0,B\n")


# --- service ------------------------------------------------------------------


def test_normalize_options_casts_and_drops():
    raw = {"top_k": 30.0, "min_freq": None, "dry_run": 1, "unknown": "x"}
    assert service.normalize_options("keywords", raw) == {"top_k": 30}
    assert service.normalize_options("enrich", raw) == {"dry_run": True}
    assert service.normalize_options(
        "graph", {"resolution": 1, "fmt": "gexf", "graph_type": ""}
    ) == {"resolution": 1.0, "fmt": "gexf"}


def test_existing_outputs(tmp_path):
    assert service.existing_outputs(tmp_path, "report") == []
    charts = tmp_path / service.CHARTS_DIRNAME
    charts.mkdir()
    (charts / "a.png").write_bytes(b"x")
    (charts / "notes.txt").write_text("x")
    assert service.existing_outputs(tmp_path, "report") == [charts / "a.png"]
    assert service.existing_outputs(tmp_path, "enrich") == []


def _age(path: Path, seconds: float) -> None:
    """Make ``path`` look ``seconds`` older."""
    stat = path.stat()
    os.utime(path, (stat.st_atime - seconds, stat.st_mtime - seconds))


def test_stale_warning(tmp_path):
    _prepare_outputs(tmp_path)
    graph_file = tmp_path / service.GRAPH_DIRNAME / "cocitation_graph.gexf"
    graph_file.write_text("<gexf/>")
    clusters = tmp_path / service.GRAPH_DIRNAME / "clusters_cocitation.csv"
    outputs = [clusters, graph_file]
    # Outputs written after their inputs: up to date.
    assert service.stale_warning(tmp_path, "graph", outputs) is None
    # Aggregation rerun after the graph: out of date, naming the changed file.
    for path in outputs:
        _age(path, 600)
    warning = service.stale_warning(tmp_path, "graph", outputs)
    assert "aggregated_results.csv" in warning
    assert "citations_cache.json" in warning
    # Keywords depend on the clusters, which are older than nothing here.
    keywords = tmp_path / service.GRAPH_DIRNAME / "keyword_suggestions.md"
    keywords.write_text("# k")
    assert service.stale_warning(tmp_path, "keywords", [keywords]) is None
    _age(keywords, 1200)
    assert "clusters_cocitation.csv" in service.stale_warning(
        tmp_path, "keywords", [keywords]
    )
    # Analyses without tracked inputs, or without outputs, never warn.
    assert service.stale_warning(tmp_path, "snowball", outputs) is None
    assert service.stale_warning(tmp_path, "graph", []) is None


def test_missing_prerequisite(tmp_path):
    assert "Collect" in service.missing_prerequisite(tmp_path, "results")
    assert "citation" in service.missing_prerequisite(tmp_path, "citations")
    assert "Graph" in service.missing_prerequisite(tmp_path, "clusters")
    _prepare_outputs(tmp_path)
    for needs in ("results", "citations", "clusters"):
        assert service.missing_prerequisite(tmp_path, needs) is None


def test_run_summaries_writes_report(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    _prepare_outputs(review.collection_dir)
    result = service.run_summaries(config, lambda percent, message: None)
    assert result.files == [review.collection_dir / "graph_analysis/summary_report.md"]
    assert result.files[0].is_file()


def test_run_without_input_is_user_error(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    with pytest.raises(service.AnalysisError):
        service.run_graph(config, lambda percent, message: None)
    with pytest.raises(service.AnalysisError):
        service.run_keywords(config, lambda percent, message: None)


def test_run_enrich_passes_options(ctx, tmp_path, monkeypatch):
    from scilex.pipeline import enrichment_pwc

    seen = {}

    def fake_enrichment(config, options, progress_callback):
        seen["options"] = options
        progress_callback(1, 2, {})
        return enrichment_pwc.EnrichmentResult(
            total=2, processed=2, matched=1, updated=0
        )

    monkeypatch.setattr(enrichment_pwc, "run_enrichment", fake_enrichment)
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    progress_calls = []
    result = service.run_enrich(
        config, lambda p, m: progress_calls.append(p), dry_run=True, limit=5
    )
    assert seen["options"].dry_run and seen["options"].limit == 5
    assert progress_calls == [50]
    assert "1 of 2" in result.message


def _review_with_results(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text("title\nA\n")
    return review


# --- page ---------------------------------------------------------------------


async def test_tabs_are_rendered(ctx, tmp_path):
    review = _review_with_results(ctx, tmp_path)
    async with user_simulation(build_root(ctx)) as user:
        for step in ("enrich", "extend", "analyses"):
            await user.open(f"/review/{review.id}/{step}")
            for name in NAMES:
                if STEP[name] == step:
                    await user.should_see(marker=f"analysis-tab-{name}")
                else:
                    await user.should_not_see(marker=f"analysis-tab-{name}")


async def test_missing_input_is_explained(ctx, tmp_path):
    review = _review_with_results(ctx, tmp_path)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/extend")
        user.find(marker="analysis-tab-snowball").click()
        await user.should_see(marker="analysis-missing-snowball")


async def test_existing_outputs_shown_on_open(ctx, tmp_path):
    review = _review_with_results(ctx, tmp_path)
    _prepare_outputs(review.collection_dir)
    summary = review.collection_dir / "graph_analysis" / "summary_report.md"
    summary.write_text("# Old summary")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/analyses")
        user.find(marker="analysis-tab-summaries").click()
        await user.should_see("Previous results:")


async def test_stale_results_flagged_on_open(ctx, tmp_path):
    review = _review_with_results(ctx, tmp_path)
    _prepare_outputs(review.collection_dir)
    summary = review.collection_dir / "graph_analysis" / "summary_report.md"
    summary.write_text("# Old summary")
    _age(summary, 600)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/analyses")
        user.find(marker="analysis-tab-summaries").click()
        await user.should_see(marker="analysis-stale-summaries")


@pytest.mark.parametrize("name", NAMES)
async def test_run_each_analysis(ctx, tmp_path, monkeypatch, name):
    review = _review_with_results(ctx, tmp_path)
    _prepare_outputs(review.collection_dir)
    produced = review.collection_dir / f"{name}_out.md"
    calls = []

    def fake_runner(config, progress, **kwargs):
        calls.append(kwargs)
        progress(50, "halfway")
        produced.write_text(f"# Output of {name}")
        return service.AnalysisResult(f"{name} finished", [produced])

    monkeypatch.setitem(service.RUNNERS, name, fake_runner)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/{STEP[name]}")
        user.find(marker=f"analysis-tab-{name}").click()
        user.find(marker=f"analysis-run-{name}").click()
        await user.should_see("Completed", retries=50)
        await user.should_see(f"{name} finished", retries=50)
        # The graph is drawn as a network instead of listing its files.
        expected = "papers are linked" if name == "graph" else f"Output of {name}"
        await user.should_see(expected, retries=50)
    assert len(calls) == 1


# --- citations, cancel, busy buttons -------------------------------------------


def _fake_fetchers(monkeypatch, calls, on_batch=None):
    from scilex.citations import reference_fetcher

    def fake(dois, api_key=None, cache_path=None, **kwargs):
        calls.append((Path(cache_path).name, list(dois)))
        if on_batch:
            on_batch()
        Path(cache_path).write_text("{}")
        return {doi: ["10.9/ref"] for doi in dois}

    monkeypatch.setattr(reference_fetcher, "fetch_references_batch", fake)
    monkeypatch.setattr(reference_fetcher, "fetch_citers_batch", fake)


def _review_with_dois(ctx, tmp_path, count=3):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text(
        "itemType,title,DOI\n"
        + "\n".join(f"journalArticle,T{i},10.1/{i}" for i in range(count))
        + "\n"
    )
    return review


def test_run_citations_writes_both_caches(ctx, tmp_path, monkeypatch):
    calls = []
    _fake_fetchers(monkeypatch, calls)
    review = _review_with_dois(ctx, tmp_path)
    config = ctx.workspace.load_config(review)
    result = service.run_citations(config, lambda p, m: None)
    assert [name for name, _ in calls] == ["citations_cache.json", "citers_cache.json"]
    assert service.missing_prerequisite(review.collection_dir, "citations") is None
    assert len(result.files) == 2


def test_run_citations_skip_citers(ctx, tmp_path, monkeypatch):
    calls = []
    _fake_fetchers(monkeypatch, calls)
    review = _review_with_dois(ctx, tmp_path, count=5)
    config = ctx.workspace.load_config(review)
    service.run_citations(config, lambda p, m: None, skip_citers=True)
    assert [(name, len(dois)) for name, dois in calls] == [("citations_cache.json", 5)]


def test_run_citations_passes_cancel_to_fetcher(ctx, tmp_path, monkeypatch):
    """The fetcher gets a per-paper stop check, so cancel needs no batch boundary."""
    import threading

    from scilex.citations import reference_fetcher

    cancel = threading.Event()
    calls = []

    def fake(dois, api_key=None, cache_path=None, should_stop=None, **kwargs):
        calls.append(cache_path)
        assert should_stop() is False
        cancel.set()
        assert should_stop() is True
        Path(cache_path).write_text("{}")
        return {dois[0]: ["10.9/ref"]}

    monkeypatch.setattr(reference_fetcher, "fetch_references_batch", fake)
    monkeypatch.setattr(reference_fetcher, "fetch_citers_batch", fake)
    review = _review_with_dois(ctx, tmp_path, count=5)
    config = ctx.workspace.load_config(review)
    result = service.run_citations(config, lambda p, m: None, cancel_event=cancel)
    assert len(calls) == 1  # citers stage skipped
    assert "Cancelled" in result.message


def test_run_report_cancelled_before_drawing(ctx, tmp_path, monkeypatch):
    import threading

    from scilex import report_charts

    monkeypatch.setattr(report_charts, "load_data", lambda directory: pd.DataFrame())
    review = _review_with_results(ctx, tmp_path)
    config = ctx.workspace.load_config(review)
    cancel = threading.Event()
    cancel.set()
    result = service.run_report(config, lambda p, m: None, cancel_event=cancel)
    assert result.message == "Cancelled."


async def test_citations_job_lifts_snowball_warning(ctx, tmp_path, monkeypatch):
    calls = []
    _fake_fetchers(monkeypatch, calls)
    review = _review_with_dois(ctx, tmp_path)
    async with user_simulation(build_root(ctx)) as user:
        # Snowball (⑤ Extend) needs the citations fetched in ⑥ Enrich.
        await user.open(f"/review/{review.id}/extend")
        user.find(marker="analysis-tab-snowball").click()
        await user.should_see(marker="analysis-missing-snowball")
        await user.open(f"/review/{review.id}/enrich")
        user.find(marker="analysis-tab-citations").click()
        user.find(marker="analysis-run-citations").click()
        await user.should_see("Completed", retries=50)
        await user.open(f"/review/{review.id}/extend")
        user.find(marker="analysis-tab-snowball").click()
        await user.should_not_see(marker="analysis-missing-snowball", retries=50)


async def test_cancel_stops_running_analysis(ctx, tmp_path, monkeypatch):
    import threading

    review = _review_with_results(ctx, tmp_path)
    started = threading.Event()

    def slow_runner(config, progress, cancel_event=None, **kwargs):
        started.set()
        cancel_event.wait(10)
        return service.AnalysisResult("stopped")

    monkeypatch.setitem(service.RUNNERS, "report", slow_runner)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/analyses")
        user.find(marker="analysis-run-report").click()
        await user.should_see(marker="analysis-cancel-report", retries=50)
        user.find(marker="analysis-cancel-report").click()
        await user.should_see("Cancelled", retries=50)


async def test_run_buttons_disabled_only_by_conflicting_jobs(
    ctx, tmp_path, monkeypatch
):
    import threading

    review = _review_with_results(ctx, tmp_path)
    release = threading.Event()

    def slow_runner(config, progress, cancel_event=None, **kwargs):
        release.wait(10)
        return service.AnalysisResult("ok")

    monkeypatch.setitem(service.RUNNERS, "report", slow_runner)
    try:
        async with user_simulation(build_root(ctx)) as user:
            await user.open(f"/review/{review.id}/analyses")
            user.find(marker="analysis-run-report").click()
            await user.should_see("Running", retries=50)
            # Charts only read the papers: an enricher can run alongside.
            await user.open(f"/review/{review.id}/enrich")
            user.find(marker="analysis-tab-enrich").click()
            buttons = user.find(marker="analysis-run-enrich").elements
            assert all(button.enabled for button in buttons)

            # A job rewriting the papers blocks the enrichers of this review.
            blocker = ctx.runner.start_task(
                review, "consolidate", lambda job: release.wait(10) and "done"
            )
            await user.open(f"/review/{review.id}/enrich")
            user.find(marker="analysis-tab-enrich").click()
            await user.should_see("Waiting for: consolidate", retries=20)
            buttons = user.find(marker="analysis-run-enrich").elements
            assert all(not button.enabled for button in buttons)
            release.set()
            await user.open(f"/review/{review.id}/analyses")
            await user.should_see("Completed", retries=50)
            assert blocker is not None
    finally:
        release.set()


def test_run_enrich_cache_path_is_inside_review(ctx, tmp_path, monkeypatch):
    from scilex.pipeline import enrichment_pwc

    seen = {}

    def fake_enrichment(config, options, progress_callback):
        seen["cache_path"] = config.main["pwc_enrichment"]["cache_path"]
        return enrichment_pwc.EnrichmentResult(total=0)

    monkeypatch.setattr(enrichment_pwc, "run_enrichment", fake_enrichment)
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    service.run_enrich(config, lambda p, m: None)
    cache = Path(seen["cache_path"])
    assert cache.is_absolute()
    assert cache.is_relative_to(tmp_path / "rag")


def test_run_enrich_runs_even_when_disabled_in_config(ctx, tmp_path, monkeypatch):
    """The button is the request to enrich: ``enabled: false`` (the default) is overridden."""
    from scilex.pipeline import enrichment_pwc

    seen = {}

    def fake_enrichment(config, options, progress_callback):
        seen["settings"] = enrichment_pwc.enrichment_settings(config.main)
        return enrichment_pwc.EnrichmentResult(total=0)

    monkeypatch.setattr(enrichment_pwc, "run_enrichment", fake_enrichment)
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    assert not enrichment_pwc.enrichment_settings(config.main).get("enabled")
    service.run_enrich(config, lambda p, m: None)
    assert seen["settings"]["enabled"] is True


def _stub_fetchers(monkeypatch, result_of):
    from scilex.citations import reference_fetcher

    def fake(dois, api_key=None, cache_path=None, **kwargs):
        return {doi: result_of(doi) for doi in dois}

    monkeypatch.setattr(reference_fetcher, "fetch_references_batch", fake)
    monkeypatch.setattr(reference_fetcher, "fetch_citers_batch", fake)


def test_run_citations_fails_when_nothing_fetched(ctx, tmp_path, monkeypatch):
    _stub_fetchers(monkeypatch, lambda doi: [])
    config = ctx.workspace.load_config(_review_with_dois(ctx, tmp_path))
    with pytest.raises(
        service.AnalysisError, match="No citation data could be fetched"
    ):
        service.run_citations(config, lambda p, m: None)


def test_run_citations_warns_on_partial_failure(ctx, tmp_path, monkeypatch):
    _stub_fetchers(monkeypatch, lambda doi: ["10.9/x"] if doi == "10.1/0" else [])
    config = ctx.workspace.load_config(_review_with_dois(ctx, tmp_path))
    result = service.run_citations(config, lambda p, m: None)
    assert "1 of 3 papers" in result.message


def test_run_keywords_flattens_keyword_groups(ctx, tmp_path, monkeypatch):
    from scilex.keyword_suggestions import extractor

    review = _review_with_results(ctx, tmp_path)
    _prepare_outputs(review.collection_dir)
    config = ctx.workspace.load_config(review)
    config.main["keywords"] = [["knowledge graph"], ["metabolomics", ["lipidomics"]]]
    seen = {}

    def fake(df, existing, **kwargs):
        seen["existing"] = existing
        return []

    monkeypatch.setattr(extractor, "extract_suggestions", fake)
    service.run_keywords(config, lambda p, m: None)
    assert seen["existing"] == ["knowledge graph", "metabolomics", "lipidomics"]


def test_tabs_follow_prerequisites():
    assert NAMES == [
        "report",
        "citations",
        "snowball",
        "graph",
        "tags",
        "keywords",
        "summaries",
        "enrich",
        "crossref",
        "lpwc",
        "search_keywords",
        "orkg",
    ]


async def test_busy_reason_is_visible_and_chart_caption_is_file_name(
    ctx, tmp_path, monkeypatch
):
    import threading

    review = _review_with_results(ctx, tmp_path)
    charts = review.collection_dir / service.CHARTS_DIRNAME
    charts.mkdir()
    (charts / "years.png").write_bytes(b"x")
    release = threading.Event()

    def slow_runner(config, progress, cancel_event=None, **kwargs):
        release.wait(10)
        return service.AnalysisResult("ok")

    monkeypatch.setitem(service.RUNNERS, "enrich", slow_runner)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/analyses")
        await user.should_see("years.png")
        await user.open(f"/review/{review.id}/enrich")
        user.find(marker="analysis-tab-enrich").click()
        user.find(marker="analysis-run-enrich").click()
        await user.should_see("Running", retries=50)
        await user.open(f"/review/{review.id}/analyses")
        await user.should_see("years.png")
        # Charts only read the papers: the running enricher does not block them.
        await user.should_not_see("Waiting for: Papers with Code")
        assert all(b.enabled for b in user.find(marker="analysis-run-report").elements)
        release.set()
        await user.open(f"/review/{review.id}/enrich")
        user.find(marker="analysis-tab-enrich").click()
        await user.should_see("Completed", retries=50)


def test_snowball_adds_papers_to_the_aggregated_file(ctx, tmp_path, monkeypatch):
    from scilex.io_utils import AGGREGATED_CSV_SEP

    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    review.collection_dir.mkdir(parents=True)
    merged = pd.DataFrame(
        {"title": ["A, B"], "authors": ["Ann Smith;Bob Lee"], "DOI": ["10.1/a"]}
    )
    for target, value in {
        "scilex.io_utils.load_aggregated_data": lambda main, **kwargs: merged.iloc[:0],
        "scilex.graph_analysis.loader.load_citation_caches": lambda d: ({}, {}),
        "scilex.snowball.candidates.extract_candidates": lambda *a, **k: [
            ("10.1/a", 2)
        ],
        "scilex.snowball.fetcher.fetch_metadata_batch": lambda dois, api_key: [{}],
        "scilex.snowball.filter.apply_snowball_filters": lambda papers: merged,
        "scilex.snowball.merge.merge_with_corpus": lambda corpus, new: merged,
    }.items():
        monkeypatch.setattr(target, value)

    result = service.run_snowball(config, lambda percent, message: None)
    assert result.files == [review.collection_dir / "aggregated_results.csv"]
    assert result.message.startswith("1 new papers added")
    written = pd.read_csv(result.files[0], sep=AGGREGATED_CSV_SEP, dtype=str)
    assert written.to_dict("records") == merged.to_dict("records")


def test_snowball_separate_file_leaves_collection_unchanged(ctx, tmp_path, monkeypatch):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    review.collection_dir.mkdir(parents=True)
    aggregated = review.collection_dir / "aggregated_results.csv"
    aggregated.write_text("title;DOI\nA;10.1/a\n", encoding="utf-8")
    merged = pd.DataFrame({"title": ["A", "B"], "DOI": ["10.1/a", "10.1/b"]})
    for target, value in {
        "scilex.io_utils.load_aggregated_data": lambda main, **kwargs: merged.iloc[:1],
        "scilex.graph_analysis.loader.load_citation_caches": lambda d: ({}, {}),
        "scilex.snowball.candidates.extract_candidates": lambda *a, **k: [
            ("10.1/b", 2)
        ],
        "scilex.snowball.fetcher.fetch_metadata_batch": lambda dois, api_key: [{}],
        "scilex.snowball.filter.apply_snowball_filters": lambda papers: merged,
        "scilex.snowball.merge.merge_with_corpus": lambda corpus, new: merged,
    }.items():
        monkeypatch.setattr(target, value)

    result = service.run_snowball(
        config, lambda percent, message: None, add_to_collection=False
    )
    separate = review.collection_dir / "aggregated_results_snowball.csv"
    assert result.files == [separate]
    assert "collection unchanged" in result.message
    assert aggregated.read_text(encoding="utf-8") == "title;DOI\nA;10.1/a\n"
    assert not (review.collection_dir / "aggregated_results_pre_snowball.csv").exists()
    assert service.existing_outputs(review.collection_dir, "snowball") == [separate]


def test_run_enrich_message_counts_processed_papers(ctx, tmp_path, monkeypatch):
    from scilex.pipeline import enrichment_pwc

    def fake_enrichment(config, options, progress_callback):
        return enrichment_pwc.EnrichmentResult(total=500, processed=15, matched=2)

    monkeypatch.setattr(enrichment_pwc, "run_enrichment", fake_enrichment)
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    result = service.run_enrich(config, lambda p, m: None, dry_run=True, limit=15)
    assert result.message == "2 of 15 papers matched, 2 would be updated."


def test_snowball_reports_failed_metadata_fetch(ctx, tmp_path, monkeypatch):
    """All Semantic Scholar requests failed: say so, not 'no paper passed filters'."""
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    config = ctx.workspace.load_config(review)
    review.collection_dir.mkdir(parents=True)
    corpus = pd.DataFrame({"title": ["A"], "DOI": ["10.1/a"]})
    for target, value in {
        "scilex.io_utils.load_aggregated_data": lambda main, **kwargs: corpus,
        "scilex.graph_analysis.loader.load_citation_caches": lambda d: ({}, {}),
        "scilex.snowball.candidates.extract_candidates": lambda *a, **k: [
            ("10.9/x", 2)
        ],
        "scilex.snowball.fetcher.fetch_metadata_batch": lambda dois, api_key: [],
    }.items():
        monkeypatch.setattr(target, value)

    with pytest.raises(service.AnalysisError, match="No metadata could be fetched"):
        service.run_snowball(config, lambda percent, message: None)
