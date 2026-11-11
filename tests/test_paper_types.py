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
