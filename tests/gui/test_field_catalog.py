"""Tests of the Configure field catalog and guidance helpers (ADR 0005)."""

from pydantic import BaseModel

from scilex.config_defaults import COLLECTOR_API_NAMES
from scilex.gui.services import config_editor, field_catalog
from scilex.settings.schema import ScilexSettings


def _leaf_paths(model: type[BaseModel] = ScilexSettings, prefix: str = "") -> list[str]:
    paths = []
    for name, field in model.model_fields.items():
        core, _ = config_editor._unwrap(field.annotation)
        if isinstance(core, type) and issubclass(core, BaseModel):
            paths.extend(_leaf_paths(core, f"{prefix}{name}."))
        else:
            paths.append(f"{prefix}{name}")
    return paths


def test_every_settings_field_has_a_label_and_help():
    missing = [path for path in _leaf_paths() if path not in field_catalog.FIELDS]
    assert not missing, f"add these fields to field_catalog.FIELDS: {missing}"
    for path in _leaf_paths():
        meta = field_catalog.FIELDS[path]
        assert meta.label and meta.help, path


def test_catalog_has_no_stale_entry():
    assert set(field_catalog.FIELDS) <= set(_leaf_paths())


def test_every_api_and_section_is_described():
    assert set(field_catalog.API_INFO) == set(COLLECTOR_API_NAMES)
    for name, _model in config_editor.sections():
        assert name in field_catalog.SECTIONS


def _data(keywords, years, apis):
    data = config_editor.base_dict()
    data["name"] = "x"
    data["search"].update(keywords=keywords, years=years, apis=apis)
    return data


def test_estimate_queries_follows_the_query_compositor():
    assert (
        config_editor.estimate_queries(
            _data([["a", "b"], ["c"]], [2024, 2025], ["Arxiv"])
        )
        == 4
    )
    assert (
        config_editor.estimate_queries(
            _data([["a", "b"], []], [2024], ["Arxiv", "DBLP"])
        )
        == 4
    )
    assert config_editor.estimate_queries(_data([["a"]], "2025-2020", ["Arxiv"])) == 0


def test_dependency_warnings():
    data = _data([["a"]], [2024], ["IEEE", "Arxiv"])
    data["citations"]["fetch"] = False
    data["filters"]["citations"] = True
    data["enrichment"]["unpaywall"] = True
    data["llm_screening"]["enabled"] = True
    paths = [path for path, _ in config_editor.dependency_warnings(data, {})]
    assert paths == [
        "search.apis",
        "filters.citations",
        "enrichment.unpaywall",
        "llm_screening.enabled",
    ]
    keys = {
        "IEEE": {"api_key": "k"},
        "Unpaywall": {"email": "a@b.c"},
        "openrouter": {"api_key": "k"},
    }
    data["citations"]["fetch"] = True
    assert config_editor.dependency_warnings(data, keys) == []


def test_key_status():
    assert config_editor.key_status("IEEE", {}) == "missing"
    assert config_editor.key_status("SemanticScholar", {}) == "advised"
    assert config_editor.key_status("Arxiv", {}) == "ok"
    assert config_editor.key_status("IEEE", {"IEEE": {"api_key": ["a", "b"]}}) == "ok"


def test_readable_problem_names_the_field():
    assert (
        config_editor.readable_problem(
            "filters.abstract_quality", "Input should be less than or equal to 100"
        )
        == "Minimum abstract quality (0-100): must be at most 100"
    )
    assert config_editor.readable_problem(
        "search.years.0", "Input should be a valid integer"
    ).startswith("Years: must be a whole number")
    assert (
        config_editor.readable_problem(
            "search.years", "year range start is after its end"
        )
        == "Years: 'From' is after 'To'"
    )


def test_default_value_and_format():
    assert config_editor.default_value("filters.require") == ["abstract", "year"]
    assert config_editor.default_value("ranking.max_papers", "bibliometrics") is None
    assert config_editor.format_default(True) == "on"
    assert config_editor.format_default(None) == "empty"
    assert config_editor.format_default(["a", "b"]) == "a, b"


def test_template_keywords_are_suggested():
    terms = field_catalog.template_keywords()
    assert "knowledge graph" in terms
    assert len(terms) == len(set(terms))
