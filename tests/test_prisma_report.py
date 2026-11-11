"""Tests for the PRISMA 2020 report (issue #49)."""

from datetime import datetime

from scilex.pipeline.report import (
    build_prisma_report,
    compute_prisma_screening_steps,
    write_prisma_report,
)
from scilex.pipeline.tracker import FilteringTracker


def _tracker():
    tracker = FilteringTracker()
    tracker.set_initial(100, "Papers after deduplication")
    tracker.add_stage("ItemType Filter", 90, "whitelist")
    tracker.add_stage("ItemType Bypass Split", 70, "split")
    tracker.add_stage("Quality Filter", 75, "quality")
    tracker.add_stage("Citation Filter", 60, "citations")
    tracker.add_stage("Relevance Ranking", 50, "top 50")
    return tracker


PARALLEL_STATS = {
    "loading": {"total_papers": 300, "per_api": {"OpenAlex": 200, "arXiv": 100}},
    "processing": {"papers_rejected": 150},
    "deduplication": {"total_removed": 50},
}


def test_steps_skip_bypass_split_and_compute_exclusions():
    steps = compute_prisma_screening_steps(_tracker())
    assert [s["stage"] for s in steps] == [
        "ItemType Filter",
        "Quality Filter",
        "Citation Filter",
        "Relevance Ranking",
    ]
    # Quality filter follows the itemtype filter (90), not the bypass split (70)
    assert [s["excluded"] for s in steps] == [10, 15, 15, 10]


def test_report_contains_counts_and_mermaid():
    content = build_prisma_report(
        "demo", datetime(2026, 1, 1), PARALLEL_STATS, _tracker(), 50
    )
    assert "| OpenAlex | 200 |" in content
    assert "| **Total** | **300** |" in content
    assert "```mermaid\nflowchart TD" in content
    assert "Records screened" in content and "n = 100" in content
    assert "Records included<br/>n = 50" in content
    assert "Duplicates: n = 50" in content


def test_write_report(tmp_path):
    path = write_prisma_report(
        str(tmp_path), "demo", datetime(2026, 1, 1), PARALLEL_STATS, _tracker(), 50
    )
    assert path.endswith("prisma_report.md")
    assert (tmp_path / "prisma_report.md").read_text().startswith("# PRISMA Report")
