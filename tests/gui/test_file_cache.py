"""Files parsed once per version: results and Zotero source."""

import os

import pandas as pd
import pytest

from scilex.gui.services import file_cache
from scilex.gui.services import zotero_library as zl
from scilex.gui.services.extend import read_results, write_results


@pytest.fixture(autouse=True)
def _fresh_cache():
    file_cache.clear()
    yield
    file_cache.clear()


def _frame(*titles):
    return pd.DataFrame([{"title": t, "itemType": "journalArticle"} for t in titles])


def test_results_parsed_once_then_after_each_write(tmp_path):
    path = tmp_path / "rag" / "aggregated_results.csv"
    path.parent.mkdir()
    assert read_results(path) is None
    write_results(_frame("A", "B"), path)
    first = read_results(path)
    second = read_results(path)
    assert file_cache.stats()["hits"] == 1
    # Each call gets its own copy: changing one changes nothing else.
    first.loc[0, "title"] = "changed"
    assert read_results(path).loc[0, "title"] == "A"
    assert list(second["title"]) == ["A", "B"]
    write_results(_frame("A", "B", "C"), path)
    assert list(read_results(path)["title"]) == ["A", "B", "C"]


def test_a_change_by_another_program_is_seen(tmp_path):
    path = tmp_path / "rag" / "aggregated_results.csv"
    path.parent.mkdir()
    write_results(_frame("A"), path)
    assert len(read_results(path)) == 1
    write_results(_frame("A", "B"), tmp_path / "other.csv")
    text = (tmp_path / "other.csv").read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")  # not through SciLEx
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert len(read_results(path)) == 2


def test_zotero_source_cached_and_refreshed_on_save(tmp_path):
    assert zl.load_source(tmp_path) is None
    zl.save_source(tmp_path, zl.ZoteroSource("42", "group", None, ""))
    assert zl.load_source(tmp_path).library_id == "42"
    assert zl.load_source(tmp_path).library_id == "42"
    zl.save_source(tmp_path, zl.ZoteroSource("43", "group", None, ""))
    assert zl.load_source(tmp_path).library_id == "43"
    (tmp_path / zl.SOURCE_FILENAME).write_text("broken: [", encoding="utf-8")
    assert zl.load_source(tmp_path) is None  # unreadable: ignored, as before
