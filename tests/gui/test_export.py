"""Tests of the export service and the Export screen."""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.config import SciLExConfig
from scilex.gui.app import build_root
from scilex.gui.services import exports, screening

pytestmark = pytest.mark.anyio

ROWS = [
    {
        "itemType": "journalArticle",
        "title": "Knowledge graphs for metabolomics",
        "authors": "Alice Martin;Bob Durand",
        "abstract": "We build a graph.",
        "DOI": "10.1000/kg1",
        "date": "2023-05-01",
        "journalAbbreviation": "J. KG",
        "publisher": "Pub",
        "url": "https://example.org/kg1",
        "volume": "1",
        "issue": "2",
        "pages": "1-10",
        "relevance_score": 8.5,
    },
    {
        "itemType": "journalArticle",
        "title": "Mass spectrometry annotation",
        "authors": "Carol Smith",
        "abstract": "We annotate spectra.",
        "DOI": "10.1000/ms2",
        "date": "2022-01-01",
        "journalAbbreviation": "J. MS",
        "publisher": "Pub",
        "url": "https://example.org/ms2",
        "volume": "3",
        "issue": "4",
        "pages": "11-20",
        "relevance_score": 6.0,
    },
    {
        "itemType": "conferencePaper",
        "title": "Ontology alignment",
        "authors": "Dan Lee",
        "abstract": "We align.",
        "DOI": "10.1000/oa3",
        "date": "2021-01-01",
        "journalAbbreviation": "NA",
        "publisher": "NA",
        "url": "https://example.org/oa3",
        "volume": "NA",
        "issue": "NA",
        "pages": "NA",
        "relevance_score": 4.0,
    },
]


@pytest.fixture
def review(ctx, tmp_path):
    """Review with 3 aggregated papers, the first one included."""
    review = ctx.workspace.create_review(tmp_path / "rev", name="rev")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ROWS).to_csv(
        review.collection_dir / "aggregated_results.csv", sep=";", index=False
    )
    key = screening.load_results(review)["paper_key"].iloc[0]
    screening.set_decision(review, key, screening.INCLUDE, "great")
    return review


def test_scope_counts(review):
    assert exports.scope_counts(review) == (1, 3)


def test_bibtex_contains_entries(review):
    path = exports.run_file_export(review, exports.BIBTEX, exports.SCOPE_ALL)
    assert path.parent == exports.exports_dir(review)
    text = path.read_text(encoding="utf-8")
    assert text.count("@") == 3
    assert "Knowledge graphs for metabolomics" in text


def test_bibtex_included_only(review):
    path = exports.run_file_export(review, exports.BIBTEX, exports.SCOPE_INCLUDED)
    text = path.read_text(encoding="utf-8")
    assert text.count("@") == 1
    assert "Ontology alignment" not in text


def test_csv_rows_and_columns(review):
    path = exports.run_file_export(review, exports.CSV, exports.SCOPE_ALL)
    table = pd.read_csv(path, sep=";")
    assert len(table) == 3
    assert "paper_key" not in table.columns
    assert table["screening_decision"].fillna("").tolist().count("include") == 1
    assert "great" in table["screening_note"].tolist()
    included = pd.read_csv(
        exports.run_file_export(review, exports.CSV, exports.SCOPE_INCLUDED), sep=";"
    )
    assert len(included) == 1


def test_turtle_parses(review):
    rdflib = pytest.importorskip("rdflib")
    path = exports.run_file_export(review, exports.TURTLE, exports.SCOPE_ALL)
    graph = rdflib.Graph().parse(path, format="turtle")
    assert len(graph) > 0


def test_empty_scope_is_refused(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "e", name="e")
    review.collection_dir.mkdir(parents=True)
    pd.DataFrame(ROWS).to_csv(review.results_path, sep=";", index=False)
    with pytest.raises(ValueError):
        exports.run_file_export(review, exports.CSV, exports.SCOPE_INCLUDED)


def test_list_exports_newest_first(review):
    assert exports.list_exports(review) == []
    first = exports.run_file_export(review, exports.CSV, exports.SCOPE_ALL)
    assert exports.list_exports(review) == [first]


def test_zotero_settings():
    complete = SciLExConfig({}, {"Zotero": {"api_key": "k", "user_id": "1"}})
    assert exports.zotero_settings(complete).user_mode == "user"
    assert exports.zotero_settings(SciLExConfig({}, {})) is None
    # The global key alone is enough: the review's group gives the library.
    key_only = exports.zotero_settings(SciLExConfig({}, {"Zotero": {"api_key": "k"}}))
    assert key_only.api_key == "k" and key_only.user_id == ""


def test_push_to_zotero_with_mock_client(review, monkeypatch):
    monkeypatch.setattr("scilex.push_to_zotero.prefetch_templates", lambda data: {})
    monkeypatch.setattr(
        "scilex.push_to_zotero.prepare_zotero_item",
        lambda row, key, templates: {"url": row["url"], "title": row["title"]},
    )
    api = MagicMock()
    api.get_or_create_collection.return_value = {"data": {"key": "COLL"}}
    api.get_existing_item_urls.return_value = {"https://example.org/ms2"}
    api.post_items_bulk.return_value = {"success": 1, "failed": 0}
    counts = exports.push_to_zotero(
        review, SciLExConfig({}, {}), exports.SCOPE_ALL, zotero_api=api
    )
    uploaded = api.post_items_bulk.call_args.args[0]
    assert {item["url"] for item in uploaded} == {
        "https://example.org/kg1",
        "https://example.org/oa3",
    }
    assert counts["success"] == 1
    assert counts["skipped"] == 1


def test_reveal_command(tmp_path):
    target = tmp_path / "x.bib"
    assert exports.reveal_command(target, "darwin") == ["open", "-R", str(target)]
    assert exports.reveal_command(target, "win32")[0] == "explorer"
    assert exports.reveal_command(target, "linux") == ["xdg-open", str(tmp_path)]


async def test_page_bibtex_export_shows_path(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/export")
        await user.should_see("Included papers only (1)")
        user.find(marker="export-bibtex").click()
        await user.should_see("Exported to", retries=50)
        files = exports.list_exports(review)
        assert len(files) == 1
        await user.should_see(files[0].name)


async def test_page_zotero_disabled_without_settings(ctx, review):
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/export")
        button = user.find(marker="export-zotero").elements.pop()
        assert not button.enabled
        await user.should_see(marker="export-zotero-keys")


def test_export_path_never_overwrites_an_existing_export(ctx, tmp_path):
    from scilex.gui.services import exports

    review = ctx.workspace.create_review(tmp_path / "rag2", name="rag_kg")
    first = exports.export_path(review, "papers", "all", "csv")
    first.write_text("a")
    second = exports.export_path(review, "papers", "all", "csv")
    assert second != first
    second.write_text("b")
    assert exports.export_path(review, "papers", "all", "csv") not in (first, second)
