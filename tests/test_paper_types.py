"""Default paper types."""

import pandas as pd

from scilex import paper_types as pt


def test_title_cues_decide():
    assert pt.classify("A Survey of Retrieval-Augmented Generation") == pt.REVIEW
    assert pt.classify("RAGBench: a benchmark for RAG systems") == pt.BENCHMARK
    assert pt.classify("SciQA: a new dataset for scholarly QA") == pt.DATASET
    assert pt.classify("GraphRAG: local to global summarization") == pt.MODEL
    # The most specific cue wins: a survey of benchmarks is a review.
    assert pt.classify("A survey of benchmarks for LLMs") == pt.REVIEW


def test_abstract_needs_repeated_cues_and_item_type_counts():
    one_mention = "We evaluate our model on a public dataset."
    assert pt.classify("Our model", one_mention) == pt.MODEL
    many = "We release a corpus. The corpus has 3 parts. This dataset is open."
    assert pt.classify("Something new", many) == pt.DATASET
    assert pt.classify("Something", "", "Review article") == pt.REVIEW


def test_annotate_keeps_types_set_by_people():
    data = pd.DataFrame(
        [
            {"title": "A survey of KGs", "tags": "SAT_TASK:Ner"},
            {"title": "A survey of RAG", "tags": "PAPER_TYPE:Dataset"},
            {"title": "Our method", "tags": None},
        ]
    )
    assert pt.annotate(data) == 2
    assert list(data["tags"]) == [
        "SAT_TASK:Ner;PAPER_TYPE:Review or State of the art",
        "PAPER_TYPE:Dataset",
        "PAPER_TYPE:Model or Method",
    ]
    assert pt.effective_type({"title": "A survey", "tags": ""}) == pt.REVIEW


def test_a_paper_can_have_several_types():
    row = {
        "title": "X",
        "tags": "PAPER_TYPE:Model or Method;TASK:RE;PAPER_TYPE:Dataset",
    }
    assert pt.types_of(row) == [pt.MODEL, pt.DATASET]
    assert pt.effective_types(row) == [pt.MODEL, pt.DATASET]
    assert pt.effective_type(row) == pt.MODEL  # the first one
    assert pt.effective_types({"title": "A survey of RE"}) == [pt.REVIEW]
    add, remove = pt.tag_changes(row, [pt.DATASET, pt.BENCHMARK])
    assert add == ["PAPER_TYPE:Benchmark"]
    assert remove == ["PAPER_TYPE:Model or Method"]


def test_origin_of_the_types_is_recorded():
    """SX-17: the default guess, a person and a collection role are told apart."""
    data = pd.DataFrame(
        [
            {"title": "A survey of KGs", "tags": ""},
            {"title": "X", "tags": "PAPER_TYPE:Dataset"},
        ]
    )
    pt.annotate(data)
    assert data.at[0, pt.ORIGIN_COLUMN] == pt.DEFAULT_GUESS
    assert data.at[1, pt.ORIGIN_COLUMN] == ""  # set before: origin unknown
    assert pt.changes_types(["PAPER_TYPE:Dataset"], []) and not pt.changes_types(
        ["X:1"], []
    )
    assert pt.person_origin("https://orcid.org/1") == "person:https://orcid.org/1"
