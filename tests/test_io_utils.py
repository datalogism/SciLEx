"""Tests for scilex.io_utils."""

import os

import pandas as pd
import pytest

from scilex.constants import MISSING_VALUE, is_valid
from scilex.io_utils import (
    load_aggregated_data,
    resolve_aggregate_path,
    write_aggregated_csv,
)


def _config(tmp_path):
    return {
        "output_dir": str(tmp_path),
        "collect_name": "c",
        "aggregate_file": "agg.csv",
    }


def _write(tmp_path, text):
    (tmp_path / "c").mkdir(exist_ok=True)
    (tmp_path / "c" / "agg.csv").write_text(text, encoding="utf-8")


def test_resolve_path_and_collect_dir_override(tmp_path):
    cfg = _config(tmp_path)
    assert resolve_aggregate_path(cfg) == os.path.join(str(tmp_path), "c", "agg.csv")
    assert resolve_aggregate_path(cfg, collect_dir="/x") == os.path.join(
        "/x", "agg.csv"
    )


def test_delimiter_fallback(tmp_path):
    _write(tmp_path, "itemType,title\narticle,T\n")
    assert len(load_aggregated_data(_config(tmp_path))) == 1


def test_error_message_has_real_cause(tmp_path):
    _write(tmp_path, "foo;bar\n1;2\n")
    with pytest.raises(ValueError, match="Last error"):
        load_aggregated_data(_config(tmp_path))


def test_missing_marker_round_trip(tmp_path):
    """The literal 'NA' must survive a read/write cycle (enrichment rewrites the CSV)."""
    _write(tmp_path, "itemType;title;DOI\narticle;T;NA\narticle;U;\n")
    cfg = _config(tmp_path)
    data = load_aggregated_data(cfg, preserve_missing_marker=True)
    assert data.loc[0, "DOI"] == MISSING_VALUE
    assert pd.isna(data.loc[1, "DOI"])
    path = resolve_aggregate_path(cfg)
    write_aggregated_csv(data, path)
    with open(path, encoding="utf-8") as handle:
        assert "article;T;NA" in handle.read()
    reloaded = load_aggregated_data(cfg)
    assert not is_valid(reloaded.loc[0, "DOI"])
    assert not is_valid(reloaded.loc[1, "DOI"])
    assert [f for f in os.listdir(tmp_path / "c") if f.endswith(".tmp")] == []


def test_atomic_write_keeps_original_on_failure(tmp_path):
    target = tmp_path / "out.csv"
    target.write_text("old", encoding="utf-8")

    class Boom:
        def to_csv(self, *args, **kwargs):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        write_aggregated_csv(Boom(), str(target))
    assert target.read_text(encoding="utf-8") == "old"
    assert os.listdir(tmp_path) == ["out.csv"]
