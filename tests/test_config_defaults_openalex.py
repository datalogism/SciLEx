"""use_openalex_citations is part of the documented quality filter schema."""

from scilex.config_defaults import QUALITY_FILTER_SCHEMA, get_default_quality_filters


def test_use_openalex_citations_in_schema_and_defaults():
    assert QUALITY_FILTER_SCHEMA["use_openalex_citations"] is bool
    assert get_default_quality_filters()["use_openalex_citations"] is True
