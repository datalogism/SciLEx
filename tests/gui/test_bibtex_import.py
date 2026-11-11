"""Adding the papers of a BibTeX file to a review."""

import pandas as pd
import pytest

from scilex.gui.services import bibtex_import, paper_log, screening
from scilex.gui.services.extend import read_results
from scilex.gui.services.workspace import Review

BIB = r"""
@article{huguet2021rebel,
  title = {{REBEL}: Relation Extraction By End-to-end Language generation},
  author = {Huguet Cabot, Pere-Llu{\'\i}s and Navigli, Roberto},
  journal = {Findings of EMNLP},
  year = {2021},
  doi = {https://doi.org/10.18653/v1/2021.findings-emnlp.204},
  pages = {2370--2381},
  keywords = {TASK:RelationExtraction, LANG:English},
  abstract = {Extracting relation triplets from raw text.}
}
@inproceedings{yao2019docred,
  title = {DocRED: A Large-Scale Document-Level Relation Extraction Dataset},
  author = {Yao, Yuan and Ye, Deming},
  booktitle = {ACL},
  year = {2019}
}
@misc{chia2022hyperred,
  title = {A Dataset for Hyper-Relational Extraction},
  author = {Chia, Yew Ken},
  eprint = {2211.10018},
  archivePrefix = {arXiv},
  year = {2022}
}
@misc{notitle, author = {Nobody}, year = {2020}}
"""


@pytest.fixture
def review(tmp_path):
    review = Review(folder=tmp_path, name="re", output_root=tmp_path / "output")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "title": [
                "Existing paper",
                "DocRED: a large-scale document-level relation extraction dataset",
            ],
            "DOI": ["10.1/old", "NA"],
            "date": ["2020", "2019"],
            "archive": ["OpenAlex", "OpenAlex"],
            "itemType": ["journalArticle", "conferencePaper"],
        }
    ).to_csv(review.results_path, sep=";")
    return review


def test_entry_mapping():
    rows = dict(bibtex_import.parse_bibtex(BIB)[0])
    rebel = rows["huguet2021rebel"]
    assert rebel["title"].startswith("REBEL: Relation")
    assert rebel["authors"] == "Pere-Lluís Huguet Cabot;Roberto Navigli"
    assert rebel["itemType"] == "journalArticle"
    assert rebel["pages"] == "2370-2381"
    assert rebel["tags"] == "TASK:RelationExtraction;LANG:English"
    assert "10.18653/v1/2021.findings-emnlp.204" in rebel["DOI"]
    hyper = rows["chia2022hyperred"]
    assert hyper["itemType"] == "preprint"
    assert hyper["url"] == "https://arxiv.org/abs/2211.10018"
    assert rows["yao2019docred"]["conferenceName"] == "ACL"


def test_import_adds_only_new_papers_and_dates_them(review):
    summary = bibtex_import.import_bibtex(review, BIB, "re.bib")
    assert (summary.entries, summary.added, summary.already_there) == (4, 2, 1)
    assert summary.skipped == ["notitle"]

    data = read_results(review.results_path)
    assert len(data) == 4
    assert set(data.loc[data["archive"] == "BibTeX", "title"].str[:5]) == {
        "REBEL",
        "A Dat",
    }

    session = screening.ScreeningSession(review)
    assert dict(session.facet_options()["origin"])["BibTeX import"] == 2
    log = paper_log.load(review.folder)
    dated = [entry for entry in log.values() if entry["imported_at"]]
    assert len(dated) == 2 and {e["origin"] for e in dated} == {"BibTeX import"}

    again = bibtex_import.import_bibtex(review, BIB, "re.bib")
    assert again.added == 0 and again.already_there == 3


def test_not_bibtex(review):
    with pytest.raises(bibtex_import.BibtexImportError):
        bibtex_import.import_bibtex(review, "title;year\nA;2020\n")
