"""Annotate step, VPN editor and the OpenCitations switch."""

import pandas as pd
import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.components import vpn_editor as vpn
from scilex.gui.services import annotations as service
from scilex.gui.services import zotero_library
from scilex.tagging.grid import PAPER_TYPES


def paper(key, tags, version=1):
    return {
        "key": key,
        "version": version,
        "data": {
            "itemType": "journalArticle",
            "title": f"Paper {key}",
            "tags": [{"tag": t} for t in tags],
        },
        "meta": {"createdByUser": {"username": "scilex"}},
    }


class FakeZotero:
    user_id, user_role = "1", "user"

    def __init__(self, items):
        self.items = items
        self.updates = None

    def get_collections(self):
        return [{"data": {"key": "C1", "name": "rag_kg"}, "meta": {"numItems": 2}}]

    def get_groups(self):
        return []

    def get_top_items(self, collection_key=None):
        return self.items

    def update_item_tags(self, updates):
        self.updates = updates
        return {"success": len(updates), "failed": 0}


# -- services -----------------------------------------------------------------


def test_grid_rows_round_trip_keeps_extra_columns():
    grid = pd.DataFrame(
        [{"tag": "A", "detail": "Q", "datasets": "X", "models": "", "nb": "4"}]
    )
    rows = service.grid_to_rows(grid)
    assert rows[0]["datasets"] is True and rows[0]["models"] is False
    rows[0]["models"] = True
    back = service.rows_to_grid(rows, grid)
    assert back.loc[0, "models"] == "X" and back.loc[0, "nb"] == "4"


def test_plan_apply_and_report(tmp_path, ctx):
    review = ctx.workspace.create_review(tmp_path / "r", name="r")
    grid = pd.DataFrame([{"tag": "SAT_TASK", **dict.fromkeys(PAPER_TYPES, "X")}])
    items = [paper("A", ["SAT_TASK:Ner"]), paper("B", ["HavePDF"])]
    plan = service.plan_apply(grid, items, "datasets", keep_other_tags=True)
    assert list(plan.updates) == ["B"] and plan.papers == 2
    with pytest.raises(ValueError):
        service.plan_apply(
            pd.DataFrame([{"tag": "X", "models": "X"}]), items, "surveys", True
        )

    report = service.build_report(review, items)
    assert report.papers == 2
    assert report.by_dimension["dimension"].tolist() == ["SAT_TASK"]
    assert (report.folder / "tags_by_dimension.csv").is_file()


# -- VPN editor helpers ---------------------------------------------------------


def test_country_modes_map_to_countries_key():
    assert vpn.country_mode({}) == vpn.COUNTRY_ALL
    assert vpn.country_mode({"countries": []}) == vpn.COUNTRY_QUICK
    assert vpn.country_mode({"countries": ["France"]}) == vpn.COUNTRY_LIST
    block = {"enabled": True, "countries": ["France"]}
    assert "countries" not in vpn.with_country_mode(block, vpn.COUNTRY_ALL, [])
    assert vpn.with_country_mode(block, vpn.COUNTRY_QUICK, [])["countries"] == []
    assert vpn.with_country_mode({}, vpn.COUNTRY_LIST, ["Italy"])["countries"] == [
        "Italy"
    ]


def test_disabled_vpn_block_is_not_written():
    assert vpn.normalized({"enabled": False, "provider": "nordvpn"}) is None
    kept = {"enabled": False, "rotation_delay": 20}
    assert vpn.normalized(kept) == kept


def test_vpn_status_never_rotates(monkeypatch):
    from scilex.vpn import rotator

    monkeypatch.setattr(
        rotator.VPNRotator, "_get_public_ip", staticmethod(lambda: "1.2.3.4")
    )
    monkeypatch.setattr(
        rotator.VPNRotator, "rotate", lambda self: pytest.fail("rotated")
    )
    status = rotator.vpn_status()
    assert status["public_ip"] == "1.2.3.4"


# -- OpenCitations switch -------------------------------------------------------


def test_opencitations_setting_reaches_the_pipeline(tmp_path):
    from scilex.settings.loader import load_settings, to_legacy

    config = tmp_path / "scilex.yml"
    config.write_text(
        "name: x\nsearch:\n  keywords: [[a]]\n  years: 2024\n  apis: [OpenAlex]\n"
        "citations:\n  opencitations: false\n",
        encoding="utf-8",
    )
    keys = tmp_path / "keys.yml"
    keys.write_text("{}\n", encoding="utf-8")
    loaded = load_settings(config_path=config, keys_path=keys)
    assert loaded.settings.citations.opencitations is False
    main_config, _ = to_legacy(loaded.settings)
    assert main_config["quality_filters"]["use_opencitations"] is False


def test_fetcher_skips_opencitations_phase(monkeypatch):
    from scilex.citations import fetcher

    called = []
    monkeypatch.setattr(
        fetcher, "_phase_opencitations", lambda *a, **k: called.append(True)
    )
    monkeypatch.setattr(fetcher, "_phase_crossref", lambda *a, **k: None)
    df = pd.DataFrame({"DOI": ["10.1/a"]})
    fetcher.fetch_citations_for_dataframe(df, use_cache=False, use_opencitations=False)
    assert called == []
    fetcher.fetch_citations_for_dataframe(df, use_cache=False)
    assert called == [True]


# -- pages ----------------------------------------------------------------------


@pytest.mark.anyio
async def test_annotate_step_shows_grid_and_collection(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "r", name="rag_kg")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/annotate")
        await user.should_see("Annotation grid")
        await user.should_see(marker="annotate-collection-select")
        user.find(marker="annotate-default").click()
        user.find(marker="annotate-save").click()
    assert (review.folder / "annotation_grid.csv").is_file()


@pytest.mark.anyio
async def test_annotate_preview_then_apply(ctx, tmp_path, monkeypatch):
    review = ctx.workspace.create_review(tmp_path / "r", name="rag_kg")
    service.save_review_grid(
        review, pd.DataFrame([{"tag": "SAT_TASK", **dict.fromkeys(PAPER_TYPES, "X")}])
    )
    fake = FakeZotero([paper("A", ["HavePDF"], version=9)])
    monkeypatch.setattr(zotero_library, "client", lambda keys=None, library=None: fake)
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/annotate")
        user.find(marker="annotate-load-collections").click()
        await user.should_see("1 collections")
        user.find(marker="annotate-preview-button").click()
        await user.should_see("1 of 1 papers")
        user.find(marker="annotate-apply-button").click()
        await user.should_see("1 papers updated", retries=40)
    assert fake.updates == {"A": (9, ["HavePDF", "SAT_TASK:?"])}


@pytest.mark.anyio
async def test_new_review_from_zotero_dialog(ctx, tmp_path, monkeypatch):
    items = [
        paper("A", ["Collect_KW1:graph rag"])
        | {
            "data": {
                "itemType": "journalArticle",
                "title": "Paper A",
                "date": "2024",
                "tags": [{"tag": "Collect_KW1:graph rag"}, {"tag": "SAT_TASK:Ner"}],
            }
        }
    ]
    monkeypatch.setattr(
        zotero_library, "client", lambda keys=None, library=None: FakeZotero(items)
    )
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/")
        user.find(marker="new-review").click()
        user.find(marker="new-review-start").elements.pop().value = "zotero"
        user.find(marker="folder").type(str(tmp_path / "imported"))
        user.find(marker="zotero-load").click()
        await user.should_see(marker="zotero-collection")
        select = user.find(marker="zotero-collection").elements.pop()
        for _ in range(50):  # options arrive after the io_bound call
            if select.options:
                break
            await __import__("asyncio").sleep(0.05)
        select.value = "C1"
        user.find(marker="create").click()
        await user.should_see(marker="step-annotate")
    [review] = ctx.workspace.list_reviews()
    assert review.name == "rag_kg"  # suggested from the collection name
    assert review.has_results
    assert (review.folder / "annotation_grid.csv").is_file()
