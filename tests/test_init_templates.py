"""Tests for scilex-init: new-format templates, profiles, questionnaire, skeleton."""

import pytest
import yaml

from scilex import init_templates
from scilex.crawlers.aggregate import FORMAT_CONVERTERS
from scilex.settings.schema import ScilexSettings, SettingsError

DOMAINS = [
    "bioinformatics",
    "clinical-medicine",
    "computer-science",
    "machine-learning",
    "social-sciences",
]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(init_templates.PROFILES_DIR_ENV, str(tmp_path / "profiles"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # "~" on Windows
    monkeypatch.delenv("SCILEX_KEYS", raising=False)
    monkeypatch.chdir(tmp_path)


def test_five_templates_listed():
    assert init_templates.list_templates() == DOMAINS


@pytest.mark.parametrize("name", DOMAINS)
def test_template_is_valid_new_format(name):
    config = yaml.safe_load(init_templates.resolve_template(name).read_text())
    assert "collect_name" not in config
    settings = ScilexSettings.model_validate(config)
    assert set(settings.search.apis) <= set(FORMAT_CONVERTERS)


def test_init_from_template_writes_scilex_yml_in_cwd(tmp_path, capsys):
    assert init_templates.main(["--template", "bioinformatics"]) == 0
    written = yaml.safe_load((tmp_path / "scilex.yml").read_text())
    assert "PubMed" in written["search"]["apis"]
    assert "keys.yml" in capsys.readouterr().out  # tells where to create the keys
    assert init_templates.main(["--template", "bioinformatics"]) == 1  # no overwrite
    assert init_templates.main(["--template", "bioinformatics", "--force"]) == 0


def test_init_never_copies_keys(tmp_path):
    init_templates.main(["--template", "machine-learning"])
    assert "api_key" not in (tmp_path / "scilex.yml").read_text()


def test_legacy_profile_is_converted_when_read(tmp_path):
    legacy = tmp_path / "legacy.yml"
    legacy.write_text(
        "collect_name: custom\nkeywords: [[a]]\nyears: [2024]\napis: [OpenAlex]\n"
    )
    assert init_templates.main(["--save-profile", "lab", "--config", str(legacy)]) == 0
    saved = yaml.safe_load((init_templates.profiles_dir() / "lab.yml").read_text())
    assert saved["name"] == "custom"
    target = tmp_path / "out.yml"
    assert init_templates.main(["--template", "lab", "--config", str(target)]) == 0
    assert yaml.safe_load(target.read_text())["search"]["apis"] == ["OpenAlex"]


def test_save_profile_new_format_roundtrip(tmp_path):
    init_templates.main(["--template", "bioinformatics"])
    assert init_templates.main(["--save-profile", "mine"]) == 0
    assert "mine" in init_templates.list_profiles()
    assert init_templates.main(["--save-profile", "mine"]) == 1


def test_unknown_template_and_bad_name(tmp_path):
    assert init_templates.main(["--template", "nope"]) == 1
    assert init_templates.main(["--template", "../etc"]) == 1
    assert not (tmp_path / "scilex.yml").exists()


def test_skeleton_when_not_a_terminal_is_valid(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert init_templates.main([]) == 0
    text = (tmp_path / "scilex.yml").read_text()
    assert text.startswith("#")
    ScilexSettings.model_validate(yaml.safe_load(text))


def test_interactive_questions_build_a_valid_config():
    answers = iter(["demo", "rag, llm", "kg", "2023-2024", "OpenAlex", "bibliometrics"])
    data = init_templates.interactive_config(lambda _prompt: next(answers))
    assert data["name"] == "demo"
    assert data["preset"] == "bibliometrics"
    assert data["search"]["keywords"] == [["rag", "llm"], ["kg"]]
    ScilexSettings.model_validate(data)


def test_interactive_empty_keywords_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["demo", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert init_templates.main([]) == 1
    assert not (tmp_path / "scilex.yml").exists()


def test_check_rejects_invalid_data():
    with pytest.raises(SettingsError):
        init_templates._check({"name": "x"})
