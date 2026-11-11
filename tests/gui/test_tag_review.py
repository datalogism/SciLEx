"""Annotations analysis: run, merge decisions, crossing, Zotero cleaning (no network)."""

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import analyses as service
from scilex.gui.services import tag_review

pytestmark = pytest.mark.anyio

RESULTS = pd.DataFrame(
    [
        {"title": "A", "date": "2020", "tags": "Tool:Metashape;Step:3;Onto:CIDOC-CRM"},
        {"title": "B", "date": "2021", "tags": "Tool:MetaShape;Step:4;Onto:CIDOC CRM"},
        {"title": "C", "date": "2021", "tags": "Tool:Blender;Step:3;Onto:PROV-O"},
        {"title": "D", "date": "2022", "tags": "Tool:Blendr;Step:4;Onto:PROV-O"},
    ]
)


def _review(ctx, tmp_path, frame=RESULTS):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    review.collection_dir.mkdir(parents=True)
    frame.to_csv(review.results_path, sep=";", index=False)
    return review


def _run(ctx, review, **kwargs):
    config = ctx.workspace.load_config(review)
    return service.run_tags(
        config, lambda p, m: None, review_folder=review.folder, **kwargs
    )


def test_run_writes_outputs_and_source(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    result = _run(ctx, review)
    paths = tag_review.paths_of(review.collection_dir, review.folder)
    assert "4 of 4 papers annotated" in result.message
    assert paths.source.is_file() and paths.synonyms.is_file()
    assert paths.synonyms.parent == review.folder
    assert result.files[0].name == "annotation_report.md"
    assert service.existing_outputs(review.collection_dir, "tags")


def test_run_without_annotations_is_user_error(ctx, tmp_path):
    review = _review(ctx, tmp_path, pd.DataFrame([{"title": "A", "tags": "HavePDF"}]))
    with pytest.raises(service.AnalysisError, match="No DIMENSION:value"):
        _run(ctx, review)


def test_run_from_zotero_without_source_is_user_error(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    with pytest.raises(service.AnalysisError, match="no Zotero collection"):
        _run(ctx, review, from_zotero=True)


def test_run_from_zotero_reads_live_tags(ctx, tmp_path, monkeypatch):
    review = _review(ctx, tmp_path)
    items = [
        {
            "key": "K1",
            "version": 3,
            "data": {"title": "Live", "itemType": "journalArticle", "date": "2023",
                     "tags": [{"tag": "Tool:Zephyr"}, {"tag": "Step:5"}]},
        }
    ]
    monkeypatch.setattr(tag_review, "fetch_zotero_items", lambda folder: items)
    result = _run(ctx, review, from_zotero=True)
    assert "1 of 1 papers annotated" in result.message
    assert "Zotero" in result.message
    source = pd.read_csv(tag_review.paths_of(review.collection_dir, review.folder).source)
    assert list(source["zotero_key"]) == ["K1"]


def test_accept_and_reject_suggestions(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    _run(ctx, review)
    paths = tag_review.paths_of(review.collection_dir, review.folder)
    pending = tag_review.pending_suggestions(paths)
    blender = pending[pending["dimension"] == "TOOL"].to_dict("records")
    assert blender
    tag_review.accept(paths, blender)
    assert tag_review.pending_suggestions(paths).query("dimension == 'TOOL'").empty
    _run(ctx, review)
    values = pd.read_csv(paths.values)
    tool = values[values["dimension"] == "TOOL"]
    assert len(tool) == 2  # MetaShape (2 spellings) and Blender (merged)
    tag_review.remove_synonyms(paths, blender)
    tag_review.reject(paths, blender)
    _run(ctx, review)
    assert tag_review.pending_suggestions(paths).query("dimension == 'TOOL'").empty


def test_cross_chosen_dimensions(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    _run(ctx, review)
    paths = tag_review.paths_of(review.collection_dir, review.folder)
    assert set(tag_review.dimension_choices(paths)) == {"TOOL", "STEP", "ONTO"}
    path, common = tag_review.cross(paths, "TOOL", "ONTO")
    assert path.is_file() and common == 4
    with pytest.raises(tag_review.TagReviewError):
        tag_review.cross(paths, "TOOL", "TOOL")


def test_preview_cleaning_uses_synonyms(ctx, tmp_path, monkeypatch):
    review = _review(ctx, tmp_path)
    paths = tag_review.paths_of(review.collection_dir, review.folder)
    tag_review.accept(paths, [{"dimension": "TOOL", "value": "Blendr", "merge_into": "Blender"}])
    items = [
        {"key": k, "version": 1, "data": {"title": k, "itemType": "book", "tags": [{"tag": t}]}}
        for k, t in (("A", "Tool:Blendr"), ("B", "Tool:Blender"), ("C", "Tool:Blender"))
    ]
    monkeypatch.setattr(tag_review, "fetch_zotero_items", lambda folder: items)
    preview = tag_review.preview_cleaning(review.folder, paths)
    assert preview.plan.updates == {"A": (1, ["Tool:Blender"])}
    assert preview.examples == [("Tool:Blendr", "Tool:Blender", 1)]


async def test_tab_shows_merge_and_cross_tools(ctx, tmp_path):
    review = _review(ctx, tmp_path)
    _run(ctx, review)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/analyses")
        user.find(marker="analysis-tab-tags").click()
        await user.should_see("Previous results:")
        await user.should_see(marker="tags-suggestions")
        await user.should_see(marker="tags-cross-button")
        # No Zotero collection: no cleaning card.
        await user.should_not_see(marker="tags-zotero")
        user.find(marker="tags-cross-button").click()
        await user.should_see(marker="tags-cross-result", retries=50)
