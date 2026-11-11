"""Tests for scilex.config — centralized configuration service."""

import pytest
import yaml

from scilex.config import SciLExConfig, _merge_advanced_config


@pytest.fixture()
def config_dir(tmp_path):
    """Create a temporary config directory with valid YAML files."""
    main_cfg = {
        "keywords": [["machine learning"], ["biology"]],
        "years": [2023, 2024],
        "apis": ["SemanticScholar", "OpenAlex"],
        "collect_name": "test_collect",
        "output_dir": str(tmp_path / "output"),
    }
    api_cfg = {
        "SemanticScholar": {"api_key": "test-key-123"},
        "CrossRef": {"mailto": "test@example.com"},
    }

    (tmp_path / "scilex.config.yml").write_text(yaml.dump(main_cfg))
    (tmp_path / "api.config.yml").write_text(yaml.dump(api_cfg))
    return tmp_path


class TestFromFiles:
    def test_loads_main_and_api_config(self, config_dir):
        config = SciLExConfig.from_files(config_dir)
        assert config.main["collect_name"] == "test_collect"
        assert config.api["SemanticScholar"]["api_key"] == "test-key-123"
        assert config.main["years"] == [2023, 2024]

    def test_missing_main_config_raises(self, tmp_path):
        (tmp_path / "api.config.yml").write_text(yaml.dump({}))
        with pytest.raises(FileNotFoundError, match="scilex.config.yml"):
            SciLExConfig.from_files(tmp_path)

    def test_missing_api_config_raises(self, tmp_path):
        (tmp_path / "scilex.config.yml").write_text(yaml.dump({"keywords": []}))
        with pytest.raises(FileNotFoundError, match="api.config.yml"):
            SciLExConfig.from_files(tmp_path)

    def test_merges_advanced_config(self, config_dir):
        advanced = {
            "quality_filters": {"require_doi": True, "max_papers": 500},
            "extra_setting": "hello",
        }
        (config_dir / "scilex.advanced.yml").write_text(yaml.dump(advanced))

        config = SciLExConfig.from_files(config_dir)
        assert config.main["quality_filters"]["require_doi"] is True
        assert config.main["quality_filters"]["max_papers"] == 500
        assert config.main["extra_setting"] == "hello"

    def test_advanced_does_not_overwrite_existing_keys(self, config_dir):
        advanced = {"collect_name": "should_not_overwrite"}
        (config_dir / "scilex.advanced.yml").write_text(yaml.dump(advanced))

        config = SciLExConfig.from_files(config_dir)
        assert config.main["collect_name"] == "test_collect"

    def test_empty_advanced_config_is_fine(self, config_dir):
        (config_dir / "scilex.advanced.yml").write_text("")
        config = SciLExConfig.from_files(config_dir)
        assert config.main["collect_name"] == "test_collect"


class TestFromDicts:
    def test_creates_config_from_dicts(self):
        main = {"keywords": [["test"]], "collect_name": "c1"}
        api = {"SemanticScholar": {"api_key": "k"}}
        config = SciLExConfig.from_dicts(main, api)
        assert config.main["collect_name"] == "c1"
        assert config.api["SemanticScholar"]["api_key"] == "k"

    def test_deep_copies_inputs(self):
        main = {"keywords": [["test"]], "nested": {"a": 1}}
        config = SciLExConfig.from_dicts(main)
        config.main["nested"]["a"] = 999
        assert main["nested"]["a"] == 1  # Original unchanged

    def test_default_empty_api_config(self):
        config = SciLExConfig.from_dicts({"keywords": []})
        assert config.api == {}


class TestQualityFilters:
    def test_returns_defaults_when_no_user_filters(self):
        config = SciLExConfig.from_dicts({"keywords": []})
        qf = config.quality_filters
        assert "require_abstract" in qf
        assert "apply_citation_filter" in qf

    def test_user_filters_override_defaults(self):
        config = SciLExConfig.from_dicts(
            {"quality_filters": {"require_doi": True, "max_papers": 42}}
        )
        qf = config.quality_filters
        assert qf["require_doi"] is True
        assert qf["max_papers"] == 42
        # Defaults still present for non-overridden keys
        assert "require_abstract" in qf

    def test_quality_filters_are_fresh_copies(self):
        config = SciLExConfig.from_dicts({"keywords": []})
        qf1 = config.quality_filters
        qf2 = config.quality_filters
        qf1["require_abstract"] = "MUTATED"
        assert qf2["require_abstract"] != "MUTATED"


class TestSaveConfig:
    def test_save_main_config(self, tmp_path):
        config = SciLExConfig.from_dicts({"keywords": [["test"]], "years": [2024]})
        save_path = tmp_path / "saved_main.yml"
        config.save_main_config(save_path)

        loaded = yaml.safe_load(save_path.read_text())
        assert loaded["keywords"] == [["test"]]
        assert loaded["years"] == [2024]

    def test_save_api_config(self, tmp_path):
        config = SciLExConfig.from_dicts({}, {"SS": {"key": "v"}})
        save_path = tmp_path / "saved_api.yml"
        config.save_api_config(save_path)

        loaded = yaml.safe_load(save_path.read_text())
        assert loaded["SS"]["key"] == "v"

    def test_save_creates_parent_dirs(self, tmp_path):
        config = SciLExConfig.from_dicts({"a": 1})
        save_path = tmp_path / "nested" / "dir" / "config.yml"
        config.save_main_config(save_path)
        assert save_path.exists()


class TestMergeAdvancedConfig:
    def test_merges_quality_filters(self):
        main = {"quality_filters": {"require_doi": False}}
        advanced = {"quality_filters": {"require_doi": True, "max_papers": 100}}
        _merge_advanced_config(main, advanced)
        assert main["quality_filters"]["require_doi"] is True
        assert main["quality_filters"]["max_papers"] == 100

    def test_creates_quality_filters_if_absent(self):
        main = {}
        advanced = {"quality_filters": {"require_doi": True}}
        _merge_advanced_config(main, advanced)
        assert main["quality_filters"]["require_doi"] is True

    def test_adds_new_keys(self):
        main = {"existing": "value"}
        advanced = {"new_key": "new_value"}
        _merge_advanced_config(main, advanced)
        assert main["new_key"] == "new_value"
        assert main["existing"] == "value"

    def test_does_not_overwrite_existing_keys(self):
        main = {"key": "original"}
        advanced = {"key": "overwritten"}
        _merge_advanced_config(main, advanced)
        assert main["key"] == "original"
