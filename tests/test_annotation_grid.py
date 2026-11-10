"""Annotation grid: tag processing, deduction from Zotero tags, grid files."""

from unittest.mock import MagicMock

import pandas as pd

from scilex.tagging import grid as g


def paper(key, tags, title="A paper", version=7):
    return {
        "key": key,
        "version": version,
        "data": {
            "itemType": "journalArticle",
            "title": title,
            "tags": [{"tag": t} for t in tags],
        },
    }


def test_missing_dimensions_get_placeholders_and_values_are_normalized():
    item = paper("K1", ["sat_task:question answering", "HavePDF"])
    assert g.process_paper_tags(item, ["SAT_TASK", "SAT_LANG"]) == [
        "SAT_TASK:QuestionAnswering",
        "SAT_LANG:?",
    ]


def test_keep_other_tags_preserves_scilex_and_free_tags():
    item = paper("K1", ["HavePDF", "Collect_KW1:rag", "SAT_TASK:?", "my note"])
    tags = g.process_paper_tags(item, ["SAT_TASK"], keep_other_tags=True)
    assert tags == ["HavePDF", "Collect_KW1:rag", "my note", "SAT_TASK:?"]


def test_filled_dimension_drops_its_placeholder():
    item = paper("K1", ["SAT_TASK:?", "SAT_TASK:Ner"])
    assert g.process_paper_tags(item, ["SAT_TASK"]) == ["SAT_TASK:Ner"]


def test_plan_lists_only_papers_whose_tags_change():
    done = paper("A", ["SAT_TASK:Ner"], version=3)
    todo = paper("B", ["HavePDF"], version=5)
    attachment = {"key": "C", "data": {"itemType": "attachment", "title": "pdf"}}
    plan = g.plan_grid_updates([done, todo, attachment], ["SAT_TASK"])
    assert plan == {"B": (5, ["HavePDF", "SAT_TASK:?"])}


def test_automation_tags_are_recognized():
    for tag in ("HavePDF", "HavePWC", "Collect_KW2:llm", "REL_SCORE:7", "CITAT:2"):
        assert g.is_automation_tag(tag)
    assert not g.is_automation_tag("SAT_TASK:Ner")


def test_deduce_grid_ignores_automation_and_unstructured_tags():
    items = [
        paper("A", ["SAT_TASK:Ner", "Collect_KW1:rag", "free text", "QUALI_SCORE:5"]),
        paper("B", ["sat_task:Qa", "SAT_LANG:?", "two words:x"]),
    ]
    grid = g.deduce_grid(items)
    assert grid["tag"].tolist() == ["SAT_TASK", "SAT_LANG"]
    assert "Ner" in grid.loc[0, "detail"] and "Qa" in grid.loc[0, "detail"]
    assert set(grid.loc[0, list(g.PAPER_TYPES)]) == {"X"}


def test_deduce_keyword_groups_from_collect_tags():
    items = [
        paper("A", ["Collect_KW1:knowledge graph", "Collect_KW2:llm"]),
        paper("B", ["Collect_KW1:knowledge graph", "Collect_KW2:rag"]),
        paper("C", ["Collect_KW1:ontology", "Collect_KW2:llm"]),
    ]
    assert g.deduce_keyword_groups(items) == [
        ["knowledge graph", "ontology"],
        ["llm", "rag"],
    ]
    assert g.deduce_keyword_groups([paper("D", ["SAT_TASK:Ner"])]) == []


def test_default_grid_loads_with_types(tmp_path):
    grid = g.load_grid(g.DEFAULT_GRID_PATH)
    assert "SAT_TASK" in grid["tag"].tolist()
    assert "SAT_LANG" in g.tags_for_type(grid, "datasets")
    assert set(g.tags_for_type(grid, g.ALL_TYPES)) >= set(
        g.tags_for_type(grid, "models")
    )
    by_type = g.load_tags_from_csv(str(g.DEFAULT_GRID_PATH))
    assert set(by_type) == set(g.PAPER_TYPES)


def test_save_and_load_round_trip_keeps_extra_columns(tmp_path):
    grid = pd.DataFrame(
        [{"tag": "dim_a", "detail": "Q?", "datasets": "X", "comment": "keep me"}]
    )
    path = g.save_grid(grid, tmp_path / "grid.csv")
    loaded = g.load_grid(path)
    assert loaded.loc[0, "tag"] == "DIM_A"
    assert loaded.loc[0, "comment"] == "keep me"
    assert g.tags_for_type(loaded, "datasets") == ["DIM_A"]
    assert g.tags_for_type(loaded, "models") == []


def test_merge_grids_adds_only_new_dimensions():
    base = pd.DataFrame([{"tag": "A", "detail": "base"}])
    extra = pd.DataFrame([{"tag": "a", "detail": "other"}, {"tag": "B"}])
    merged = g.merge_grids(base, extra)
    assert merged["tag"].tolist() == ["A", "B"]
    assert merged.loc[0, "detail"] == "base"


def test_update_item_tags_batches_by_fifty():
    from scilex.Zotero.zotero_api import ZoteroAPI

    api = ZoteroAPI("1", "user", "key")
    response = MagicMock()
    response.json.return_value = {"successful": {"0": {}}, "failed": {}}
    api._post = MagicMock(return_value=response)
    updates = {f"K{i}": (i, ["SAT_TASK:?"]) for i in range(120)}
    api.update_item_tags(updates)
    sizes = [len(call.args[1]) for call in api._post.call_args_list]
    assert sizes == [50, 50, 20]
    first = api._post.call_args_list[0].args[1][0]
    assert first == {"key": "K0", "version": 0, "tags": [{"tag": "SAT_TASK:?"}]}
