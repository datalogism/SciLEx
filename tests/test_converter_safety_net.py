"""Safety net for the ``*toZoteroFormat`` converters.

Two families of tests:

* robustness: every converter must survive an empty row and a row whose fields
  are all ``None`` / ``""`` and still return the full set of base keys;
* golden: for one realistic row per API the whole output dict (values *and*
  key order, since key order is the downstream CSV column order) is pinned.
"""

import json
from pathlib import Path

import pytest

from scilex.constants import MISSING_VALUE
from scilex.crawlers.aggregate import (
    FORMAT_CONVERTERS,
    IstextoZoteroFormat,
    OpenAlextoZoteroFormat,
    PubMedCentraltoZoteroFormat,
    PubMedtoZoteroFormat,
    SpringertoZoteroFormat,
)

BASE_KEYS = [
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
]

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "converter_golden.json"
GOLDEN = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

# itemType is never missing: fallback is "Manuscript" except where a converter
# has a documented default.
DEFAULT_ITEM_TYPE = {
    "Arxiv": "preprint",
    "BioRxiv": "preprint",
    "PubMed": "journalArticle",
    "PubMedCentral": "journalArticle",
    "ORKG": "journalArticle",
    # OpenAIRE only sets a type when the payload carries a resourcetype.
    "OpenAIRE": MISSING_VALUE,
}
FORCED_VALUES = {
    "Arxiv": {"publisher": "arXiv", "rights": "open_access"},
    "BioRxiv": {"publisher": "bioRxiv", "rights": "open_access", "language": "en"},
    "HAL": {"rights": "open_access"},
    "PubMedCentral": {"rights": "open-access"},
}


def _blank_value_row(api_name: str) -> dict:
    """Return a row with the same fields as the golden input, all blanked."""
    return {key: None for key in GOLDEN[api_name]["input"]}


def _assert_all_base_keys_missing(api_name: str, result: dict) -> None:
    assert [k for k in result if k in BASE_KEYS] == [
        k for k in BASE_KEYS if k in result
    ]
    assert set(BASE_KEYS) <= set(result)
    forced = FORCED_VALUES.get(api_name, {})
    for key in BASE_KEYS:
        if key == "itemType":
            assert result[key] == DEFAULT_ITEM_TYPE.get(api_name, "Manuscript")
        elif key == "archive":
            assert result[key] not in ("", None)
        elif key in forced:
            assert result[key] == forced[key]
        else:
            assert result[key] == MISSING_VALUE, key


@pytest.mark.parametrize("api_name", sorted(FORMAT_CONVERTERS))
def test_empty_row_does_not_raise(api_name):
    """An empty dict yields a full record of MISSING_VALUE."""
    result = FORMAT_CONVERTERS[api_name]({})
    _assert_all_base_keys_missing(api_name, result)


@pytest.mark.parametrize("api_name", sorted(FORMAT_CONVERTERS))
def test_none_fields_do_not_raise(api_name):
    """A row whose fields are all None yields a full record of MISSING_VALUE."""
    result = FORMAT_CONVERTERS[api_name](_blank_value_row(api_name))
    _assert_all_base_keys_missing(api_name, result)


@pytest.mark.parametrize("api_name", sorted(FORMAT_CONVERTERS))
def test_empty_string_fields_do_not_raise(api_name):
    """A row whose fields are all empty strings yields a full record."""
    row = {key: "" for key in GOLDEN[api_name]["input"]}
    result = FORMAT_CONVERTERS[api_name](row)
    _assert_all_base_keys_missing(api_name, result)


@pytest.mark.parametrize("api_name", sorted(GOLDEN))
def test_golden_output(api_name):
    """The full output (values and key order) for a realistic row is pinned."""
    entry = GOLDEN[api_name]
    result = FORMAT_CONVERTERS[api_name](entry["input"])
    assert result == entry["expected"]
    assert list(result) == list(entry["expected"])


def test_golden_covers_every_converter():
    """Every registered converter has a golden fixture."""
    assert set(GOLDEN) == set(FORMAT_CONVERTERS)


@pytest.mark.parametrize(
    "converter", [PubMedtoZoteroFormat, PubMedCentraltoZoteroFormat]
)
def test_pubmed_family_cleans_doi_url_prefix(converter):
    """PubMed and PMC strip the doi.org prefix like every other converter."""
    result = converter({"doi": "https://doi.org/10.1000/Y", "pmid": "1"})
    assert result["DOI"] == "10.1000/Y"


def test_istex_genre_as_plain_string_is_mapped():
    """A genre given as a str maps like a one-element list."""
    assert IstextoZoteroFormat({"genre": "conference"})["itemType"] == "conferencePaper"
    assert (
        IstextoZoteroFormat({"genre": ["conference"]})["itemType"] == "conferencePaper"
    )


def test_istex_multiple_genres_stay_unmapped():
    """Several genres are ambiguous and fall back to Manuscript (unchanged)."""
    result = IstextoZoteroFormat({"genre": ["article", "book-chapter"]})
    assert result["itemType"] == "Manuscript"


def test_integer_page_numbers_do_not_raise():
    """Pages given as ints are joined instead of raising TypeError."""
    openalex = OpenAlextoZoteroFormat({"biblio": {"first_page": 10, "last_page": 20}})
    springer = SpringertoZoteroFormat({"startingPage": 1, "endingPage": 9})
    assert openalex["pages"] == "10-20"
    assert springer["pages"] == "1-9"
