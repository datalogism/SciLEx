"""⑤ Extend from Zotero (Zotero API mocked)."""

import pandas as pd
import pytest

from scilex.constants import is_valid
from scilex.gui.services import paper_log, zotero_extend, zotero_library, zotero_sync
from scilex.gui.services.extend import read_results
from scilex.gui.services.workspace import Review

SOURCE = zotero_library.ZoteroSource(
    library_id="6756633",
    library_type="group",
    collection_key=None,
    collection_name="",
    library_name="scilexre_surveyv",
)


def item(key, title, doi="", tags=(), collections=()):
    return {
        "key": key,
        "data": {
            "itemType": "conferencePaper",
            "title": title,
            "DOI": doi,
            "date": "2021",
            "tags": [{"tag": t} for t in tags],
        },
        "_scilex_collections": list(collections),
    }


ITEMS = [
    item("AAAA", "REBEL", "10.1/rebel", ["TASK:RE", "LANG:English"], ["models"]),
    item("BBBB", "DocRED", "10.1/docred", ["TASK:RE"], ["datasets"]),
    item("BBBC", "DocRED", "10.1/docred"),  # the same paper twice in Zotero
]


@pytest.fixture
def review(tmp_path, monkeypatch):
    review = Review(folder=tmp_path, name="re", output_root=tmp_path / "output")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "itemType": ["conferencePaper"],
            "title": ["REBEL"],
            "DOI": ["10.1/rebel"],
            "date": ["2021"],
            "archive": ["Zotero"],
            "tags": ["LANG:English"],
            "zotero_key": ["OLDKEY"],
        }
    ).to_csv(review.results_path, sep=";")
    monkeypatch.setattr(zotero_library, "client", lambda *a, **k: object())
    monkeypatch.setattr(zotero_library, "list_collections", lambda api: [])
    monkeypatch.setattr(zotero_library, "fetch_source_papers", lambda api, s, c: ITEMS)
    monkeypatch.setattr("scilex.gui.services.keys_editor.effective_keys", lambda f: {})
    return review


def test_adds_new_papers_merges_tags_and_stays_unlinked(review):
    summary = zotero_extend.extend_from_zotero(review, SOURCE, link=False)
    assert (summary.fetched, summary.added, summary.already_there) == (3, 1, 1)
    assert summary.enriched == 1 and summary.linked is None

    data = read_results(review.results_path).set_index("title")
    # Tags merged, then every paper gets its default type.
    assert (
        data.loc["REBEL", "tags"] == "LANG:English;TASK:RE;PAPER_TYPE:Model or Method"
    )
    assert "PAPER_TYPE:" in data.loc["DocRED", "tags"]  # the added paper too
    assert data.loc["REBEL", "zotero_collections"] == "models"
    assert data.loc["REBEL", "zotero_key"] == "OLDKEY"  # not linked: left as it was
    assert not is_valid(data.loc["DocRED", "zotero_key"])  # no key outside a link
    assert data.loc["DocRED", "extension_origin"].startswith(
        "zotero the whole library scilexre_surveyv"
    )
    assert zotero_library.load_source(review.folder) is None
    log = paper_log.load(review.folder)
    assert {e["origin"] for e in log.values()} == {"Zotero import"}


def test_link_saves_the_library_and_matches_the_papers(review, monkeypatch):
    calls = []
    monkeypatch.setattr(
        zotero_sync, "link", lambda r: calls.append(r) or {"linked": 2, "papers": 2}
    )
    summary = zotero_extend.extend_from_zotero(review, SOURCE, link=True)
    assert summary.linked == 2 and calls == [review]
    assert zotero_library.load_source(review.folder).library_id == "6756633"
    assert "Linked to this library: 2 papers" in summary.message()
