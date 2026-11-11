"""Characterization tests for TagFormatter."""

import pytest

from scilex.PapersWithCode.tag_formatter import TagFormatter


@pytest.fixture
def formatter():
    return TagFormatter()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("text classification", "TextClassification"),
        ("squad-v2", "SquadV2"),
        ("NA", ""),
        ("", ""),
        ("a/b!c", "Abc"),
    ],
)
def test_normalize_tag_value(raw, expected):
    assert TagFormatter.normalize_tag_value(raw) == expected


def test_task_tag(formatter):
    assert formatter.format_task_tag("text classification") == "TASK:TextClassification"
    assert formatter.format_task_tag(None) is None


def test_architecture_ptm_vs_archi(formatter):
    assert formatter.format_architecture_tag("BERT") == "PTM:Bert"
    assert formatter.format_architecture_tag("Transformer") == "ARCHI:Transformer"
    assert formatter.format_architecture_tag(None) is None


def test_dataset_tags(formatter):
    assert formatter.format_dataset_tags(["squad", "NA", "glue"]) == [
        "DATASET:Squad",
        "DATASET:Glue",
    ]


def test_framework_tag(formatter):
    assert formatter.format_framework_tag("PyTorch") == "FRAMEWORK:Pytorch"


def test_github_stars_tag(formatter):
    assert formatter.format_github_stars_tag(366) == "GITHUB_STARS:366"
    assert formatter.format_github_stars_tag(0) == "GITHUB_STARS:0"
    assert formatter.format_github_stars_tag(-1) is None
    assert formatter.format_github_stars_tag(None) is None


def test_citing_dataset_tags(formatter):
    assert formatter.format_citing_dataset_tags(["glue"]) == ["CITED_BY_DATASET:Glue"]


def test_ai_keywords_kept_as_is(formatter):
    assert formatter.format_ai_keywords_tags([" Multi hop QA ", "NA"]) == [
        "Multi hop QA"
    ]


def test_format_all_tags_order(formatter):
    tags = formatter.format_all_tags(
        {
            "pipeline_tag": "question-answering",
            "architecture": "BERT",
            "datasets": ["squad"],
            "framework": "PyTorch",
            "github_stars": 5,
            "citing_datasets": ["glue"],
            "ai_keywords": ["kw"],
        }
    )
    assert tags == [
        "TASK:QuestionAnswering",
        "PTM:Bert",
        "DATASET:Squad",
        "FRAMEWORK:Pytorch",
        "GITHUB_STARS:5",
        "CITED_BY_DATASET:Glue",
        "kw",
    ]


def test_format_all_tags_empty(formatter):
    assert formatter.format_all_tags({}) == []
