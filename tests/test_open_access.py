"""Unpaywall oa_type enrichment (HTTP mocked)."""

from unittest.mock import MagicMock

import pandas as pd

from scilex.pipeline import open_access
from scilex.pipeline.open_access import (
    enrich_with_unpaywall,
    fetch_oa_type,
    parse_oa_type,
)


def test_parse_oa_type():
    assert parse_oa_type({"oa_status": "Gold"}) == "gold"
    assert parse_oa_type({"oa_status": "weird"}) == "NA"
    assert parse_oa_type(None) == "NA"


def test_fetch_oa_type_request_and_404():
    session = MagicMock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = {"oa_status": "hybrid"}
    assert fetch_oa_type("10.1/a", "me@x.org", session=session) == "hybrid"
    assert session.get.call_args.kwargs["params"] == {"email": "me@x.org"}
    assert session.get.call_args.args[0].endswith("/10.1/a")
    session.get.return_value.status_code = 404
    assert fetch_oa_type("10.1/a", "me@x.org", session=session) == "NA"


def test_enrich_disabled_without_email():
    df = pd.DataFrame({"DOI": ["10.1/a"]})
    assert "oa_type" not in enrich_with_unpaywall(df, "")


def test_enrich_maps_by_doi(monkeypatch):
    monkeypatch.setattr(open_access, "MIN_SECONDS_BETWEEN_REQUESTS", 0)
    df = pd.DataFrame({"DOI": ["https://doi.org/10.1/A", "NA", "10.1/b"]})
    out = enrich_with_unpaywall(
        df, "me@x.org", fetch=lambda doi, email: {"10.1/a": "gold"}.get(doi, "closed")
    )
    assert list(out["oa_type"]) == ["gold", "NA", "closed"]
