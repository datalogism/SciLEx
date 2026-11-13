"""Collection roles: automatic vs screened results, scope, types, KEEP:screened."""

from dataclasses import dataclass

import pandas as pd
import pytest

from scilex import paper_types, review_tags
from scilex.gui.services import collection_roles as cr
from scilex.gui.services import prisma
from scilex.gui.services.extend import read_results, write_results
from scilex.gui.services.zotero_library import drop_excluded_entries


@dataclass
class Col:
    key: str
    path: str
    num_items: int = 0


COLLECTIONS = [
    Col("A", "surveys"),
    Col("B", "benchmark"),
    Col("C", "models"),
    Col("D", "models / Website"),
    Col("E", "datasets"),
    Col("F", "Extension_Collect_2026-11-11"),
    Col("G", "Extension 5 · BibTeX · 2026-11-12"),
    Col("H", "rag_kg"),
]

ROWS = [
    {  # screened as a survey, but a rule discarded it
        "title": "A survey of relation extraction",
        "DOI": "10.1/a",
        "tags": "PAPER_TYPE:Model or Method;DELETED_BY:filter:C9 no citation",
        "zotero_key": "K1",
        "zotero_collections": "Extension_Collect_2026-11-11;surveys",
    },
    {  # in two screened collections
        "title": "REBench: a benchmark and a dataset",
        "DOI": "10.1/b",
        "tags": "",
        "zotero_key": "K2",
        "zotero_collections": "benchmark;datasets",
    },
    {  # automatic only, discarded by a rule
        "title": "Unrelated paper",
        "DOI": "10.1/c",
        "tags": "DELETED_BY:filter:C3 language",
        "zotero_key": "K3",
        "zotero_collections": "Extension_Collect_2026-11-11",
    },
    {  # sub-collection of models, discarded by a person: stays discarded
        "title": "A website",
        "DOI": "10.1/d",
        "tags": "DELETED_BY:0000-0002-1825-0097",
        "zotero_key": "K4",
        "zotero_collections": "models / Website",
    },
    {  # was screened, then moved out: loses KEEP:screened
        "title": "Moved out",
        "DOI": "10.1/e",
        "tags": "KEEP:screened",
        "zotero_key": "K5",
        "zotero_collections": "Extension 5 · BibTeX · 2026-11-12",
    },
]


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    write_results(
        pd.DataFrame(ROWS).assign(itemType="journalArticle"), review.results_path
    )
    return review


def roles_of(review):
    roles = cr.proposal(COLLECTIONS, {}, review.name)
    cr.save(review.folder, roles)
    return cr.load(review.folder)


def test_guesses_roles_and_types_from_names():
    roles = {r.path: r for r in cr.proposal(COLLECTIONS, {}, "rag_kg")}
    assert roles["surveys"].role == cr.SCREENED
    assert roles["surveys"].paper_type == paper_types.REVIEW
    assert roles["benchmark"].paper_type == paper_types.BENCHMARK
    assert roles["models"].paper_type == paper_types.MODEL
    assert roles["datasets"].paper_type == paper_types.DATASET
    for automatic in (
        "Extension_Collect_2026-11-11",
        "Extension 5 · BibTeX · 2026-11-12",
        "rag_kg",
    ):
        assert roles[automatic].role == cr.AUTOMATIC
        assert roles[automatic].paper_type is None


def test_saved_roles_win_over_guesses(tmp_path):
    cr.save(tmp_path, [cr.CollectionRole("C", "models", cr.AUTOMATIC)])
    roles = {r.path: r for r in cr.proposal(COLLECTIONS, cr.load(tmp_path))}
    assert roles["models"].role == cr.AUTOMATIC
    assert roles["surveys"].role == cr.SCREENED  # not saved: guessed


def test_scope_and_types(review):
    roles = roles_of(review)
    data = pd.DataFrame(ROWS)
    screened = cr.filter_scope(data, roles, cr.SCOPE_SCREENED)
    assert screened["zotero_key"].tolist() == ["K1", "K2", "K4"]  # sub-collection too
    automatic = cr.filter_scope(data, roles, cr.SCOPE_AUTOMATIC)
    assert automatic["zotero_key"].tolist() == ["K3", "K5"]
    assert len(cr.filter_scope(data, roles, cr.SCOPE_ALL)) == 5
    assert cr.types_of(ROWS[1], roles) == [paper_types.BENCHMARK, paper_types.DATASET]
    # No screened collection yet: every paper, whatever the scope.
    assert len(cr.filter_scope(data, {}, cr.SCOPE_SCREENED)) == 5


def test_apply_sets_types_and_keep_screened(review):
    roles = roles_of(review)
    counts = cr.apply(review, roles)
    assert counts["screened"] == 3 and counts["untagged"] == 1
    tags = read_results(review.results_path)["tags"].fillna("").tolist()
    first = review_tags.split_tags(tags[0])
    assert "PAPER_TYPE:Review or State of the art" in first
    assert "PAPER_TYPE:Model or Method" not in first
    assert review_tags.SCREENED_KEEP in first
    assert "DELETED_BY:filter:C9 no citation" in first  # kept as a warning
    assert not review_tags.workflow(tags[0]).deleted
    assert review_tags.workflow(tags[2]).deleted  # automatic, rule discard
    assert review_tags.workflow(tags[3]).deleted  # a person's discard wins
    assert "KEEP:screened" not in tags[4]
    # Applying again changes nothing.
    again = cr.apply(review, roles)
    assert again["typed"] == again["kept_tagged"] == again["untagged"] == 0


def test_prisma_ends_with_screened_collections(review):
    roles = roles_of(review)
    cr.apply(review, roles)
    flow = prisma.compute(review)
    assert flow.included.count == 3
    assert "surveys: 1" in flow.included.lines
    assert any(
        "kept despite an eligibility rule" in line for line in flow.included.lines
    )
    # K3 is discarded by a rule; K5 is kept but in no screened collection.
    assert flow.pending.count == 1


def test_kg_export_keeps_screened_papers():
    text = (
        "@article{a,\n keywords = {DELETED_BY:filter:C9 x, KEEP:screened},\n}\n"
        "@article{b,\n keywords = {DELETED_BY:filter:C9 x},\n}\n"
        "@article{c,\n keywords = {DELETED_BY:0000-0002-1825-0097, KEEP:screened},\n}\n"
    )
    kept, dropped = drop_excluded_entries(text)
    assert dropped == {"b", "c"}
    assert "@article{a" in kept


def _item(key, title, collections, doi=""):
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": "journalArticle",
            "title": title,
            "DOI": doi,
            "date": "2024",
            "collections": collections,
            "tags": [],
        },
    }


def test_merge_takes_duplicates_and_adds_missing_screened_papers(review):
    roles = roles_of(review)
    paths = {c.key: c.path for c in COLLECTIONS}
    items = [
        _item("K1", "A survey of relation extraction", ["F"], "10.1/a"),
        # A second copy of K1's paper, filed by hand in "surveys".
        _item("Z1", "A Survey of Relation Extraction", ["A"]),
        _item("K2", "REBench: a benchmark and a dataset", ["B"], "10.1/b"),
        # K3 is gone from the library; K4, K5 unchanged.
        _item("K4", "A website", ["D"], "10.1/d"),
        _item("K5", "Moved out", ["G"], "10.1/e"),
        # Screened in Zotero, unknown to SciLEx: added.
        _item("N1", "A new dataset paper", ["E"], "10.1/n"),
        # Automatic only, unknown to SciLEx: not added.
        _item("N2", "Another collect result", ["F"], "10.1/m"),
    ]
    merged, counts = cr.merge_collections(pd.DataFrame(ROWS), items, paths, roles)
    by_key = dict(zip(merged["zotero_key"], merged["zotero_collections"], strict=True))
    assert by_key["K1"] == "Extension_Collect_2026-11-11;surveys"
    assert by_key["K2"] == "benchmark"  # left datasets
    assert by_key["K3"] == ""  # gone from Zotero
    assert by_key["N1"] == "datasets"
    assert "N2" not in by_key and "Z1" not in by_key
    assert counts == {"changed": 2, "gone": 1, "added": 1}
