"""Web keys file location and the Papers with Code ``workers`` setting."""

from unittest.mock import MagicMock, patch

import pandas as pd

from scilex.config import SciLExConfig
from scilex.pipeline.enrichment_pwc import EnrichmentOptions, run_enrichment
from scilex.settings import resolve
from scilex.settings.schema import ScilexSettings


def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv("SCILEX_KEYS", raising=False)
    user_path = tmp_path / "home" / ".config" / "scilex" / "keys.yml"
    monkeypatch.setattr(resolve, "USER_KEYS_PATH", user_path)
    return user_path


def test_new_keys_file_goes_to_user_config_not_package(monkeypatch, tmp_path):
    user_path = _isolate(monkeypatch, tmp_path)
    legacy = tmp_path / "pkg" / "api.config.yml"  # does not exist
    assert resolve.keys_file_for_editing(legacy) == user_path


def test_existing_legacy_keys_file_is_still_used(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    legacy = tmp_path / "api.config.yml"
    legacy.write_text("SemanticScholar: {api_key: k}\n")
    assert resolve.keys_file_for_editing(legacy) == legacy


def test_user_keys_file_wins_over_legacy(monkeypatch, tmp_path):
    user_path = _isolate(monkeypatch, tmp_path)
    user_path.parent.mkdir(parents=True)
    user_path.write_text("{}\n")
    legacy = tmp_path / "api.config.yml"
    legacy.write_text("{}\n")
    assert resolve.keys_file_for_editing(legacy) == user_path


def test_explicit_keys_env_wins(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("SCILEX_KEYS", str(tmp_path / "k.yml"))
    assert resolve.keys_file_for_editing(tmp_path / "x.yml") == tmp_path / "k.yml"


def test_hf_workers_in_schema():
    settings = ScilexSettings.model_validate(
        {
            "name": "x",
            "search": {"keywords": [["a"]], "years": [2024], "apis": ["HAL"]},
            "enrichment": {"paperswithcode": {"enabled": True, "workers": 8}},
        }
    )
    assert settings.enrichment.paperswithcode.workers == 8


def _run_with(tmp_path, hf_block, options):
    collect = tmp_path / "c"
    collect.mkdir()
    pd.DataFrame(
        {"title": ["A paper"], "itemType": ["journalArticle"], "DOI": ["10.1/a"]}
    ).to_csv(collect / "aggregated_results.csv", sep=";", index=False)
    config = SciLExConfig.from_dicts(
        {"collect_name": "c", "pwc_enrichment": hf_block}, {}
    )
    options.collect_dir = str(collect)
    options.dry_run = True
    seen = {}

    def fake_rows(data, *args, **kwargs):
        seen["workers"] = (
            args[3].workers if len(args) > 3 else kwargs["options"].workers
        )
        return [], {"total": len(data), "matched": 0, "skipped": 0}

    with (
        patch("scilex.pipeline.enrichment_pwc.PWCClient", MagicMock()),
        patch("scilex.pipeline.enrichment_pwc._enrich_rows", side_effect=fake_rows),
    ):
        run_enrichment(config, options)
    return seen["workers"]


def test_config_workers_used_when_cli_absent(tmp_path):
    assert (
        _run_with(tmp_path, {"enabled": True, "workers": 7}, EnrichmentOptions()) == 7
    )


def test_cli_workers_override_config(tmp_path):
    assert (
        _run_with(
            tmp_path, {"enabled": True, "workers": 7}, EnrichmentOptions(workers=2)
        )
        == 2
    )


def test_default_workers_is_four(tmp_path):
    assert _run_with(tmp_path, {"enabled": True}, EnrichmentOptions()) == 4


def test_workers_only_reaches_legacy_when_not_default():
    from scilex.settings.loader import to_legacy

    base = {
        "name": "x",
        "search": {"keywords": [["a"]], "years": [2024], "apis": ["HAL"]},
    }
    default = ScilexSettings.model_validate(
        {**base, "enrichment": {"paperswithcode": True}}
    )
    custom = ScilexSettings.model_validate(
        {**base, "enrichment": {"paperswithcode": {"enabled": True, "workers": 8}}}
    )
    assert "workers" not in to_legacy(default)[0]["pwc_enrichment"]
    assert to_legacy(custom)[0]["pwc_enrichment"]["workers"] == 8
