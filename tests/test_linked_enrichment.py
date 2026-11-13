"""Crossref, Linked Papers With Code and ORKG enrichment (HTTP mocked)."""

import threading

import pandas as pd
import pytest

from scilex import linked_enrichment as le


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
        self.ok = status < 400

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not self.ok:
            import requests

            raise requests.HTTPError(str(self.status_code))


class Session:
    """Answers by URL fragment; records the calls."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _answer(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for fragment, payload in self.routes.items():
            if fragment in url:
                return payload(url, kwargs) if callable(payload) else payload
        return Response({}, 404)

    def get(self, url, **kwargs):
        return self._answer(url, **kwargs)

    def post(self, url, **kwargs):
        return self._answer(url, **kwargs)


def _papers():
    return pd.DataFrame(
        {
            "title": ["BERT", "Unknown paper"],
            "DOI": ["10.18653/v1/N19-1423", "10.1/none"],
            "url": ["https://arxiv.org/abs/1810.04805v2", "NA"],
            "abstract": ["NA", "kept"],
            "pages": ["NA", "NA"],
        }
    )


def test_arxiv_id_from_doi_url_or_eprint():
    assert le.arxiv_id({"DOI": "10.48550/arXiv.1912.09582"}) == "1912.09582"
    assert (
        le.arxiv_id({"url": "https://arxiv.org/pdf/1810.04805v2.pdf"}) == "1810.04805"
    )
    assert le.arxiv_id({"eprint": "2210.12714"}) == "2210.12714"
    assert le.arxiv_id({"url": "https://example.org/1234.5678"}) is None


def test_crossref_fills_only_empty_fields_and_caches(tmp_path):
    record = {
        "message": {
            "abstract": "<jats:p>Deep <jats:italic>bidirectional</jats:italic></jats:p>",
            "page": "4171-4186",
            "container-title": ["NAACL"],
            "type": "proceedings-article",
            "is-referenced-by-count": 11691,
            "issued": {"date-parts": [[2019, 6]]},
            "funder": [{"name": "NSF"}],
        }
    }
    session = Session({"n19-1423": Response(record)})
    data = _papers()
    report = le.enrich_crossref(data, tmp_path / "c.json", session=session)
    assert (report.looked_up, report.found) == (2, 1)
    assert data.loc[0, "abstract"] == "Deep bidirectional"
    assert data.loc[0, "pages"] == "4171-4186"
    assert data.loc[0, "date"] == "2019-06"
    assert data.loc[0, "crossref_cited_by"] == "11691"
    assert data.loc[0, "crossref_funders"] == "NSF"
    assert data.loc[1, "abstract"] == "kept"  # never overwritten
    # Second run: answered from the cache, no request.
    session.calls.clear()
    le.enrich_crossref(_papers(), tmp_path / "c.json", session=session)
    assert session.calls == []


def test_lpwc_lookup_by_arxiv_then_title(tmp_path):
    def sparql(url, kwargs):
        query = kwargs["data"]["query"]
        key = "1810.04805" if "hasArXivId" in query else "Unknown paper"
        paper = "https://linkedpaperswithcode.com/paper/x" + (
            "" if "hasArXivId" in query else "2"
        )
        rows = [
            {
                "key": {"value": key},
                "paper": {"value": paper},
                "p": {"value": "https://linkedpaperswithcode.com/property/hasTask"},
                "o": {"value": "https://linkedpaperswithcode.com/task/ner"},
                "label": {"value": "Named Entity Recognition"},
            },
            {
                "key": {"value": key},
                "paper": {"value": paper},
                "p": {
                    "value": "https://linkedpaperswithcode.com/property/hasOfficialRepository"
                },
                "o": {
                    "value": "https://linkedpaperswithcode.com/repository/github.com/a/b"
                },
            },
        ]
        return Response({"results": {"bindings": rows}})

    session = Session({"linkedpaperswithcode": sparql})
    data = _papers()
    report = le.enrich_lpwc(data, tmp_path / "l.json", session=session)
    assert report.found == 2
    assert data.loc[0, "lpwc_tasks"] == "Named Entity Recognition"
    assert data.loc[0, "lpwc_repositories"] == "github.com/a/b"
    assert data.loc[1, "lpwc_paper"].endswith("/x2")


def test_orkg_paper_fields_and_problems(tmp_path):
    paper = {
        "content": [
            {
                "id": "R1",
                "research_fields": [{"label": "NLP"}],
                "contributions": [{"id": "C1"}],
            }
        ]
    }
    statements = {"content": [{"object": {"label": "Word Embeddings"}}]}
    session = Session(
        {
            "/papers": lambda url, kw: Response(
                paper
                if kw["params"].get("doi") == "10.18653/v1/n19-1423"
                else {"content": []}
            ),
            "/statements": Response(statements),
        }
    )
    data = _papers()
    report = le.enrich_orkg(data, tmp_path / "o.json", session=session)
    assert report.found == 1
    assert data.loc[0, "orkg_paper"] == "https://orkg.org/paper/R1"
    assert data.loc[0, "orkg_research_problems"] == "Word Embeddings"
    assert data.loc[1, "orkg_paper"] == "NA"


def test_row_filter_and_cancel(tmp_path):
    session = Session({})
    data = _papers()
    report = le.enrich_crossref(
        data, tmp_path / "c.json", session=session, row_filter=lambda d: d.iloc[1:]
    )
    assert report.looked_up == 1 and len(session.calls) == 1
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(le.Cancelled):
        le.enrich_orkg(_papers(), tmp_path / "o.json", session=session, cancel=cancel)


# ---------------------------------------------------------------------------
# GitHub licences
# ---------------------------------------------------------------------------


class _Headed(Response):
    def __init__(self, payload, status=200, headers=None):
        super().__init__(payload, status)
        self.headers = headers or {}


def test_github_repositories_from_every_code_column():
    row = {
        "github_repo": "https://github.com/google-research/bert.git",
        "lpwc_repositories": "github.com/google-research/bert;github.com/a/b",
        "pwc_repository": "NA",
    }
    assert le.github_repositories(row) == ["google-research/bert", "a/b"]
    assert le.github_repositories({"github_repo": "https://gitlab.com/x/y"}) == []


def test_github_licence_only_for_papers_without_one(tmp_path):
    session = Session(
        {
            "repos/a/b": _Headed(
                {"license": {"spdx_id": "MIT"}, "html_url": "https://github.com/a/b"}
            ),
            "repos/c/gone": _Headed({}, 404),
            "repos/c/other": _Headed(
                {"license": {"spdx_id": "NOASSERTION", "name": "Other"}}
            ),
        }
    )
    data = pd.DataFrame(
        {
            "title": ["A", "B", "C", "D"],
            "github_repo": [
                "https://github.com/a/b",
                "https://github.com/x/y",
                "https://github.com/c/gone;https://github.com/c/other",
                "NA",
            ],
            "code_license": ["NA", "Apache-2.0", "NA", "NA"],
        }
    )
    report = le.enrich_github(data, tmp_path / "g.json", session=session)
    assert list(data["code_license"]) == ["MIT", "Apache-2.0", "Other", "NA"]
    assert data.loc[0, "code_repository"] == "https://github.com/a/b"
    assert (report.found, report.kept, report.looked_up) == (2, 1, 2)
    assert not any("x/y" in url for url, _ in session.calls)  # kept: not asked


def test_github_rate_limit_stops_and_says_so(tmp_path):
    session = Session({"repos/": _Headed({}, 403, {"X-RateLimit-Remaining": "0"})})
    data = pd.DataFrame({"github_repo": ["https://github.com/a/b"]})
    report = le.enrich_github(data, tmp_path / "g.json", session=session)
    assert report.rate_limited and report.failed == 1
    assert "token" in report.message()


# ---------------------------------------------------------------------------
# Zenodo
# ---------------------------------------------------------------------------


def _zenodo_record(rid, kind, licence, size=2_000_000):
    return {
        "id": rid,
        "doi": f"10.5281/zenodo.{rid}",
        "links": {"html": f"https://zenodo.org/records/{rid}"},
        "metadata": {"license": {"id": licence}, "resource_type": {"type": kind}},
        "files": [{"size": size}],
        "stats": {"unique_downloads": 7},
    }


def test_zenodo_ids_from_doi_url_and_abstract():
    row = {
        "DOI": "10.5281/zenodo.123",
        "abstract": "Data at https://zenodo.org/records/456 and zenodo.org/record/123",
    }
    assert le.zenodo_ids(row) == ["123", "456"]


def test_zenodo_linked_and_related_records(tmp_path):
    def search(url, kwargs):
        assert "10.1/data" in kwargs["params"]["q"]
        return Response({"hits": {"hits": [_zenodo_record(9, "software", "mit")]}})

    session = Session(
        {
            "/records/456": Response(_zenodo_record(456, "dataset", "cc-by-4.0")),
            "/records?": search,
            "api/records": search,
        }
    )
    data = pd.DataFrame(
        {
            "title": ["Dataset paper", "Already done"],
            "DOI": ["10.1/data", "10.1/done"],
            "abstract": ["Available at https://zenodo.org/records/456", "NA"],
            "zenodo_records": ["NA", "https://zenodo.org/records/1"],
        }
    )
    report = le.enrich_zenodo(data, tmp_path / "z.json", session=session)
    assert data.loc[0, "zenodo_license"] == "cc-by-4.0;mit"
    assert data.loc[0, "zenodo_types"] == "dataset;software"
    assert data.loc[0, "zenodo_size"] == "4.0 MB"
    assert data.loc[0, "zenodo_downloads"] == "14"
    assert data.loc[0, "code_license"] == "mit"  # from the software record
    assert data.loc[1, "zenodo_records"] == "https://zenodo.org/records/1"
    assert (report.found, report.kept) == (1, 1)
    assert not any("10.1/done" in str(kw) for _, kw in session.calls)
