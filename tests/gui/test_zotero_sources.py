"""Per-review Zotero library / collection: sub-collections, whole library, push target."""

import importlib.util

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import DCTERMS

from scilex.gui.services import exports, zotero_library
from scilex.gui.services.zotero_library import (
    ZoteroCollection,
    ZoteroSource,
    descendant_keys,
    export_source_biblatex,
    fetch_source_papers,
    load_source,
    save_source,
    split_by_collection,
)

COLLECTIONS = [
    ZoteroCollection("ROOT", "Survey", 1),
    ZoteroCollection("A", "Survey / Datasets", 1, parent="ROOT"),
    ZoteroCollection("B", "Survey / Datasets / Biomed", 1, parent="A"),
    ZoteroCollection("OTHER", "Other", 1),
]


def _item(key, collections):
    return {
        "key": key,
        "data": {
            "itemType": "journalArticle",
            "title": f"Paper {key}",
            "collections": collections,
        },
    }


class FakeApi:
    user_id, user_role = "42", "group"

    def __init__(self):
        self.items = {
            "ROOT": [_item("p1", ["ROOT"])],
            "A": [_item("p2", ["A"]), _item("p3", ["A", "B"])],
            "B": [_item("p3", ["A", "B"])],
            "OTHER": [_item("p4", ["OTHER"])],
        }
        self.pushed_to = None

    def get_top_items(self, key=None):
        if key is None:
            seen = {}
            for items in self.items.values():
                for item in items:
                    seen[item["key"]] = item
            return list(seen.values())
        return self.items[key]

    def export_top_items(self, key, export_format="biblatex"):
        keys = [i["key"] for i in self.get_top_items(key)]
        return "\n".join(f"@article{{{k}, title={{Paper {k}}}}}" for k in keys)


def test_descendant_keys():
    assert sorted(descendant_keys(COLLECTIONS, "ROOT")) == ["A", "B", "ROOT"]
    assert descendant_keys(COLLECTIONS, "B") == ["B"]


def test_collection_with_subcollections_gives_each_paper_once_with_its_sub_corpora():
    source = ZoteroSource("42", "group", "ROOT", "Survey", include_subcollections=True)
    items = fetch_source_papers(FakeApi(), source, COLLECTIONS)
    assert sorted(i["key"] for i in items) == ["p1", "p2", "p3"]
    p3 = next(i for i in items if i["key"] == "p3")
    assert p3["_scilex_collections"] == [
        "Survey / Datasets",
        "Survey / Datasets / Biomed",
    ]
    groups = split_by_collection(items)
    assert sorted(i["key"] for i in groups["Survey / Datasets"]) == ["p2", "p3"]


def test_single_collection_without_subcollections():
    source = ZoteroSource(
        "42", "group", "A", "Survey / Datasets", include_subcollections=False
    )
    items = fetch_source_papers(FakeApi(), source, COLLECTIONS)
    assert sorted(i["key"] for i in items) == ["p2", "p3"]


def test_whole_group_library():
    source = ZoteroSource("42", "group", None, "", library_name="Group: Lab")
    assert source.whole_library and "whole library" in source.describe()
    items = fetch_source_papers(FakeApi(), source, COLLECTIONS)
    assert sorted(i["key"] for i in items) == ["p1", "p2", "p3", "p4"]
    text, subcorpora = export_source_biblatex(FakeApi(), source, COLLECTIONS)
    assert "@article{p4" in text
    assert subcorpora["Survey / Datasets / Biomed"] == ["p3"]


def test_source_round_trip_and_legacy_file(tmp_path):
    source = ZoteroSource("42", "group", "A", "Survey / Datasets", True, "Group: Lab")
    save_source(tmp_path, source)
    assert load_source(tmp_path) == source
    (tmp_path / zotero_library.SOURCE_FILENAME).write_text(
        "library_id: '1'\nlibrary_type: user\ncollection_key: C1\ncollection_name: rag\n"
    )
    legacy = load_source(tmp_path)
    assert legacy.collection_key == "C1" and legacy.include_subcollections is False


def test_push_goes_to_the_review_collection(ctx, tmp_path, monkeypatch):
    review = ctx.workspace.create_review(tmp_path / "r", name="r")
    review.collection_dir.mkdir(parents=True)
    review.results_path.write_text(
        "itemType;title;DOI;url\njournalArticle;T;10.1/x;https://e.org\n"
    )
    save_source(review.folder, ZoteroSource("42", "group", "COLL", "Survey"))
    seen = {}

    class Api:
        def get_or_create_collection(self, name):
            raise AssertionError("must not create a collection")

        def get_existing_item_urls(self, key):
            seen["key"] = key
            return set()

    import scilex.push_to_zotero as push

    monkeypatch.setattr(push, "prefetch_templates", lambda data: {})
    monkeypatch.setattr(
        push,
        "push_new_items_to_zotero",
        lambda data, api, key, *a: {"success": 1, "key": key},
    )
    result = exports.push_to_zotero(
        review, ctx.workspace.load_config(review), "all", Api()
    )
    assert seen["key"] == "COLL" and result["key"] == "COLL"


@pytest.mark.skipif(
    not all(importlib.util.find_spec(m) for m in ("morph_kgc", "pyoxigraph")),
    reason="needs the 'kg' extra",
)
def test_knowledge_graph_has_creator_and_sub_corpora(tmp_path):
    from scilex.kg.build import build_knowledge_graph

    bib = tmp_path / "s.bib"
    bib.write_text(
        "@article{p1, title={One}, author={Doe, Jane}, date={2020}}\n"
        "@article{p3, title={Three}, author={Roe, Rick}, date={2021}}\n",
        encoding="utf-8",
    )
    base = "https://w3id.org/scilex/data/s/"
    out = tmp_path / "s.ttl"
    build_knowledge_graph(
        bib,
        out,
        review_name="s",
        base_iri=base,
        run_validation=False,
        creator="https://orcid.org/0000-0002-1825-0097",
        subcorpora={"Survey / Datasets": ["p3"]},
    )
    graph = Graph().parse(out)
    dataset = URIRef(base)
    assert (
        dataset,
        DCTERMS.creator,
        URIRef("https://orcid.org/0000-0002-1825-0097"),
    ) in graph
    part = URIRef(f"{base}subcorpus/survey-datasets")
    # profile iteration 4+ maps the sub-corpora itself (VoID)
    void = Namespace("http://rdfs.org/ns/void#")
    assert (dataset, void.subset, part) in graph
    assert (URIRef(f"{base}br/p3"), void.inDataset, part) in graph
    assert (URIRef(f"{base}br/p1"), void.inDataset, part) not in graph
