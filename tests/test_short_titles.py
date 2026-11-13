"""Short titles deduced from the acronym a title names."""

import pandas as pd
import pytest

from scilex import short_titles as st


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("BERT: Pre-training of Deep Bidirectional Transformers", "BERT"),
        ("SQuAD: 100,000+ Questions for Machine Comprehension of Text", "SQuAD"),
        ("RoBERTa: A Robustly Optimized BERT Pretraining Approach", "RoBERTa"),
        ("word2vec: explained", "word2vec"),
        ("GPT-4 – Technical report", "GPT-4"),
        ("KILT - a Benchmark for Knowledge Intensive Language Tasks", "KILT"),
        ("Holistic Evaluation of Language Models (HELM)", "HELM"),
        ("General Language Understanding Evaluation (GLUE) benchmark", "GLUE"),
        ("GPT 3: a test", "GPT 3"),
        # Not acronyms: plain words, phrases, no prefix
        ("Transformers: State-of-the-Art Natural Language Processing", None),
        ("Lost in the Middle: How Language Models Use Long Contexts", None),
        ("Big Bird: Transformers for Longer Sequences", None),
        ("Attention Is All You Need", None),
        ("A study of graphs (KG) in medicine", None),  # not spelled by the words
        ("NA", None),
        (None, None),
    ],
)
def test_candidate(title, expected):
    assert st.candidate(title) == expected


def test_annotate_fills_only_empty_and_skips_shared_prefixes():
    data = pd.DataFrame(
        {
            "title": [
                "BERT: Pre-training of Deep Bidirectional Transformers",
                "LLaMA: Open and Efficient Foundation Language Models",
                "COVID-19: a survey of models",
                "COVID-19: knowledge graphs for drugs",
                "Attention Is All You Need",
                "BERT: Pre-training of Deep Bidirectional Transformers",  # copy
            ],
            "shortTitle": ["NA", "Llama1", None, None, None, ""],
        }
    )
    report = st.annotate(data)
    assert list(data["shortTitle"]) == [
        "BERT",
        "Llama1",  # set before: kept
        None,
        None,
        None,
        "BERT",
    ]
    assert (report.filled, report.already, report.shared) == (2, 1, 2)
    assert "2 short titles" in report.message()


def test_annotate_adds_the_column_and_honours_the_filter():
    data = pd.DataFrame({"title": ["T5: text to text", "SQuAD: questions"]})
    st.annotate(data, row_filter=lambda df: df.iloc[[1]])
    assert data["shortTitle"].isna().tolist() == [True, False]
    assert data.at[1, "shortTitle"] == "SQuAD"
