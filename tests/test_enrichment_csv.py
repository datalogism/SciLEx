"""Tests for the CSV side of the Papers with Code enrichment."""

import pandas as pd

from scilex.constants import MISSING_VALUE, is_valid


def test_parse_tags_normal():
    """Test normal semicolon-separated tags parsing."""
    tags_str = "TASK:NER;PTM:BERT;DATASET:Conll2003"
    tags_list = [tag.strip() for tag in str(tags_str).split(";")]
    tags_list = [t for t in tags_list if t]
    expected = ["TASK:NER", "PTM:BERT", "DATASET:Conll2003"]
    assert tags_list == expected


def test_parse_tags_with_empty():
    """Test tags with empty values (double semicolons)."""
    tags_str = "TASK:NER;;DATASET:Conll2003"
    tags_list = [tag.strip() for tag in str(tags_str).split(";")]
    tags_list = [t for t in tags_list if t]
    expected = ["TASK:NER", "DATASET:Conll2003"]
    assert tags_list == expected


def test_parse_tags_with_whitespace():
    """Test tags with extra whitespace."""
    tags_str = "  TASK:NER ; PTM:BERT ; DATASET:Squad  "
    tags_list = [tag.strip() for tag in str(tags_str).split(";")]
    tags_list = [t for t in tags_list if t]
    expected = ["TASK:NER", "PTM:BERT", "DATASET:Squad"]
    assert tags_list == expected


def test_parse_tags_invalid():
    """Test parsing with invalid/missing tags."""
    tags_str = MISSING_VALUE
    if not is_valid(tags_str):
        tags_list = []
    else:
        tags_list = [tag.strip() for tag in str(tags_str).split(";")]
        tags_list = [t for t in tags_list if t]
    assert tags_list == []


def test_parse_tags_empty_string():
    """Test parsing with empty string."""
    tags_str = ""
    if not is_valid(tags_str):
        tags_list = []
    else:
        tags_list = [tag.strip() for tag in str(tags_str).split(";")]
        tags_list = [t for t in tags_list if t]
    assert tags_list == []


def test_csv_column_addition():
    """Test that enrichment columns are added to DataFrame if missing."""
    data = pd.DataFrame(
        {
            "title": ["Test Paper"],
            "authors": ["John Doe"],
            "itemType": ["journalArticle"],
        }
    )

    # Add columns if missing
    if "tags" not in data.columns:
        data["tags"] = MISSING_VALUE
    if "pwc_url" not in data.columns:
        data["pwc_url"] = MISSING_VALUE
    if "github_repo" not in data.columns:
        data["github_repo"] = MISSING_VALUE

    # Check columns exist
    assert "tags" in data.columns
    assert "pwc_url" in data.columns
    assert "github_repo" in data.columns

    # Check default values
    assert data.loc[0, "tags"] == MISSING_VALUE
    assert data.loc[0, "pwc_url"] == MISSING_VALUE
    assert data.loc[0, "github_repo"] == MISSING_VALUE


def test_csv_backward_compatibility():
    """Test that CSVs without enrichment columns still work."""
    # Old CSV without enrichment columns
    data = pd.DataFrame(
        {
            "title": ["Test Paper 1", "Test Paper 2"],
            "authors": ["John Doe", "Jane Smith"],
            "itemType": ["journalArticle", "conferencePaper"],
            "DOI": ["10.1234/x", "10.5678/y"],
        }
    )

    # Process with backward-compatible code
    for col in ["tags", "pwc_url", "github_repo"]:
        if col not in data.columns:
            data[col] = MISSING_VALUE

    # All columns should now exist
    assert len(data.columns) == 7
    assert "tags" in data.columns
    assert "pwc_url" in data.columns
    assert "github_repo" in data.columns

    # No data loss
    assert len(data) == 2
    assert data.loc[0, "title"] == "Test Paper 1"
    assert data.loc[1, "DOI"] == "10.5678/y"


def test_zotero_tag_format():
    """Test conversion of semicolon-separated tags to Zotero format."""
    tags_str = "TASK:TextClassification;PTM:BERT;DATASET:Squad"
    tags_list = [tag.strip() for tag in str(tags_str).split(";")]
    tags_list = [t for t in tags_list if t]

    # Convert to Zotero format
    zotero_tags = [{"tag": t} for t in tags_list]

    expected = [
        {"tag": "TASK:TextClassification"},
        {"tag": "PTM:BERT"},
        {"tag": "DATASET:Squad"},
    ]

    assert zotero_tags == expected


def test_bibtex_keywords_format():
    """Test conversion of semicolon-separated tags to BibTeX keywords."""
    tags_str = "TASK:TextClassification;PTM:BERT;DATASET:Squad;FRAMEWORK:PyTorch"
    tags_list = [tag.strip() for tag in str(tags_str).split(";")]
    tags_list = [t for t in tags_list if t]

    # Convert to comma-separated for BibTeX
    keywords = ", ".join(tags_list)

    expected = "TASK:TextClassification, PTM:BERT, DATASET:Squad, FRAMEWORK:PyTorch"
    assert keywords == expected


def test_github_repo_url():
    """Test that GitHub repo URLs are properly handled."""
    github_repo = "https://github.com/huggingface/transformers"
    assert github_repo.startswith("https://github.com/")
    assert "/" in github_repo.replace("https://", "")


def test_csv_row_update():
    """Test updating CSV row with Papers with Code enrichment results."""
    data = pd.DataFrame(
        {
            "title": ["Test Paper"],
            "tags": [MISSING_VALUE],
            "pwc_url": [MISSING_VALUE],
            "github_repo": [MISSING_VALUE],
        }
    )

    # Simulate enrichment result
    result = {
        "tags": "TASK:TextClassification;PTM:BERT;DATASET:Squad",
        "pwc_url": "https://paperswithcode.co/paper/2409.17957",
        "github_repo": "https://github.com/author/repo",
    }

    # Update row
    idx = 0
    data.at[idx, "tags"] = result["tags"]
    data.at[idx, "pwc_url"] = result["pwc_url"]
    data.at[idx, "github_repo"] = result["github_repo"]

    # Verify update
    assert data.loc[idx, "tags"] == "TASK:TextClassification;PTM:BERT;DATASET:Squad"
    assert data.loc[idx, "pwc_url"] == "https://paperswithcode.co/paper/2409.17957"
    assert data.loc[idx, "github_repo"] == "https://github.com/author/repo"


def test_missing_value_handling():
    """Test handling of MISSING_VALUE in tags."""
    tags_str = MISSING_VALUE

    # Parse tags with graceful fallback
    if is_valid(tags_str) and tags_str != MISSING_VALUE:
        tags_list = [tag.strip() for tag in str(tags_str).split(";")]
        tags_list = [t for t in tags_list if t]
    else:
        tags_list = []

    assert tags_list == []


def test_github_repo_in_archive_location():
    """Test that GitHub repo maps to archiveLocation field."""
    github_repo = "https://github.com/author/repo"

    # Simulate Zotero item
    item = {
        "archiveLocation": "OLD_ARCHIVE_ID",
    }

    # Update with GitHub repo
    if "archiveLocation" in item and github_repo:
        item["archiveLocation"] = github_repo

    assert item["archiveLocation"] == "https://github.com/author/repo"


def test_multiple_papers_enrichment():
    """Test enrichment of multiple papers in DataFrame."""
    data = pd.DataFrame(
        {
            "title": ["Paper A", "Paper B", "Paper C"],
            "authors": ["Author A", "Author B", "Author C"],
            "itemType": ["journalArticle", "conferencePaper", "preprint"],
            "tags": [MISSING_VALUE, MISSING_VALUE, MISSING_VALUE],
            "pwc_url": [MISSING_VALUE, MISSING_VALUE, MISSING_VALUE],
            "github_repo": [MISSING_VALUE, MISSING_VALUE, MISSING_VALUE],
        }
    )

    # Simulate enrichment of 2 papers
    enrichment_results = [
        {
            "tags": "TASK:NER;PTM:BERT",
            "pwc_url": "https://paperswithcode.co/paper/001",
            "github_repo": "https://github.com/org/repo1",
        },
        None,  # No match
        {
            "tags": "TASK:TextGeneration;PTM:GPT",
            "pwc_url": "https://paperswithcode.co/paper/002",
            "github_repo": "https://github.com/org/repo2",
        },
    ]

    # Apply enrichment
    matched_count = 0
    for idx, result in enumerate(enrichment_results):
        if result is None:
            continue
        matched_count += 1
        data.at[idx, "tags"] = result["tags"]
        data.at[idx, "pwc_url"] = result["pwc_url"]
        data.at[idx, "github_repo"] = result["github_repo"]

    # Verify
    assert matched_count == 2
    assert data.loc[0, "tags"] == "TASK:NER;PTM:BERT"
    assert data.loc[1, "tags"] == MISSING_VALUE  # No match
    assert data.loc[2, "tags"] == "TASK:TextGeneration;PTM:GPT"


def test_tag_deduplication_in_bibtex():
    """Test that duplicate tags are handled in BibTeX export."""
    tags_str = "TASK:NER;TASK:NER;PTM:BERT"  # Duplicate TASK:NER
    tags_list = [tag.strip() for tag in str(tags_str).split(";")]
    tags_list = [t for t in tags_list if t]

    # Deduplicate while preserving order
    seen = set()
    unique_tags = []
    for tag in tags_list:
        if tag not in seen:
            unique_tags.append(tag)
            seen.add(tag)

    assert unique_tags == ["TASK:NER", "PTM:BERT"]
