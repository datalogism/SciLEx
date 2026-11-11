"""Tests for CLI hygiene: logging at import, exit codes, HF enrichment loop."""

import importlib
import logging
import os

import pandas as pd
import pytest

import scilex.enrich_with_pwc as enrich_module
import scilex.export_to_bibtex as bibtex_module
import scilex.pipeline.enrichment_pwc as enrichment_module
import scilex.push_to_zotero as push_module
from scilex.config import SciLExConfig
from scilex.logging_config import setup_logging
from scilex.pipeline.enrichment_pwc import EnrichmentOptions


@pytest.fixture
def restore_root_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.parametrize("module", [push_module, bibtex_module, enrich_module])
def test_import_does_not_reconfigure_root_logging(module, restore_root_logging):
    sentinel = logging.NullHandler()
    logging.getLogger().addHandler(sentinel)
    importlib.reload(module)
    assert sentinel in logging.getLogger().handlers


def test_invalid_log_level_falls_back_to_info(restore_root_logging, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "NOPE")
    setup_logging()
    assert logging.getLogger().level == logging.INFO


def test_push_main_exits_1_without_zotero_config(monkeypatch):
    monkeypatch.setattr("sys.argv", ["scilex-push-zotero"])
    monkeypatch.setattr(push_module, "setup_logging", lambda: None)
    monkeypatch.setattr(
        push_module, "resolve_legacy_configs", lambda: ({"collect_name": "c"}, {})
    )
    with pytest.raises(SystemExit) as exc_info:
        push_module.main()
    assert exc_info.value.code == 1


def test_invalid_items_csv_keeps_original_column_names(tmp_path):
    data = pd.DataFrame(
        {"itemType": ["NA"], "title": ["T"], "bad col-name": ["x"], "1st": ["y"]}
    )
    config = {"_collect_dir": str(tmp_path), "collect_name": "c"}
    push_module.push_new_items_to_zotero(data, None, "KEY", set(), {}, config)
    saved = pd.read_csv(tmp_path / "invalid_items_no_url.csv")
    assert list(saved.columns) == ["itemType", "title", "bad col-name", "1st"]


def test_invalid_items_path_uses_normalized_collect_name(tmp_path):
    data = pd.DataFrame({"itemType": ["NA"], "title": ["T"]})
    config = {"output_dir": str(tmp_path), "collect_name": "My Collect"}
    push_module.push_new_items_to_zotero(data, None, "KEY", set(), {}, config)
    from scilex.constants import normalize_path_component

    expected = tmp_path / normalize_path_component("My Collect")
    assert (expected / "invalid_items_no_url.csv").exists()


def _run_enrich(monkeypatch, tmp_path, data, options, processor):
    csv_dir = tmp_path / "collect"
    csv_dir.mkdir(exist_ok=True)
    options.collect_dir = str(csv_dir)
    monkeypatch.setattr(enrichment_module, "PWCClient", lambda **_: object())
    monkeypatch.setattr(
        enrichment_module, "load_aggregated_data", lambda *_a, **_k: data.copy()
    )
    monkeypatch.setattr(enrichment_module, "process_paper_for_csv", processor)
    calls = []
    enrichment_module.run_enrichment(
        SciLExConfig({"collect_name": "c"}, {}),
        options,
        lambda done, total, stats: calls.append(done),
    )
    return csv_dir, calls


def test_enrich_progress_called_for_every_row_and_limit_uses_counter(
    monkeypatch, tmp_path
):
    data = pd.DataFrame(
        {"itemType": ["a"] * 4, "title": list("wxyz")}, index=[10, 11, 12, 13]
    )
    processed_titles = []

    def processor(row, *args, **kwargs):
        processed_titles.append(row["title"])
        if row["title"] == "x":
            raise RuntimeError("boom")
        if row["title"] == "w":
            return None
        return {"tags": "T", "pwc_url": "NA", "github_repo": "NA"}

    csv_dir, calls = _run_enrich(
        monkeypatch, tmp_path, data, EnrichmentOptions(limit=3), processor
    )
    # rows are searched concurrently: same rows, call order not guaranteed
    assert sorted(processed_titles) == ["w", "x", "y"]
    # one call per processed row (skipped, errored, matched) plus the final report
    assert calls[:3] == [1, 2, 3]
    assert os.path.exists(csv_dir / "aggregated_results.csv")
