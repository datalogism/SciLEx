"""Enrich: citations from the Zotero snapshot, citation metrics, discarded papers."""

import json

import pandas as pd
import pytest

from scilex.gui.services import analyses as service
from scilex.gui.services import zotero_citations
from scilex.gui.services.extend import read_results


@pytest.fixture
def review(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "cit", name="cit_review")
    review.collection_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "itemType": ["journalArticle"] * 3,
            "title": ["Cited paper", "Citing paper", "Discarded paper"],
            "DOI": ["10.1/a", "10.1/b", "10.1/c"],
            "date": ["2020", "2022", "2021"],
            "tags": ["TASK:RE", "", "DELETED_BY:filter:year"],
        }
    ).to_csv(review.results_path, sep=";")
    caches = {
        "citations_cache.json": {"10.1/b": ["10.1/a"], "10.1/c": ["10.1/a"]},
        "citers_cache.json": {"10.1/a": ["10.1/b", "10.1/c", "10.9/x"]},
    }
    for name, data in caches.items():
        (review.collection_dir / name).write_text(json.dumps(data), encoding="utf-8")
    return review


def test_without_discarded():
    df = pd.DataFrame({"tags": ["A:b", "DELETED_BY:me", None]})
    assert list(service.without_discarded(df).index) == [0, 2]


def test_metrics_tab_writes_tags_and_skips_discarded(ctx, review):
    from scilex.gui.services.workspace import Workspace

    config = Workspace.load_config(review)
    result = service.RUNNERS["metrics"](config, lambda *a: None)
    assert "2 papers" in result.message
    rows = {r["title"]: r for r in read_results(review.results_path).to_dict("records")}
    assert "CITATIONS:10^0" in rows["Cited paper"]["tags"]
    assert rows["Cited paper"]["tags"].startswith("TASK:RE;")
    assert rows["Discarded paper"]["tags"] == "DELETED_BY:filter:year"
    assert not pd.notna(rows["Discarded paper"].get("metric_citations")) or rows[
        "Discarded paper"
    ]["metric_citations"] in ("", "NA")


def test_citations_from_zotero_snapshot(ctx, review, monkeypatch):
    from scilex.gui.services.workspace import Workspace

    report = zotero_citations.SnapshotReport(papers=2, references=1, citers=3)
    monkeypatch.setattr(zotero_citations, "import_snapshot", lambda r: report)
    config = Workspace.load_config(review)
    result = service.RUNNERS["citations"](
        config, lambda *a: None, source="zotero", review=review
    )
    assert result.message.startswith("Citation snapshot from Zotero: 2 papers")
    with pytest.raises(service.AnalysisError):
        service.RUNNERS["citations"](config, lambda *a: None, source="zotero")
