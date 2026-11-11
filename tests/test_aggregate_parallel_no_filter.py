"""Tests for parallel_aggregate with txt_filters=False (convert only)."""

import json

from scilex.crawlers.aggregate_parallel import parallel_aggregate


def _write_collection(tmp_path):
    query_dir = tmp_path / "HAL" / "0"
    query_dir.mkdir(parents=True)
    papers = [
        {
            "halId_s": "hal-1",
            "title_s": ["Deep learning survey"],
            "abstract_s": ["deep learning methods"],
            "authFullName_s": ["Smith J"],
            "submittedDate_tdate": "2022-01-15T00:00:00Z",
            "docType_s": "ART",
            "uri_s": "https://hal.science/hal-1",
            "doiId_s": "10.1/one",
        },
        {
            "halId_s": "hal-2",
            "title_s": ["Unrelated gardening notes"],
            "abstract_s": ["tomatoes and soil"],
            "authFullName_s": ["Doe J"],
            "submittedDate_tdate": "2022-02-15T00:00:00Z",
            "docType_s": "ART",
            "uri_s": "https://hal.science/hal-2",
            "doiId_s": "10.1/two",
        },
    ]
    (query_dir / "page_1").write_text(json.dumps({"results": papers}))
    return {"keywords": [["deep learning"]], "years": [2022], "apis": ["HAL"]}


def test_text_filter_enabled_drops_unrelated(tmp_path):
    config = _write_collection(tmp_path)
    df, _ = parallel_aggregate(str(tmp_path), config, txt_filters=True, num_workers=1)
    assert len(df) == 1


def test_text_filters_disabled_keeps_all_converted_papers(tmp_path):
    config = _write_collection(tmp_path)
    df, stats = parallel_aggregate(
        str(tmp_path), config, txt_filters=False, num_workers=1
    )
    assert len(df) == 2
    assert stats["processing"]["papers_filtered"] == 2
