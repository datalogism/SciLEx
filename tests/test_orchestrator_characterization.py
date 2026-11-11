"""Characterization tests pinning the observable behavior of run_aggregation().

They run the whole aggregation on small fake HAL collections written in the
real on-disk format, with every network-bound step mocked. Their purpose is to
guarantee that refactoring the orchestrator does not change its output.
"""

import json
from unittest.mock import patch

import pandas as pd
import yaml

from scilex.config import SciLExConfig
from scilex.pipeline.orchestrator import AggregationOptions, run_aggregation

COLLECT_NAME = "charac"


def _hal_paper(hal_id, title, abstract, year, doi, doc_type="ART"):
    return {
        "halId_s": hal_id,
        "title_s": [title],
        "abstract_s": [abstract],
        "authFullName_s": ["Smith J", "Doe A"],
        "submittedDate_tdate": f"{year}-03-15T00:00:00Z",
        "docType_s": doc_type,
        "uri_s": f"https://hal.science/{hal_id}",
        "doiId_id": doi,
    }


PAPERS = [
    _hal_paper(
        "hal-1",
        "Deep learning for metabolomics",
        "We apply deep learning to metabolomics data. " * 5,
        2022,
        "10.1/one",
    ),
    _hal_paper(
        "hal-2",
        "Deep learning on graphs",
        "A knowledge graph study using deep learning. " * 5,
        2021,
        "10.1/two",
    ),
    # Duplicate of hal-1 (same DOI), must be merged by deduplication.
    _hal_paper(
        "hal-3",
        "Deep learning for metabolomics",
        "We apply deep learning to metabolomics data. " * 5,
        2022,
        "10.1/one",
    ),
    _hal_paper(
        "hal-4",
        "Unrelated gardening notes",
        "Tomatoes and soil, nothing else. " * 5,
        2022,
        "10.1/four",
    ),
    _hal_paper(
        "hal-5",
        "Deep learning in chemistry",
        "Deep learning for chemistry applications. " * 5,
        2022,
        "10.1/five",
    ),
]

CITATIONS_BY_DOI = {"10.1/one": 12, "10.1/two": 3, "10.1/five": 0}


def _fake_fetch_citations(df, **kwargs):
    counts = [CITATIONS_BY_DOI.get(doi, 0) for doi in df["DOI"]]
    stats = {"success": len(df), "error": 0, "timeout": 0}
    return ["{}"] * len(df), [0] * len(df), counts, stats


def _build_config(tmp_path, quality_filters=None):
    output_dir = tmp_path / "output"
    collect_dir = output_dir / COLLECT_NAME
    query_dir = collect_dir / "HAL" / "0"
    query_dir.mkdir(parents=True)
    (query_dir / "page_1").write_text(json.dumps({"results": PAPERS}))
    main_config = {
        "keywords": [["deep learning"]],
        "years": [2021, 2022],
        "apis": ["HAL"],
        "collect_name": COLLECT_NAME,
        "output_dir": str(output_dir),
        "aggregate_file": "aggregated.csv",
        "aggregate_get_citations": True,
        "generate_prisma_report": True,
        "quality_filters": quality_filters or {},
    }
    (collect_dir / "config_used.yml").write_text(yaml.safe_dump(main_config))
    return SciLExConfig.from_dicts(main_config, {}), collect_dir


def _run(config, **option_overrides):
    options = AggregationOptions(
        no_abstract_enrichment=True, parallel_workers=1, **option_overrides
    )
    calls = []
    with (
        patch(
            "scilex.citations.fetcher.fetch_citations_for_dataframe",
            side_effect=_fake_fetch_citations,
        ),
        patch(
            "scilex.pipeline.orchestrator.use_semantic_scholar_citations_fallback",
            side_effect=lambda df: df,
        ),
        patch(
            "scilex.pipeline.orchestrator.use_openalex_citations_fallback",
            side_effect=lambda df: df,
        ),
        patch(
            "scilex.pipeline.orchestrator.apply_time_aware_citation_filter",
            side_effect=lambda df: df[df["nb_citation"] >= 1].reset_index(drop=True),
        ),
    ):
        df = run_aggregation(
            config, options, progress_callback=lambda *args: calls.append(args)
        )
    return df, calls


def _snapshot(collect_dir, df, calls):
    written = pd.read_csv(collect_dir / "aggregated.csv", sep=";")
    summary = json.loads((collect_dir / "filtering_summary.json").read_text())
    return {
        "columns": list(written.columns),
        "dois": list(written["DOI"]),
        "returned_dois": list(df["DOI"]),
        "titles": list(written["title"]),
        "quality_score": list(written["quality_score"]),
        "relevance_score": (
            [round(v, 4) for v in written["relevance_score"]]
            if "relevance_score" in written
            else None
        ),
        "nb_citation": (
            list(written["nb_citation"]) if "nb_citation" in written else None
        ),
        "initial": summary["initial_count"],
        "final": summary["final_count"],
        "stages": [(s["stage"], s["papers"]) for s in summary["stages"]],
        "progress": [(c[0], c[1]) for c in calls],
    }


BASE_COLUMNS = [
    "title",
    "publisher",
    "itemType",
    "authors",
    "language",
    "abstract",
    "archiveID",
    "archive",
    "date",
    "DOI",
    "url",
    "rights",
    "pages",
    "journalAbbreviation",
    "volume",
    "serie",
    "issue",
    "pdf_url",
    "collect_keywords",
    "quality_score",
]
FULL_PROGRESS = [
    ("initializing", 5),
    ("aggregating", 10),
    ("filtering", 30),
    ("filtering", 45),
    ("citations", 55),
    ("ranking", 85),
    ("completed", 100),
]


def test_citations_and_ranking_enabled(tmp_path):
    config, collect_dir = _build_config(tmp_path)
    df, calls = _run(config)
    snapshot = _snapshot(collect_dir, df, calls)

    assert snapshot == {
        "columns": BASE_COLUMNS
        + [
            "extra",
            "nb_cited",
            "nb_citation",
            "canonical_citation_count",
            "relevance_score",
            "bonus_keyword_tags",
        ],
        "dois": ["10.1/one", "10.1/two"],
        "returned_dois": ["10.1/one", "10.1/two"],
        "titles": ["Deep learning for metabolomics", "Deep learning on graphs"],
        "quality_score": [19, 19],
        "relevance_score": [6.21, 5.95],
        "nb_citation": [12, 3],
        "initial": 3,
        "final": 2,
        "stages": [
            ("Initial", 3),
            ("ItemType Bypass Split", 3),
            ("Quality Filter", 3),
            ("Citation Filter", 2),
            ("Relevance Ranking", 2),
        ],
        "progress": FULL_PROGRESS,
    }
    for report_name in (
        "aggregation_stats.csv",
        "aggregation_report.md",
        "prisma_report.md",
        "filtering_summary.json",
    ):
        assert (collect_dir / report_name).exists(), report_name
    assert not (collect_dir / "citation_checkpoint.json").exists()


def test_citations_and_ranking_disabled(tmp_path):
    config, collect_dir = _build_config(
        tmp_path, quality_filters={"apply_relevance_ranking": False}
    )
    df, calls = _run(config, skip_citations=True)
    snapshot = _snapshot(collect_dir, df, calls)

    assert snapshot == {
        "columns": BASE_COLUMNS + ["bonus_keyword_tags"],
        "dois": ["10.1/one", "10.1/two", "10.1/five"],
        "returned_dois": ["10.1/one", "10.1/two", "10.1/five"],
        "titles": [
            "Deep learning for metabolomics",
            "Deep learning on graphs",
            "Deep learning in chemistry",
        ],
        "quality_score": [19, 19, 19],
        "relevance_score": None,
        "nb_citation": None,
        "initial": 3,
        # All papers are bypassed: a "Quality Filter" stage records the kept
        # total so the summary matches the 3 papers written.
        "final": 3,
        "stages": [("Initial", 3), ("ItemType Bypass Split", 3), ("Quality Filter", 3)],
        "progress": FULL_PROGRESS,
    }


def test_itemtype_filter_removing_everything_returns_early(tmp_path):
    config, collect_dir = _build_config(
        tmp_path,
        quality_filters={
            "enable_itemtype_filter": True,
            "allowed_item_types": ["book"],
        },
    )
    df, calls = _run(config)

    assert len(df) == 0
    assert not (collect_dir / "aggregated.csv").exists()
    assert not (collect_dir / "filtering_summary.json").exists()
    assert [(c[0], c[1]) for c in calls] == FULL_PROGRESS[:3]
