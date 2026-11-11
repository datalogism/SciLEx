"""Layout and walkthrough fixes: collect log width, years text, home refresh."""

import pytest
import yaml
from nicegui import ui
from nicegui.testing import user_simulation

from scilex.config import SciLExConfig
from scilex.gui.app import build_root
from scilex.gui.services.collect_summary import preflight_line

pytestmark = pytest.mark.anyio


def _write_years(review, years):
    raw = yaml.safe_load(review.config_path.read_text(encoding="utf-8"))
    raw["search"]["years"] = years
    review.config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")


@pytest.mark.parametrize(
    ("years", "expected"),
    [([2024, 2026], "2024, 2026"), ("2022-2024", "2022-2024"), ([2024], "2024")],
)
def test_preflight_shows_years_as_written(ctx, tmp_path, years, expected):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag")
    _write_years(review, years)
    from scilex.gui.services.workspace import Workspace

    config = Workspace.load_config(review)
    assert f"for {expected}," in preflight_line(config, review.config_path)


def test_preflight_without_path_uses_list_for_gaps():
    config = SciLExConfig({"years": [2024, 2026], "apis": [], "keywords": []}, {})
    assert "for 2024, 2026," in preflight_line(config)
    config = SciLExConfig({"years": [2022, 2023, 2024], "apis": []}, {})
    assert "for 2022-2024," in preflight_line(config)


async def test_collect_log_spans_the_content_width(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag")
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}/collect")
        # Hidden until a job runs: look it up among all elements.
        log = next(e for e in user.client.elements.values() if isinstance(e, ui.log))
        assert "w-full" in log.classes
        # Every ancestor up to the sub-pages container must fill the width.
        element = log.parent_slot.parent
        chain = []
        while element is not None and "nicegui-sub-pages" not in element.classes:
            chain.append(element)
            element = element.parent_slot.parent if element.parent_slot else None
        assert element is not None, "sub-pages container not found"
        assert "w-full" in element.classes
        content = next(e for e in chain if "min-w-0" in e.classes)
        assert "flex-1" in content.classes
        for item in chain:
            if item is content:
                continue
            if "nicegui-row" in item.classes or "nicegui-column" in item.classes:
                assert (
                    "w-full" in item.classes
                    or "flex-1" in item.classes
                    or "grow" in item.classes
                )


async def test_home_card_disappears_after_remove(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_unique")
    async with user_simulation(build_root(ctx)) as user:
        await user.open("/")
        await user.should_see("rag_unique")
        user.find(marker=f"forget-item-{review.id}").click()
        user.find(marker=f"forget-confirm-{review.id}").click()
        await user.should_not_see("rag_unique")
