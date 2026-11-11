"""``--threshold`` of scilex-enrich takes precedence over the configuration."""

import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

import scilex.enrich_with_pwc as cli_module
import scilex.pipeline.enrichment_pwc as core
from scilex.config import SciLExConfig
from scilex.pipeline.enrichment_pwc import EnrichmentOptions


def _matcher_threshold(config_threshold, options):
    hf_block = {"enabled": True}
    if config_threshold is not None:
        hf_block["fuzzy_match_threshold"] = config_threshold
    config = SciLExConfig.from_dicts(
        {"collect_name": "c", "output_dir": "/nonexistent", "pwc_enrichment": hf_block},
        {},
    )
    seen = {}

    class RecordingMatcher:
        def __init__(self, threshold):
            seen["threshold"] = threshold

    with (
        mock.patch.object(core, "PWCClient"),
        mock.patch.object(core, "TitleMatcher", RecordingMatcher),
        mock.patch.object(
            core, "load_aggregated_data", return_value=pd.DataFrame({"title": ["a"]})
        ),
        mock.patch.object(core, "resolve_aggregate_path", return_value=Path("x.csv")),
        mock.patch.object(core, "process_paper_for_csv", return_value=None),
    ):
        core.run_enrichment(config, options)
    return seen["threshold"]


def test_cli_threshold_wins_over_config():
    assert _matcher_threshold(90, EnrichmentOptions(threshold=60, dry_run=True)) == 60


def test_config_threshold_used_without_cli_value():
    assert _matcher_threshold(70, EnrichmentOptions(dry_run=True)) == 70


def test_default_threshold_is_85():
    assert _matcher_threshold(None, EnrichmentOptions(dry_run=True)) == 85


@pytest.mark.parametrize(
    ("argv", "expected"), [([], None), (["--threshold", "60"], 60)]
)
def test_cli_passes_threshold_only_when_given(monkeypatch, argv, expected):
    captured = {}

    def fake_run(config, options):
        captured["threshold"] = options.threshold
        return core.EnrichmentResult(disabled=True)

    monkeypatch.setenv("SCILEX_CONFIG", "")
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    monkeypatch.setattr(cli_module, "run_enrichment", fake_run)
    monkeypatch.setattr(
        cli_module.SciLExConfig, "from_files", classmethod(lambda cls: object())
    )
    cli_module.main()
    assert captured["threshold"] == expected
