"""Snowballing seeds (collections, paper types, eligibility) and stored settings."""

import pandas as pd

from scilex.gui.services import snowball_scope as scope
from scilex.snowball.candidates import extract_candidates

DATA = pd.DataFrame(
    {
        "title": ["A survey of RE", "DocRED: a dataset", "REBEL model"],
        "abstract": ["We review relation extraction.", "A new dataset.", "A model."],
        "DOI": ["10.1/a", "10.1/b", "10.1/c"],
        "zotero_collections": ["Corpus/Surveys", "Corpus/Datasets", "Other"],
        "tags": ["PAPER_TYPE:Review", "PAPER_TYPE:Dataset", "PAPER_TYPE:Model"],
    }
)


def test_seeds_by_collection_and_type():
    assert list(scope.seeds(DATA, ["Corpus"])["DOI"]) == ["10.1/a", "10.1/b"]
    assert list(scope.seeds(DATA, ["corpus / datasets"])["DOI"]) == ["10.1/b"]
    assert list(scope.seeds(DATA, paper_types=["Model"])["DOI"]) == ["10.1/c"]
    assert len(scope.seeds(DATA)) == 3
    assert scope.collection_options(DATA) == [
        "Corpus",
        "Corpus / Datasets",
        "Corpus / Surveys",
        "Other",
    ]


def test_candidates_start_from_the_seeds_only():
    references = {"10.1/a": ["10.9/x", "10.1/b"], "10.1/c": ["10.9/y"]}
    found = extract_candidates(
        references,
        {},
        {"10.1/a", "10.1/b", "10.1/c"},
        min_frequency=1,
        seed_dois={"10.1/a"},
    )
    assert found == [("10.9/x", 1)]  # 10.1/b is in the corpus already


def test_settings_are_stored(tmp_path):
    assert scope.load(tmp_path) == {}
    scope.save(
        tmp_path,
        {"direction": "backward", "collections": ["Corpus"], "dry_run": True},
    )
    assert scope.load(tmp_path) == {"direction": "backward", "collections": ["Corpus"]}
