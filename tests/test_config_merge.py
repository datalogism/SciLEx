"""_merge_advanced_config: null-safety and recursive merge."""

from scilex.config import _merge_advanced_config


def test_null_quality_filters_in_main():
    main = {"quality_filters": None}
    _merge_advanced_config(main, {"quality_filters": {"max_papers": 5}})
    assert main["quality_filters"] == {"max_papers": 5}


def test_null_quality_filters_in_advanced():
    main = {"quality_filters": {"max_papers": 5}}
    _merge_advanced_config(main, {"quality_filters": None})
    assert main["quality_filters"] == {"max_papers": 5}


def test_nested_partial_override_keeps_other_keys():
    main = {
        "quality_filters": {
            "relevance_weights": {"keywords": 0.5, "quality": 0.5},
            "max_papers": 10,
        }
    }
    _merge_advanced_config(
        main, {"quality_filters": {"relevance_weights": {"keywords": 0.9}}}
    )
    assert main["quality_filters"]["relevance_weights"] == {
        "keywords": 0.9,
        "quality": 0.5,
    }
    assert main["quality_filters"]["max_papers"] == 10


def test_advanced_does_not_alias_its_input():
    advanced = {"quality_filters": {"relevance_weights": {"keywords": 0.9}}}
    main = {}
    _merge_advanced_config(main, advanced)
    main["quality_filters"]["relevance_weights"]["keywords"] = 0.1
    assert advanced["quality_filters"]["relevance_weights"]["keywords"] == 0.9


def test_other_keys_only_fill_absent():
    main = {"years": [2020]}
    _merge_advanced_config(main, {"years": [1999], "extra": 1})
    assert main == {"years": [2020], "extra": 1}
