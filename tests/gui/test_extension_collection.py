"""Each extension gets its own collection in the review's Zotero group."""

import pandas as pd
import pytest

from scilex.gui.services import extension_collection as ec
from scilex.gui.services import zotero_library as zl
from scilex.gui.services.extend import read_results, write_results


class FakeApi:
    def __init__(self, created=True):
        self.created = created
        self.calls = []

    def create_collection(self, name, parent=None):
        self.calls.append((name, parent))
        return (
            {"key": "EXT1", "data": {"key": "EXT1", "name": name}}
            if self.created
            else None
        )


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    write_results(
        pd.DataFrame(
            [
                {
                    "title": "Old paper",
                    "itemType": "journalArticle",
                    "DOI": "10.1/old",
                    "zotero_collections": "Core",
                },
                {
                    "title": "New paper",
                    "itemType": "journalArticle",
                    "DOI": "10.1/new",
                    "zotero_collections": "",
                },
            ]
        ),
        review.results_path,
    )
    return review


def test_without_group_the_extension_is_kept_without_collection(review):
    summary = ec.publish(review, {"doi:10.1/old"}, "BibTeX", api=FakeApi())
    assert summary.skipped and "no Zotero group" in summary.message()


def test_new_papers_get_their_collection(review, monkeypatch):
    zl.save_source(review.folder, zl.ZoteroSource("42", "group", "PARENT", "RAG"))
    before = ec.paper_keys(read_results(review.results_path).iloc[:1])
    pushed = {}

    def push(data, api, key, existing, templates, config):
        pushed["titles"], pushed["key"] = list(data["title"]), key
        return {"success": len(data), "failed": 0}

    monkeypatch.setattr("scilex.push_to_zotero.push_new_items_to_zotero", push)
    monkeypatch.setattr("scilex.push_to_zotero.prefetch_templates", lambda data: {})
    api = FakeApi()
    summary = ec.publish(review, before, "BibTeX", api=api)

    assert summary.pushed == 1 and not summary.skipped
    assert api.calls[0][0].startswith("Extension 1 · BibTeX · ")
    assert api.calls[0][1] == "PARENT"  # under the review's collection
    assert pushed == {"titles": ["New paper"], "key": "EXT1"}
    rows = read_results(review.results_path).set_index("title")
    assert rows.loc["New paper", "zotero_collections"] == summary.path
    assert summary.path.startswith("RAG / Extension 1")
    assert rows.loc["Old paper", "zotero_collections"] == "Core"
    # The next extension is number 2.
    assert ec.collection_name(review, "Snowball").startswith("Extension 2 · Snowball")


def test_refused_collection_is_reported(review):
    zl.save_source(review.folder, zl.ZoteroSource("42", "group", None, ""))
    summary = ec.publish(review, set(), "Snowball", api=FakeApi(created=False))
    assert "refused" in summary.message()


def test_target_defaults_to_a_new_collection_and_round_trips(review):
    assert ec.load_target(review).is_new
    ec.save_target(review, ec.Target(key="K1", path="RAG / Included"))
    assert ec.load_target(review) == ec.Target(key="K1", path="RAG / Included")
    ec.save_target(review, ec.Target())
    assert ec.load_target(review).is_new


def _fake_push(monkeypatch):
    pushed = {}

    def push(data, api, key, existing, templates, config):
        pushed["titles"], pushed["key"] = list(data["title"]), key
        return {"success": len(data), "failed": 0}

    monkeypatch.setattr("scilex.push_to_zotero.push_new_items_to_zotero", push)
    monkeypatch.setattr("scilex.push_to_zotero.prefetch_templates", lambda data: {})
    return pushed


def test_existing_collection_is_used_without_creating_one(review, monkeypatch):
    zl.save_source(review.folder, zl.ZoteroSource("42", "group", "PARENT", "RAG"))
    pushed = _fake_push(monkeypatch)
    ec.save_target(review, ec.Target(key="INC", path="RAG / Included"))
    api = FakeApi()
    summary = ec.publish(review, {"doi:10.1/old"}, "Snowball", api=api)

    assert api.calls == []  # nothing created
    assert pushed == {"titles": ["New paper"], "key": "INC"}
    assert summary.existing and summary.path == "RAG / Included"
    assert "Existing Zotero collection 'RAG / Included'" in summary.message()
    rows = read_results(review.results_path).set_index("title")
    assert rows.loc["New paper", "zotero_collections"] == "RAG / Included"


def test_new_collection_can_be_named(review, monkeypatch):
    zl.save_source(review.folder, zl.ZoteroSource("42", "group", None, ""))
    _fake_push(monkeypatch)
    api = FakeApi()
    summary = ec.publish(
        review, {"doi:10.1/old"}, "BibTeX", api=api, target=ec.Target(name="Seeds")
    )
    assert api.calls == [("Seeds", None)]
    assert summary.path == "Seeds" and not summary.existing


def test_candidates_stay_inside_the_review_collection(review):
    zl.save_source(review.folder, zl.ZoteroSource("42", "group", "RAG", "RAG"))

    class Api:
        def get_collections(self):
            def c(key, name, parent=False):
                return {"data": {"key": key, "name": name, "parentCollection": parent}}

            return [
                c("RAG", "RAG"),
                c("INC", "Included", "RAG"),
                c("DEEP", "Deep", "INC"),
                c("OTHER", "Other review"),
            ]

    paths = [c.path for c in ec.candidate_collections(review, api=Api())]
    assert paths == ["RAG", "RAG / Included", "RAG / Included / Deep"]
