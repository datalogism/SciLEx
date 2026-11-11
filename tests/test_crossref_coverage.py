"""Live coverage comparison: CrossRef vs OpenCitations.

Compares hit rate, speed, and citation count agreement on real DOIs
from an existing aggregated collection.

Run with: uv run python -m pytest tests/test_crossref_coverage.py -m live -s
"""

import random
import time

import pytest

from scilex.constants import is_valid

# Mark all tests in this module as 'live' (skipped by default)
pytestmark = pytest.mark.live


@pytest.fixture
def sample_dois():
    """Load 100 random valid DOIs from the largest existing collection."""
    import pandas as pd

    csv_path = "output/collection_2026_01_13/aggregated_results.csv"
    try:
        df = pd.read_csv(csv_path, sep=";", on_bad_lines="skip")
    except FileNotFoundError:
        pytest.skip(f"Collection CSV not found at {csv_path}")

    valid_dois = [str(d) for d in df["DOI"].dropna().tolist() if is_valid(str(d))]
    if len(valid_dois) < 10:
        pytest.skip(f"Too few valid DOIs ({len(valid_dois)})")

    return random.sample(valid_dois, min(100, len(valid_dois)))


def test_crossref_vs_opencitations_coverage(sample_dois):
    """Compare CrossRef and OpenCitations on real DOIs."""
    from scilex.citations.citations_tools import (
        CROSSREF_BATCH_SIZE,
        getCitations,
        getCrossRefCitationsBatch,
    )

    # CrossRef batch (should be fast: ~5 requests for 100 DOIs)
    cr_start = time.time()
    cr_results = {}
    for i in range(0, len(sample_dois), CROSSREF_BATCH_SIZE):
        chunk = sample_dois[i : i + CROSSREF_BATCH_SIZE]
        try:
            batch = getCrossRefCitationsBatch.__wrapped__.__wrapped__.__wrapped__(chunk)
            cr_results.update(batch)
        except Exception as e:
            print(f"  CrossRef batch error: {e}")
    cr_time = time.time() - cr_start

    # OpenCitations per-DOI (slow: ~100 requests at 1 req/sec)
    oc_start = time.time()
    oc_results = {}
    for doi in sample_dois:
        try:
            ok, resp, _ = getCitations(doi)
            if ok and resp is not None:
                oc_results[doi.lower()] = len(resp.json())
        except Exception:
            pass
    oc_time = time.time() - oc_start

    # Report
    cr_hits = len(cr_results)
    oc_hits = len(oc_results)
    both = set(cr_results) & set(oc_results)
    cr_only = set(cr_results) - set(oc_results)
    oc_only = set(oc_results) - set(cr_results)

    print(f"\n{'=' * 60}")
    print(f"CrossRef vs OpenCitations — {len(sample_dois)} DOIs")
    print(f"{'=' * 60}")
    print(
        f"CrossRef:      {cr_hits}/{len(sample_dois)} hits "
        f"({cr_hits / len(sample_dois) * 100:.0f}%) in {cr_time:.1f}s"
    )
    print(
        f"OpenCitations: {oc_hits}/{len(sample_dois)} hits "
        f"({oc_hits / len(sample_dois) * 100:.0f}%) in {oc_time:.1f}s"
    )
    print(f"Both found:    {len(both)}")
    print(f"CR only:       {len(cr_only)}")
    print(f"OC only:       {len(oc_only)}")
    if cr_time > 0:
        print(f"Speed ratio:   {oc_time / cr_time:.0f}x faster (CrossRef)")

    # Citation count comparison for shared DOIs
    if both:
        diffs = [abs(cr_results[d][0] - oc_results[d]) for d in both]
        avg_diff = sum(diffs) / len(diffs)
        print(f"Avg count diff (shared): {avg_diff:.1f}")

    # CrossRef should cover at least 70% as many DOIs as OpenCitations
    # (coverage varies by sample; CrossRef has ~80% hit rate on average)
    if oc_hits > 0:
        assert cr_hits >= oc_hits * 0.7, (
            f"CrossRef coverage too low: {cr_hits} vs OC {oc_hits}"
        )
