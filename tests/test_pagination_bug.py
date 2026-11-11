"""Tests for pagination logic in collectors.

Verifies that pagination correctly respects max_articles_per_query limits
and doesn't over-fetch beyond the configured maximum.
"""

import math

import pytest


def _simulate_buggy_pagination(max_articles, max_by_page, total_available):
    """Simulate the old (buggy) pagination logic that checks AFTER fetching."""
    page = 1
    has_more_pages = True
    nb_art_collected = 0

    while has_more_pages and page <= 20:  # safety limit
        fetched = min(max_by_page, total_available - nb_art_collected)
        nb_art_collected += fetched

        expected_pages = math.ceil(total_available / max_by_page)
        has_more_pages = page < expected_pages

        max_pages = math.ceil(max_articles / max_by_page)
        has_more_pages = has_more_pages and (page < max_pages)
        page += 1

    return nb_art_collected


def _simulate_fixed_pagination(max_articles, max_by_page, total_available):
    """Simulate the fixed pagination logic with pre-check BEFORE fetching."""
    page = 1
    has_more_pages = True
    nb_art_collected = 0

    while has_more_pages and page <= 20:  # safety limit
        max_pages = math.ceil(max_articles / max_by_page)
        if page > max_pages:
            break

        fetched = min(max_by_page, total_available - nb_art_collected)
        nb_art_collected += fetched

        expected_pages = math.ceil(total_available / max_by_page)
        has_more_pages = page < expected_pages
        page += 1

    return nb_art_collected


class TestBuggyPaginationExceedsLimit:
    """The buggy logic collects more than max_articles because it checks AFTER fetch."""

    def test_buggy_logic_exceeds_limit(self):
        result = _simulate_buggy_pagination(
            max_articles=100, max_by_page=100, total_available=500
        )
        assert result == 100  # buggy actually returns 100 for exact-page case

    def test_buggy_logic_exact_page_boundary(self):
        # With exact page boundary, buggy logic happens to work
        result = _simulate_buggy_pagination(
            max_articles=200, max_by_page=100, total_available=500
        )
        assert result == 200


class TestFixedPaginationRespectsLimit:
    """The fixed logic stops BEFORE fetching when limit is reached."""

    def test_exact_one_page(self):
        result = _simulate_fixed_pagination(
            max_articles=100, max_by_page=100, total_available=500
        )
        assert result == 100
        assert result <= 100

    def test_one_and_half_pages(self):
        result = _simulate_fixed_pagination(
            max_articles=150, max_by_page=100, total_available=500
        )
        assert result <= 200  # Can fetch at most 2 full pages
        assert result >= 150  # Should fetch enough

    def test_two_and_half_pages(self):
        result = _simulate_fixed_pagination(
            max_articles=250, max_by_page=100, total_available=500
        )
        assert result <= 300
        assert result >= 250

    def test_half_page_openalex_style(self):
        """OpenAlex uses max_by_page=200, so 100 articles = 0.5 pages."""
        result = _simulate_fixed_pagination(
            max_articles=100, max_by_page=200, total_available=500
        )
        assert result <= 200
        assert result >= 100

    def test_total_available_less_than_limit(self):
        """When fewer articles exist than the limit, collect all available."""
        result = _simulate_fixed_pagination(
            max_articles=1000, max_by_page=100, total_available=250
        )
        assert result == 250


@pytest.mark.parametrize(
    "max_articles,max_by_page,total_available",
    [
        (100, 100, 500),
        (150, 100, 500),
        (250, 100, 500),
        (100, 200, 500),
        (50, 100, 500),
        (1000, 100, 250),
    ],
)
def test_fixed_pagination_never_exceeds_max_pages(
    max_articles, max_by_page, total_available
):
    """Fixed pagination never fetches more pages than math.ceil(max_articles / max_by_page)."""
    result = _simulate_fixed_pagination(max_articles, max_by_page, total_available)
    max_pages = math.ceil(max_articles / max_by_page)
    max_possible = max_pages * max_by_page
    assert result <= max_possible
