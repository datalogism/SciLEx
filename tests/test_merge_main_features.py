"""Tests for features merged from origin/main (bonus keywords, report, resume config)."""

import datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml

from scilex.config import SciLExConfig
from scilex.pipeline.bonus_keywords import tag_papers_with_bonus_keywords
from scilex.pipeline.report import write_aggregation_report
from scilex.pipeline.text_filter import record_passes_text_filter
from scilex.pipeline.tracker import FilteringTracker


def test_bonus_keyword_fallback_for_group2():
    record = {"title": "AI", "abstract": "about cultural and heritage things"}
    groups = [["ai"], ["museum"]]
    assert not record_passes_text_filter(record, [], keyword_groups=groups)
    assert record_passes_text_filter(
        record, [], keyword_groups=groups, bonus_keywords=["Cultural Heritage"]
    )


def test_tag_papers_with_bonus_keywords():
    df = pd.DataFrame({"title": ["Cultural heritage"], "abstract": ["x"]})
    tagged = tag_papers_with_bonus_keywords(df, ["Cultural Heritage", "Robots"])
    assert tagged["bonus_keyword_tags"].iloc[0] == "BK:Cultural Heritage"


def test_write_aggregation_report(tmp_path):
    df = pd.DataFrame({"DOI": ["10.1/x"], "archive": ["HAL"]})
    tracker = FilteringTracker()
    tracker.set_initial(1, "init")
    md_path, csv_path = write_aggregation_report(
        str(tmp_path),
        "demo",
        datetime.datetime.now(),
        1.0,
        {"apis": ["HAL"], "years": [2020]},
        {},
        tracker,
        None,
        {},
        df,
    )
    assert "Aggregation Report" in Path(md_path).read_text()
    assert Path(csv_path).read_text().startswith("stat,value")


def test_config_from_collection(tmp_path):
    (tmp_path / "config_used.yml").write_text(yaml.dump({"collect_name": "demo"}))
    config = SciLExConfig.from_collection(str(tmp_path))
    assert config.main["collect_name"] == "demo"
    with pytest.raises(FileNotFoundError):
        SciLExConfig.from_collection(str(tmp_path / "missing"))


def test_write_aggregation_report_empty_dataframe_with_citations(tmp_path):
    df = pd.DataFrame({"DOI": [], "archive": [], "nb_citation": []})
    tracker = FilteringTracker()
    tracker.set_initial(0, "init")
    md_path, csv_path = write_aggregation_report(
        str(tmp_path),
        "demo",
        datetime.datetime.now(),
        1.0,
        {"apis": ["HAL"], "years": [2020]},
        {},
        tracker,
        None,
        {},
        df,
    )
    assert "| Max citations | 0 |" in Path(md_path).read_text()
