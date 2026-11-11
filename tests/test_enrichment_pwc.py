"""Tests for the Papers with Code enrichment core (run_enrichment) and its CLI."""

import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

import scilex.enrich_with_pwc as cli_module
import scilex.pipeline.enrichment_pwc as core
from scilex.config import SciLExConfig
from scilex.pipeline.enrichment_pwc import (
    EnrichmentOptions,
    EnrichmentResult,
    _enrich_rows,
    run_enrichment,
)

MATCH = {"tags": "TASK:X", "pwc_url": "https://pwc/x", "github_repo": "NA"}


@pytest.fixture
def csv_dir(tmp_path):
    directory = tmp_path / "collect"
    directory.mkdir()
    pd.DataFrame(
        {"title": ["Alpha", "Beta", "Gamma", "NA"], "itemType": ["a"] * 4}
    ).to_csv(directory / "aggregated_results.csv", sep=";", index=False)
    return directory


@pytest.fixture
def config():
    return SciLExConfig({"collect_name": "c", "pwc_enrichment": {}}, {})


@pytest.fixture
def fake_pwc(monkeypatch):
    """Mock the client and the per-paper processor (no network)."""
    monkeypatch.setattr(core, "PWCClient", MagicMock())
    seen = []

    def processor(row, *args, **kwargs):
        seen.append(row["title"])
        return MATCH if row["title"] in {"Alpha", "Gamma"} else None

    monkeypatch.setattr(core, "process_paper_for_csv", processor)
    return seen


def _read(csv_dir):
    return pd.read_csv(
        csv_dir / "aggregated_results.csv", sep=";", keep_default_na=False
    )


def test_run_enrichment_counters_columns_and_progress(csv_dir, config, fake_pwc):
    calls = []
    result = run_enrichment(
        config,
        EnrichmentOptions(collect_dir=str(csv_dir)),
        lambda done, total, stats: calls.append((done, total)),
    )
    assert isinstance(result, EnrichmentResult)
    assert (result.total, result.matched, result.updated, result.skipped) == (
        4,
        2,
        2,
        2,
    )
    assert result.processed == 4
    assert result.output_path == str(csv_dir / "aggregated_results.csv")
    written = _read(csv_dir)
    assert {"tags", "pwc_url", "github_repo"} <= set(written.columns)
    assert list(written["tags"]) == ["TASK:X", "NA", "TASK:X", "NA"]
    assert calls[:4] == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert calls[-1] == (4, 4)  # final report


def test_dry_run_does_not_write(csv_dir, config, fake_pwc):
    before = (csv_dir / "aggregated_results.csv").read_text()
    result = run_enrichment(
        config, EnrichmentOptions(collect_dir=str(csv_dir), dry_run=True)
    )
    assert (result.matched, result.updated) == (2, 0)
    assert result.output_path is None
    assert (csv_dir / "aggregated_results.csv").read_text() == before


def test_limit_stops_early(csv_dir, config, fake_pwc):
    calls = []
    result = run_enrichment(
        config,
        EnrichmentOptions(collect_dir=str(csv_dir), limit=2),
        lambda done, total, stats: calls.append((done, total)),
    )
    assert fake_pwc == ["Alpha", "Beta"]
    assert (result.processed, result.matched) == (2, 1)
    # Progress is out of the limited rows, not the whole CSV.
    assert calls == [(1, 2), (2, 2), (2, 2)]


@pytest.mark.parametrize("key", ["pwc_enrichment", "hf_enrichment"])
def test_disabled_in_config(csv_dir, fake_pwc, key):
    # hf_enrichment: legacy key, still read (ADR 0006)
    disabled = SciLExConfig({key: {"enabled": False}}, {})
    result = run_enrichment(disabled, EnrichmentOptions(collect_dir=str(csv_dir)))
    assert result.disabled
    assert fake_pwc == []


def test_enrich_rows_does_not_modify_data_and_keeps_order(fake_pwc):
    data = pd.DataFrame({"title": ["Alpha", "Beta", "Gamma"]}, index=[7, 8, 9])
    snapshot = data.copy()
    updates, stats = _enrich_rows(data, None, None, None, EnrichmentOptions())
    assert [idx for idx, _ in updates] == [7, 9]
    assert stats == {"total": 3, "matched": 2, "skipped": 1}
    pd.testing.assert_frame_equal(data, snapshot)


def test_cli_builds_options(monkeypatch):
    captured = {}

    def fake_run(config, options):
        captured["options"] = options
        return EnrichmentResult(total=1)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scilex-enrich",
            "--dry-run",
            "--limit",
            "5",
            "--threshold",
            "70",
            "--collect-dir",
            "d",
        ],
    )
    monkeypatch.setattr(cli_module, "run_enrichment", fake_run)
    monkeypatch.setattr(
        cli_module.SciLExConfig, "from_files", lambda: SciLExConfig({}, {})
    )
    monkeypatch.setattr(cli_module, "setup_logging", lambda: None)
    cli_module.main()
    assert captured["options"] == EnrichmentOptions(
        dry_run=True, limit=5, threshold=70, collect_dir="d"
    )


def test_enrich_rows_parallel_keeps_order_and_counts_errors(monkeypatch):
    def processor(row, *args, **kwargs):
        if row["title"] == "Boom":
            raise RuntimeError("network down")
        return MATCH

    monkeypatch.setattr(core, "process_paper_for_csv", processor)
    titles = [f"T{i}" for i in range(50)] + ["Boom"]
    data = pd.DataFrame({"title": titles})
    progress = []
    updates, stats = _enrich_rows(
        data,
        None,
        None,
        None,
        EnrichmentOptions(workers=8, limit=51),
        progress_callback=lambda done, total, _stats: progress.append(done),
    )
    assert [idx for idx, _ in updates] == list(range(50))
    assert stats == {"total": 51, "matched": 50, "skipped": 1}
    assert progress == list(range(1, 52))
