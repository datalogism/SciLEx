"""The ItemType bypass split must not report negative removals downstream."""

import pandas as pd

from scilex.pipeline.orchestrator import _apply_quality_filters_with_bypass
from scilex.pipeline.tracker import FilteringTracker


class _Ctx:
    def __init__(self, quality_filters):
        self.quality_filters = quality_filters
        self.tracker = FilteringTracker()


def test_bypass_split_then_quality_filter_has_no_negative_removal(monkeypatch):
    df = pd.DataFrame(
        {
            "itemType": ["journalArticle"] * 3 + ["preprint"] * 2,
            "title": list("abcde"),
        }
    )
    ctx = _Ctx(
        {"enable_itemtype_bypass": True, "bypass_item_types": ["journalArticle"]}
    )
    ctx.tracker.set_initial(len(df))

    def reject_one(frame, filters, report):
        return frame.iloc[1:], None

    monkeypatch.setattr(
        "scilex.pipeline.orchestrator.apply_quality_filters", reject_one
    )
    result = _apply_quality_filters_with_bypass(ctx, df)

    assert len(result) == 4
    removed = [stage["removed"] for stage in ctx.tracker.stages]
    assert removed == [0, 0, 1]
