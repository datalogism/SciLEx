"""A review created from a SciLEx knowledge graph (scilex.gui.services.kg_import)."""

import ast
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from scilex.gui.services import kg_import
from scilex.gui.services.workspace import Workspace
from scilex.io_utils import AGGREGATED_CSV_SEP
from scilex.kg.build import clean_tables
from scilex.tagging.grid import GRID_FILENAME

HAS_KG_DEPS = all(importlib.util.find_spec(m) for m in ("morph_kgc", "pyoxigraph"))
BASE = "https://w3id.org/scilex/data/my-review/"
SECRET = "S3CRETvalue123"

BIB = r"""
@inproceedings{doe_first_2021,
	title = {A {BERT} Study of Relation Extraction},
	doi = {10.1000/first},
	url = {https://api.example.org/paper?apiKey=SECRET&id=1},
	pages = {10--20},
	booktitle = {Proceedings of {ACL}},
	author = {Doe, Jane and Smith, John},
	date = {2021-05-01},
	abstract = {We study relations.},
	note = {\{'citing': ['10.1000/second', ''], 'cited': ['10.9999/outside']\}
Archive ID: arXiv:2101.00001},
	keywords = {{SAT\_TASK}:{NER}, {Collect\_KW1}:{relation extraction}},
}

@article{roe_second_2022,
	title = {Second Paper},
	doi = {10.1000/second},
	journaltitle = {Journal of Tests},
	author = {Roe, Richard},
	date = {2022},
	note = {\{'citing': [], 'cited': ['10.1000/first']\}},
	keywords = {{SAT\_TASK}:{RelationClassif}, {SAT\_DATASET}:Tacred},
}
""".replace("SECRET", SECRET)


@pytest.fixture(scope="module")
def kg_file(tmp_path_factory) -> Path:
    if not HAS_KG_DEPS:
        pytest.skip("needs the 'kg' extra")
    from scilex.kg.build import build_knowledge_graph, describe_subcorpora  # noqa: F401

    folder = tmp_path_factory.mktemp("kg")
    bib = folder / "my-review.bib"
    bib.write_text(BIB, encoding="utf-8")
    output = folder / "my-review.ttl"
    build_knowledge_graph(
        bib,
        output,
        review_name="My review",
        base_iri=BASE,
        dimensions=["SAT_TASK", "SAT_DATASET"],
        run_validation=False,
        subcorpora={"Core": ["doe_first_2021"], "Core / Extra": ["roe_second_2022"]},
        creator="https://orcid.org/0000-0002-1825-0097",
    )
    return output


def test_export_masks_api_keys(kg_file):
    text = kg_file.read_text(encoding="utf-8")
    assert SECRET not in text
    assert "REDACTED" in text  # the URL is kept, its key masked


def test_clean_tables_masks_keys_in_every_field():
    data = {
        "entries": [{"ID": "a", "url": f"https://x.org/?api_key={SECRET}", "note": ""}],
        "lists": [
            {"entry": "a", "field": "file", "value": f"https://x.org/?token={SECRET}"}
        ],
    }
    cleaned, _, _ = clean_tables(data)
    assert SECRET not in repr(cleaned)


def test_describe_reports_papers_and_subcorpora(kg_file):
    info = kg_import.describe(kg_file)
    assert info.title == "My review"
    assert info.papers == 2
    assert info.subcorpora == ["Core", "Core / Extra"]
    assert info.creator == "https://orcid.org/0000-0002-1825-0097"


def test_graph_to_items_rebuilds_the_papers(kg_file):
    graph = kg_import.read_graph(kg_file)
    items = {item["key"]: item for item in kg_import.graph_to_items(graph)}
    assert set(items) == {"doe_first_2021", "roe_second_2022"}

    first = items["doe_first_2021"]["data"]
    assert first["itemType"] == "conferencePaper"
    assert first["title"] == "A BERT Study of Relation Extraction"
    assert first["DOI"] == "10.1000/first"
    assert first["abstractNote"] == "We study relations."
    assert [(c["firstName"], c["lastName"]) for c in first["creators"]] == [
        ("Jane", "Doe"),
        ("John", "Smith"),
    ]
    assert first["proceedingsTitle"] == "Proceedings of ACL"
    assert first["pages"] == "10--20"
    assert SECRET not in first["url"]
    tags = {t["tag"] for t in first["tags"]}
    assert "SAT_TASK:NER" in tags
    note = ast.literal_eval(first["extra"])
    assert note == {"citing": ["10.1000/second"], "cited": ["10.9999/outside"]}
    assert items["doe_first_2021"]["_scilex_collections"] == ["Core"]

    second = items["roe_second_2022"]["data"]
    assert second["itemType"] == "journalArticle"
    assert second["publicationTitle"] == "Journal of Tests"
    assert {t["tag"] for t in second["tags"]} >= {
        "SAT_TASK:RelationClassif",
        "SAT_DATASET:Tacred",
    }


def test_create_review_from_kg(kg_file, tmp_path):
    workspace = Workspace(registry_path=tmp_path / "reviews.yml")
    review, summary = kg_import.create_review_from_kg(
        workspace, tmp_path / "from-kg", "from_kg", kg_file
    )
    assert summary.papers == 2
    assert summary.years == "2021-2022"
    assert summary.keyword_groups == [["relation extraction"]]
    assert summary.grid_dimensions >= 2
    results = pd.read_csv(review.results_path, sep=AGGREGATED_CSV_SEP)
    assert set(results["archive"]) == {"KG"}
    assert set(results["DOI"]) == {"10.1000/first", "10.1000/second"}
    assert (review.folder / GRID_FILENAME).is_file()
    assert (review.folder / kg_import.KG_SOURCE_FILENAME).is_file()
    copy = review.collection_dir / "kg" / f"imported-{kg_file.name}"
    assert copy.is_file()
    for path in review.folder.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8", errors="ignore"), path


def test_import_masks_keys_left_in_a_graph(kg_file, tmp_path):
    leaky = tmp_path / "leaky.ttl"
    leaky.write_text(
        kg_file.read_text(encoding="utf-8").replace("REDACTED", SECRET),
        encoding="utf-8",
    )
    workspace = Workspace(registry_path=tmp_path / "reviews.yml")
    review, _ = kg_import.create_review_from_kg(
        workspace, tmp_path / "leaky", "leaky", leaky
    )
    for path in review.folder.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8", errors="ignore"), path


def test_a_file_that_is_not_a_scilex_graph_is_refused(tmp_path):
    other = tmp_path / "other.ttl"
    other.write_text("<urn:a> <urn:b> <urn:c> .\n", encoding="utf-8")
    with pytest.raises(kg_import.KgImportError, match="no review paper"):
        kg_import.read_graph(other)
    broken = tmp_path / "broken.ttl"
    broken.write_text("this is not turtle", encoding="utf-8")
    with pytest.raises(kg_import.KgImportError, match="not a readable RDF file"):
        kg_import.read_graph(broken)
