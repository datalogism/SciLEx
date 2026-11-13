"""New review from a Zotero collection: deduced settings, files written."""

import pandas as pd
import pytest
import yaml

from scilex.gui.services import zotero_library as zl
from scilex.gui.services.workspace import Workspace
from scilex.tagging.grid import GRID_FILENAME, load_grid


def paper(key, tags, date="2023-05-01", **data):
    return {
        "key": key,
        "version": 1,
        "data": {
            "itemType": "journalArticle",
            "title": f"Paper {key}",
            "date": date,
            "creators": [
                {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
                {"creatorType": "author", "name": "SciLEx Team"},
            ],
            "abstractNote": "An abstract.",
            "tags": [{"tag": t} for t in tags],
            **data,
        },
    }


ITEMS = [
    paper("A", ["Collect_KW1:knowledge graph", "Collect_KW2:llm", "SAT_TASK:Ner"]),
    paper("B", ["Collect_KW1:ontology", "Collect_KW2:llm", "SAT_TASK:?"], "2021"),
    {"key": "N", "data": {"itemType": "note", "note": "x"}},
]
SOURCE = zl.ZoteroSource("42", "group", "COLL1", "Reviews / KG")


@pytest.fixture
def workspace(tmp_path):
    return Workspace(registry_path=tmp_path / "registry.yml")


def test_item_to_row_maps_zotero_fields():
    row = zl.item_to_row(
        paper("A", ["Collect_KW1:kg", "HavePDF"], extra="DOI: 10.1/xyz", url="")
    )
    assert row["authors"] == "Ada Lovelace;SciLEx Team"
    assert row["DOI"] == "10.1/xyz"
    assert row["collect_keywords"] == "Collect_KW1:kg"
    assert row["tags"] == "HavePDF"
    assert row["url"] == "NA"
    assert row["archiveID"] == row["zotero_key"] == "A"


def test_year_range_spans_paper_dates():
    assert zl.year_range(ITEMS) == "2021-2023"
    assert zl.year_range([paper("X", [], date="")]) == ""


def test_create_from_zotero_deduces_keywords_years_and_grid(workspace, tmp_path):
    review, summary = zl.create_review_from_zotero(
        workspace, tmp_path / "kg", "kg_review", SOURCE, ITEMS
    )
    config = yaml.safe_load(review.config_path.read_text(encoding="utf-8"))
    assert config["name"] == "kg_review"
    assert config["search"]["keywords"] == [["knowledge graph", "ontology"], ["llm"]]
    assert config["search"]["years"] == "2021-2023"
    assert summary.papers == 2 and summary.warnings == []

    results = pd.read_csv(review.results_path, sep=";")
    assert results["title"].tolist() == ["Paper A", "Paper B"]
    assert review.has_results

    assert load_grid(review.folder / GRID_FILENAME)["tag"].tolist() == ["SAT_TASK"]
    assert zl.load_source(review.folder) == SOURCE
    assert [r.name for r in workspace.list_reviews()] == ["kg_review"]


def test_config_file_wins_and_gaps_are_deduced(workspace, tmp_path):
    config_file = tmp_path / "given.yml"
    config_file.write_text(
        "name: ignored\nsearch:\n  keywords: [[graph rag]]\n  apis: [OpenAlex]\n",
        encoding="utf-8",
    )
    review, summary = zl.create_review_from_zotero(
        workspace, tmp_path / "kg", "kg_review", SOURCE, ITEMS, config_file
    )
    config = yaml.safe_load(review.config_path.read_text(encoding="utf-8"))
    assert config["name"] == "kg_review"
    assert config["search"]["keywords"] == [["graph rag"]]
    assert config["search"]["apis"] == ["OpenAlex"]
    assert config["search"]["years"] == "2021-2023"  # missing from the file
    assert summary.config_from == str(config_file)


def test_legacy_config_file_is_converted(workspace, tmp_path):
    legacy = tmp_path / "scilex.config.yml"
    legacy.write_text(
        "collect_name: old\nkeywords: [[semantic web], [survey]]\n"
        "years: [2020, 2021]\napis: [HAL]\n",
        encoding="utf-8",
    )
    review, _ = zl.create_review_from_zotero(
        workspace, tmp_path / "kg", "kg_review", SOURCE, ITEMS, legacy
    )
    config = yaml.safe_load(review.config_path.read_text(encoding="utf-8"))
    assert config["search"]["keywords"] == [["semantic web"], ["survey"]]
    assert config["search"]["apis"] == ["HAL"]


def test_without_collect_tags_keywords_stay_placeholders_with_warning(
    workspace, tmp_path
):
    items = [paper("A", ["SAT_TASK:Ner"])]
    _, summary = zl.create_review_from_zotero(
        workspace, tmp_path / "kg", "kg_review", SOURCE, items
    )
    assert any("Collect_KW" in w for w in summary.warnings)


def test_empty_collection_and_existing_folder_are_refused(workspace, tmp_path):
    with pytest.raises(ValueError, match="no paper"):
        zl.create_review_from_zotero(workspace, tmp_path / "e", "e", SOURCE, [])
    workspace.create_review(tmp_path / "taken", name="taken")
    with pytest.raises(FileExistsError):
        zl.create_review_from_zotero(
            workspace, tmp_path / "taken", "taken", SOURCE, ITEMS
        )


def test_list_collections_builds_paths():
    class FakeApi:
        def get_collections(self):
            return [
                {
                    "data": {"key": "C", "name": "Child", "parentCollection": "P"},
                    "meta": {"numItems": 3},
                },
                {"data": {"key": "P", "name": "Parent", "parentCollection": False}},
            ]

    found = zl.list_collections(FakeApi())
    assert [(c.key, c.path, c.num_items) for c in found] == [
        ("P", "Parent", 0),
        ("C", "Parent / Child", 3),
    ]


def test_credentials_require_a_key_and_default_to_the_key_owner(monkeypatch):
    with pytest.raises(zl.ZoteroNotConfiguredError):
        zl.zotero_credentials({"Zotero": {"user_id": 5}})

    # Without a library id, the key owner's library is used (asked to Zotero,
    # stubbed here so the test never reaches the network).
    asked = []

    def fake_key_info(api_key, refresh=False):
        asked.append(api_key)
        if api_key == "refused":
            raise zl.ZoteroNotConfiguredError("refused")
        return zl.ZoteroKeyInfo(user_id="77")

    monkeypatch.setattr(zl, "key_info", fake_key_info)
    assert zl.zotero_credentials({"Zotero": {"api_key": "k"}}) == ("k", "77", "user")
    with pytest.raises(zl.ZoteroNotConfiguredError):
        zl.zotero_credentials({"Zotero": {"api_key": "refused"}})
    assert asked == ["k", "refused"]
    assert zl.zotero_credentials(
        {"Zotero": {"api_key": ["k1", "k2"], "user_id": 5, "user_mode": "group"}}
    ) == ("k1", "5", "group")
