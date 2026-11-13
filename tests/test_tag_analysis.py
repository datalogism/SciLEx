"""Analysis of the DIMENSION:value annotation tags (scilex.tag_analysis)."""

import pandas as pd

from scilex import tag_analysis as tags


def _frame(rows):
    return pd.DataFrame(
        [
            {"title": f"P{i}", "date": date, "tags": ";".join(t)}
            for i, (date, t) in enumerate(rows)
        ]
    )


CORPUS = _frame(
    [
        (
            "2020",
            ["Ontology:CIDOC-CRM", "Tool:Metashape", "LifecycleStep:3", "HavePDF"],
        ),
        ("2021", ["ONTOLOGY:CIDOC CRM", "Tool:MetaShape", "LIFECYCLESTEP:4"]),
        (
            "2021",
            ["Ontology:None", "Tool:Blender", "LifecycleStep:3", "Collect_KW1:rdf"],
        ),
        ("2022", ["Ontology:?", "Tool:Blendr"]),
        ("2022", ["REL_SCORE:3"]),
    ]
)


def test_spellings_are_merged_and_dimensions_unified():
    analysis = tags.analyse_tags(CORPUS)
    ontology = analysis.dimensions["ONTOLOGY"]
    assert ontology.values == {"CIDOC-CRM": 2} or ontology.values == {"CIDOC CRM": 2}
    assert ontology.with_value == 2
    assert ontology.with_none == 1
    assert ontology.pending == 1
    assert ontology.absent == 1
    tool = analysis.dimensions["TOOL"]
    assert sum(tool.values.values()) == 4
    assert set(
        tool.variants[next(v for v in tool.values if v.lower() == "metashape")]
    ) == {
        "Metashape",
        "MetaShape",
    }
    # Automation tags are no dimension; the paper with REL_SCORE only is not annotated.
    assert (
        "REL_SCORE" not in analysis.dimensions and "HAVEPDF" not in analysis.dimensions
    )
    assert analysis.annotated == 4


def test_close_spellings_are_suggested_unless_rejected():
    analysis = tags.analyse_tags(CORPUS)
    pairs = {(s.dimension, s.value, s.merge_into) for s in analysis.suggestions}
    assert any(d == "TOOL" and {v, m} == {"Blender", "Blendr"} for d, v, m in pairs)
    rejected = {("TOOL", "blendr", "blender")}
    again = tags.analyse_tags(CORPUS, rejected=rejected)
    assert not any(s.dimension == "TOOL" for s in again.suggestions)


def test_synonyms_merge_values(tmp_path):
    path = tmp_path / "tag_synonyms.csv"
    tags.add_merge_rows(
        path, [{"dimension": "Tool", "value": "Blendr", "merge_into": "Blender"}]
    )
    synonyms = tags.load_synonyms(path)
    analysis = tags.analyse_tags(CORPUS, synonyms)
    assert analysis.dimensions["TOOL"].values["Blender"] == 2
    assert analysis.synonyms_used == 1
    assert tags.remove_merge_rows(path, [{"dimension": "TOOL", "value": "blendr"}]) == 1
    assert tags.load_synonyms(path) == {}


def test_grid_dimensions_are_listed_even_unused():
    analysis = tags.analyse_tags(CORPUS, grid_dimensions=["Project"])
    assert analysis.dimensions["PROJECT"].in_grid
    assert analysis.dimensions["PROJECT"].absent == 5


def test_cooccurrence_counts_papers_per_pair():
    analysis = tags.analyse_tags(CORPUS)
    table, common = tags.cooccurrence(analysis, "TOOL", "LIFECYCLESTEP")
    assert common == 3
    assert int(table.loc["Blender", "3"]) == 1
    assert int(table.values.sum()) == 3


def test_write_outputs(tmp_path):
    analysis = tags.analyse_tags(CORPUS)
    files = tags.write_outputs(analysis, tmp_path, "test")
    names = {path.name for path in files}
    assert tags.REPORT_FILENAME in names and tags.COVERAGE_PNG in names
    assert "dimension_tool.png" in names
    assert any(name.startswith("cross_") for name in names)
    report = (tmp_path / tags.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "| TOOL |" in report
    for csv in (tags.VALUES_CSV, tags.SUGGESTIONS_CSV, tags.COOCCURRENCE_CSV):
        assert (tmp_path / csv).is_file()


def _item(key, tag_list, version=7):
    return {
        "key": key,
        "version": version,
        "data": {
            "title": key,
            "itemType": "journalArticle",
            "tags": [{"tag": t} for t in tag_list],
        },
    }


def test_plan_tag_cleaning_rewrites_spellings_only():
    items = [
        _item("A", ["Tool:Metashape", "Tool:MetaShape", "HavePDF"]),
        _item("B", ["Tool:MetaShape", "Tool:MetaShape-x"]),
        _item("C", ["Tool:MetaShape"]),
        {"key": "N", "data": {"itemType": "note"}},
    ]
    frame = pd.DataFrame(
        [
            {"title": i["key"], "tags": ";".join(t["tag"] for t in i["data"]["tags"])}
            for i in items[:3]
        ]
    )
    analysis = tags.analyse_tags(frame)
    plan = tags.plan_tag_cleaning(items, analysis)
    assert plan.papers == 3
    assert set(plan.updates) == {"A"}
    version, new_tags = plan.updates["A"]
    assert version == 7
    assert new_tags == ["Tool:MetaShape", "HavePDF"]
    assert plan.renames[("Tool:Metashape", "Tool:MetaShape")] == 1
