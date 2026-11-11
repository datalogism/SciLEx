"""Shared test fixtures for SciLEx tests."""

from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Keep every test away from the developer's own files.

    Without this, tests read the real ``~/.config/scilex/keys.yml``, the
    ``~/SciLEx`` reviews, the desktop app's profile and registry (platformdirs:
    ``%APPDATA%`` on Windows) and the package's own legacy ``api.config.yml``.
    """
    home = tmp_path_factory.mktemp("home")
    for variable in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(variable, str(home))
    for variable in ("SCILEX_KEYS", "SCILEX_CONFIG"):
        monkeypatch.delenv(variable, raising=False)
    from scilex.settings import loader

    monkeypatch.setattr(loader, "LEGACY_KEYS_PATH", home / "api.config.yml")
    return home


@pytest.fixture
def data_query_dual():
    """Dual-keyword query dict used across collector tests."""
    return {
        "keyword": ["knowledge graph", "LLM"],
        "year": 2024,
        "id_collect": 0,
        "total_art": 0,
        "coll_art": 0,
        "last_page": 0,
        "state": 0,
    }


@pytest.fixture
def data_query_single():
    """Single-keyword query dict."""
    return {
        "keyword": ["machine learning"],
        "year": 2024,
        "id_collect": 0,
        "total_art": 0,
        "coll_art": 0,
        "last_page": 0,
        "state": 0,
    }


@pytest.fixture
def sample_paper_record():
    """Complete paper dict with all standard fields."""
    return {
        "title": "Deep Learning for Knowledge Graph Completion",
        "authors": "John Smith;Jane Doe;Bob Johnson",
        "date": "2024-03-15",
        "DOI": "10.1234/example.2024.001",
        "abstract": "This paper presents a novel approach to knowledge graph completion "
        "using deep learning techniques. We propose a new model that combines "
        "graph neural networks with transformer architectures.",
        "itemType": "journalArticle",
        "journalAbbreviation": "J. Artif. Intell.",
        "volume": "42",
        "issue": "3",
        "pages": "123-145",
        "publisher": "Springer",
        "url": "https://doi.org/10.1234/example.2024.001",
        "pdf_url": "https://arxiv.org/pdf/2401.12345.pdf",
        "language": "en",
        "rights": "CC-BY-4.0",
        "archive": "SemanticScholar",
        "archiveID": "abc123",
        "serie": "LNCS",
        "conferenceName": "AAAI 2024",
        "nb_citation": "15",
        "tags": "TASK:KGCompletion;PTM:TransE;FRAMEWORK:PyTorch",
        "pwc_url": "https://paperswithcode.co/paper/2401.12345",
        "github_repo": "https://github.com/author/kg-completion",
    }


@pytest.fixture
def sample_dataframe(sample_paper_record):
    """3-row DataFrame for filter/dedup testing."""
    records = [
        sample_paper_record,
        {
            **sample_paper_record,
            "title": "Transformer Models for NLP Tasks",
            "DOI": "10.5678/nlp.2024.002",
            "authors": "Alice Brown;Charlie Wilson",
            "date": "2023-11-20",
            "abstract": "We survey recent transformer-based models for various "
            "natural language processing tasks.",
            "archive": "OpenAlex",
            "nb_citation": "30",
        },
        {
            **sample_paper_record,
            "title": "Graph Neural Networks: A Review",
            "DOI": "10.9999/gnn.2024.003",
            "authors": "Eve Davis",
            "date": "2024-01-10",
            "abstract": "A comprehensive review of graph neural networks and their "
            "applications in various domains including biology and chemistry.",
            "archive": "IEEE",
            "itemType": "conferencePaper",
            "nb_citation": "5",
        },
    ]
    return pd.DataFrame(records)


@pytest.fixture
def pubmed_fixtures_dir():
    """Path to PubMed XML fixtures directory."""
    return Path(__file__).parent / "fixtures" / "pubmed"


@pytest.fixture
def minimal_paper_df():
    """Single-row DataFrame with all required columns."""
    return pd.DataFrame(
        [
            {
                "DOI": "10.1234/test.001",
                "title": "A Test Paper",
                "authors": "Alice Smith",
                "date": "2024-01-01",
                "abstract": "A short abstract for testing purposes.",
                "archive": "SemanticScholar",
                "itemType": "journalArticle",
                "nb_citation": "5",
                "url": "https://example.com/paper",
                "pdf_url": "NA",
                "language": "en",
                "rights": "CC-BY",
                "journalAbbreviation": "J. Test",
                "volume": "1",
                "issue": "1",
                "pages": "1-10",
                "publisher": "Test Publisher",
                "archiveID": "abc123",
                "serie": "NA",
                "conferenceName": "NA",
                "tags": "NA",
                "pwc_url": "NA",
                "github_repo": "NA",
            }
        ]
    )


@pytest.fixture
def dblp_row():
    """Minimal valid DBLP API response row."""
    return {
        "@id": "https://dblp.org/rec/journals/test/Smith24",
        "info": {
            "title": "Knowledge Graph Completion",
            "year": "2024",
            "type": "Journal Articles",
            "authors": {
                "author": [
                    {"text": "Alice Smith", "@pid": "1"},
                    {"text": "Bob Jones", "@pid": "2"},
                ]
            },
        },
    }


@pytest.fixture
def hal_row():
    """Minimal valid HAL API response row."""
    return {
        "halId_s": "hal-12345678",
        "docType_s": "ART",
        "title_s": ["Knowledge Graph Methods"],
        "abstract_s": ["We present a study on knowledge graph methods."],
        "submittedDateY_i": 2024,
    }


@pytest.fixture
def ieee_row():
    """Minimal valid IEEE API response row."""
    return {
        "article_number": "IEEE123456",
        "title": "Graph Neural Networks for KG",
        "abstract": "We study graph neural networks for knowledge graphs.",
        "authors": [{"full_name": "Alice Smith"}],
        "content_type": "Journals",
        "access_type": "Open Access",
        "publication_date": "2024",
    }
