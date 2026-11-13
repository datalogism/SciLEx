"""Moving annotations to a new grid version (scilex.gui.services.grid_migration)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from scilex.gui.services import grid_migration as gm

MAPPING = """old_dimension,old_value,new_dimension,new_value
BENCHMARKTYPE,*,SURVEY_TYPE,
TASK,RelationClassif,TASK,RC
TASK,*,TASK,
NBMODEL,*,-,
INPUT,NER,INPUT,Text
INPUT,NER,USE_NER,1
INPUT,*,INPUT,
"""


@pytest.fixture
def mapping(tmp_path):
    path = tmp_path / gm.MAPPING_FILENAME
    path.write_text(MAPPING, encoding="utf-8")
    return gm.load_mapping(path)


def test_only_existing_tags_are_translated(mapping):
    result = gm.translate_tags(
        [
            "BENCHMARKTYPE:Quali",
            "TASK:Relation classif",  # spelling differs: still matched
            "TASK:NER",  # wildcard: kept as is
            "NBMODEL:10¹",  # dropped
            "INPUT:NER",  # split into two tags
            "LANG:English",  # no rule: kept, reported
            "ANNOT:0000-0001",  # workflow tag: never touched
            "Collect_KW1:relation",  # SciLEx tag: never touched
            "BK:triple",  # bonus keyword (SciLEx): never touched
            "GITHUB_STARS:366",  # Papers with Code metric: never touched
        ],
        mapping,
    )
    assert result.tags == [
        "SURVEY_TYPE:Quali",
        "TASK:RC",
        "TASK:NER",
        "INPUT:Text",
        "USE_NER:1",
        "LANG:English",
        "ANNOT:0000-0001",
        "Collect_KW1:relation",
        "BK:triple",
        "GITHUB_STARS:366",
    ]
    assert result.changed
    assert ("NBMODEL:10¹", "", "") in result.renames
    assert result.unmapped == [("LANG", "English")]


def test_nothing_is_filled_and_placeholders_only_follow_a_rename(mapping):
    # A paper with no annotation gets none; a placeholder keeps "?".
    assert gm.translate_tags([], mapping).tags == []
    result = gm.translate_tags(["BENCHMARKTYPE:?", "TASK:?"], mapping)
    assert result.tags == ["SURVEY_TYPE:?", "TASK:?"]


def test_untouched_paper_is_not_changed(mapping):
    result = gm.translate_tags(["TASK:NER", "LANG:English"], mapping)
    assert not result.changed


def test_merged_values_collapse_into_one_tag(mapping):
    result = gm.translate_tags(["INPUT:NER", "INPUT:Text"], mapping)
    assert result.tags == ["INPUT:Text", "USE_NER:1"]


def test_mapping_errors(tmp_path):
    with pytest.raises(gm.MappingError, match="No mapping table"):
        gm.load_mapping(tmp_path / "missing.csv")
    bad = tmp_path / "bad.csv"
    bad.write_text("old_dimension;new_dimension\nA;B\n", encoding="utf-8")
    with pytest.raises(gm.MappingError, match="old_value"):
        gm.load_mapping(bad)
    incomplete = tmp_path / "incomplete.csv"
    incomplete.write_text(
        "old_dimension;old_value;new_dimension;new_value\nA;x;;\n", encoding="utf-8"
    )
    with pytest.raises(gm.MappingError, match="Line 2"):
        gm.load_mapping(incomplete)


def _item(key, tags, version=3):
    return {
        "key": key,
        "version": version,
        "data": {
            "title": key,
            "itemType": "journalArticle",
            "tags": [{"tag": t} for t in tags],
        },
    }


class FakeApi:
    def __init__(self):
        self.sent = None

    def update_item_tags(self, updates):
        self.sent = updates
        return {"success": len(updates), "failed": 0}


def test_apply_writes_zotero_results_grid_and_journal(tmp_path, mapping):
    folder = tmp_path / "review"
    folder.mkdir()
    mapping_file = folder / gm.MAPPING_FILENAME
    mapping_file.write_text(MAPPING, encoding="utf-8")
    (folder / "annotation_grid.csv").write_text(
        "tag,detail,datasets,surveys,models\nBENCHMARKTYPE,old,,X,\n", encoding="utf-8"
    )
    new_grid = tmp_path / "grid_v7.csv"
    new_grid.write_text(
        "tag,detail,datasets,surveys,models\nSURVEY_TYPE,new,,X,\n", encoding="utf-8"
    )
    results = folder / "aggregated_results.csv"
    pd.DataFrame(
        {
            "itemType": ["journalArticle"] * 2,
            "title": ["a", "b"],
            "tags": ["BENCHMARKTYPE:Quanti;LANG:English", ""],
        }
    ).to_csv(results, index=False, sep=";")
    items = [
        _item("A", ["BENCHMARKTYPE:Quanti", "LANG:English"]),
        _item("B", []),
        {"key": "N", "data": {"itemType": "note"}},
    ]
    api = FakeApi()
    review = SimpleNamespace(folder=folder, results_path=results)

    counts = gm.apply(
        review, mapping_file, new_grid=new_grid, label="V7", items=items, api=api
    )

    assert api.sent == {"A": (3, ["SURVEY_TYPE:Quanti", "LANG:English"])}
    assert counts["changed"] == 1 and counts["zotero_written"] == 1
    assert counts["papers"] == 2 and counts["annotated"] == 1
    tags = pd.read_csv(results, sep=";")["tags"].fillna("").tolist()
    assert tags == ["SURVEY_TYPE:Quanti;LANG:English", ""]
    assert "SURVEY_TYPE" in (folder / "annotation_grid.csv").read_text("utf-8")
    assert "BENCHMARKTYPE" in (folder / "annotation_grid.csv.before-V7").read_text(
        "utf-8"
    )

    events = [
        json.loads(line)
        for line in (folder / "workflow.jsonl").read_text("utf-8").splitlines()
    ]
    event = [e for e in events if e["activity"] == gm.ACTIVITY][-1]
    assert event["params"]["automatic"] is True
    assert event["used"]["grid"]["file"] == "grid_v7.csv"
    history = (folder / "annotation_history.jsonl").read_text("utf-8").splitlines()
    assert json.loads(history[-1])["origin"] == gm.HISTORY_ORIGIN


def test_plan_table_lists_translations_and_uncovered_values(mapping):
    result = gm.plan(
        [
            _item("A", ["TASK:RelationClassif", "LANG:English"]),
            _item("B", ["TASK:RelationClassif"]),
        ],
        mapping,
    )
    table = gm.plan_table(result).to_dict("records")
    assert table[0] == {
        "old_tag": "TASK:RelationClassif",
        "new_tag": "TASK:RC",
        "papers": 2,
        "note": "",
    }
    assert {
        "old_tag": "LANG:English",
        "new_tag": "(no rule: kept)",
        "papers": 1,
        "note": "",
    } in table


def test_exact_spelling_wins_over_the_loose_match(tmp_path):
    path = tmp_path / "m.csv"
    path.write_text(
        "old_dimension,old_value,new_dimension,new_value,note\n"
        'LIN,"(s,p,o)",LINEARISATION,"(s,p,o)",\n'
        'LIN,"<s,p,o>",LINEARISATION,"<s,p,o>",\n'
        "OBJ,1,OBJ,,re-check\n",
        encoding="utf-8",
    )
    mapping = gm.load_mapping(path)
    assert gm.translate_tags(["LIN:<s,p,o>"], mapping).tags == ["LINEARISATION:<s,p,o>"]
    assert gm.translate_tags(["LIN:(s,p,o)"], mapping).tags == ["LINEARISATION:(s,p,o)"]
    kept = gm.translate_tags(["OBJ:1"], mapping)
    assert not kept.changed and kept.kept == [("OBJ:1", "re-check")]


def test_rules_writing_the_same_tag_change_nothing(tmp_path):
    path = tmp_path / "m.csv"
    path.write_text(
        "old_dimension,old_value,new_dimension,new_value,note\n"
        "TASK,*,TASK,,\n"
        "TASK,*,TASK,,re-check\n"
        "TASK,RelationClassif,TASK,RC,\n",
        encoding="utf-8",
    )
    mapping = gm.load_mapping(path)
    first = gm.translate_tags(["TASK:RelationClassif", "TASK:NER"], mapping)
    assert first.tags == ["TASK:RC", "TASK:NER"]
    # Applying the mapping again to translated tags changes nothing.
    assert not gm.translate_tags(first.tags, mapping).changed
