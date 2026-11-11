#!/usr/bin/env python3
"""
Created on Fri Feb 10 10:57:49 2023

@author: cringwal
         aollagnier

@version: 1.0.1
"""

import contextlib

import pandas as pd

from scilex.constants import MISSING_VALUE, is_valid, strip_doi_prefix
from scilex.crawlers.converter_utils import (
    dig,
    fill_record,
    first_of,
    first_valid,
    get_valid,
    item_type_from_text,
    join_authors,
    join_values,
    map_item_type,
    new_record,
    page_range,
    valid_or_none,
)

_SS_SINGLE_TYPE_TO_ITEM_TYPE = {
    "JournalArticle": "journalArticle",
    "Conference": "conferencePaper",
    "Conferences": "conferencePaper",
    "Book": "book",
}
# When several types are listed, the first one found in this order wins.
_SS_MULTI_TYPE_PRIORITY = (
    ("Book", "book"),
    ("Conference", "conferencePaper"),
    ("JournalArticle", "journalArticle"),
)
_ISTEX_GENRE_TO_ITEM_TYPE = {
    "research-article": "journalArticle",
    "article": "journalArticle",
    "conference": "conferencePaper",
    "book-chapter": "bookSection",
}
_DBLP_TYPE_TO_ITEM_TYPE = {
    "Journal Articles": "journalArticle",
    "Conference and Workshop Papers": "conferencePaper",
    "Informal Publications": "Manuscript",
    "Informal and Other Publications": "Manuscript",
}
_OPENALEX_TYPE_TO_ITEM_TYPE = {
    "journal-article": "journalArticle",
    "article": "journalArticle",
    "book": "book",
    "book-chapter": "bookSection",
    "proceedings-article": "conferencePaper",
    # Other OpenAlex work types used to fall back to "Manuscript".
    "preprint": "preprint",
    "posted-content": "preprint",
    "review": "journalArticle",  # review articles, published in journals
    "dissertation": "thesis",
    "report": "report",
}
_IEEE_CONTENT_TYPE_TO_ITEM_TYPE = {
    "Journals": "journalArticle",
    "Conferences": "conferencePaper",
}
# Springer and Elsevier describe the type in free text: first pattern found wins.
_SPRINGER_TYPE_PATTERNS = (
    ("Conference", "conferencePaper"),
    ("Article", "journalArticle"),
    ("Chapter", "bookSection"),
)
_ELSEVIER_TYPE_PATTERNS = _SPRINGER_TYPE_PATTERNS
_PUBMED_TYPE_TO_ITEM_TYPE = {
    "Journal Article": "journalArticle",
    "Review": "journalArticle",
    "Book": "book",
    "Book Chapter": "bookSection",
}
_OPENAIRE_TYPE_TO_ITEM_TYPE = {
    "Article": "journalArticle",
    "publication": "journalArticle",  # OpenAIRE generic type
    "Conference object": "conferencePaper",
    "Book": "book",
    "Book part": "bookSection",
    "Preprint": "preprint",
}
_HAL_DOC_TYPE_TO_ITEM_TYPE = {
    "ART": "journalArticle",
    "COMM": "conferencePaper",
    "PROCEEDINGS": "conferencePaper",
    "UNDEFINED": "preprint",  # HAL label: "Preprint, working paper"
    "OUV": "book",
    "COUV": "bookSection",
    "Informal Publications": "Manuscript",
}


def safe_get(obj, key, default=None):
    """Safely get a value from a dictionary-like object, filtering out empty strings."""
    if isinstance(obj, dict) and key in obj and obj[key] != "":
        return obj[key]
    return default


def clean_doi(doi_value):
    """Strip the doi.org URL prefix from a DOI, keeping its case.

    Args:
        doi_value: DOI string (may be URL-formatted or clean)

    Returns:
        Bare DOI string, or MISSING_VALUE if invalid
    """
    return strip_doi_prefix(doi_value) or MISSING_VALUE


# Field importance weights for the metadata quality score.
_CRITICAL_QUALITY_FIELDS = frozenset({"DOI", "title", "authors", "date"})
_IMPORTANT_QUALITY_FIELDS = frozenset(
    {"abstract", "journalAbbreviation", "volume", "issue", "publisher"}
)


def _quality_weight(column: str) -> int:
    """Return 5 for critical fields, 3 for important ones, 1 for the rest."""
    if column in _CRITICAL_QUALITY_FIELDS:
        return 5
    if column in _IMPORTANT_QUALITY_FIELDS:
        return 3
    return 1


def getquality(df_row, column_names):
    """Calculate quality score based on weighted field importance.

    Field importance weights:
    - Critical fields (DOI, title, authors, date): 5 points each
    - Important fields (abstract, journal, volume, issue, publisher): 3 points each
    - Nice-to-have fields (pages, rights, language, url, etc.): 1 point each

    Special rules:
    - Bonus for having both volume and issue (+1 point)
    """
    valid_columns = {col for col in column_names if is_valid(df_row.get(col))}
    quality = sum(_quality_weight(col) for col in valid_columns)
    if {"volume", "issue"} <= valid_columns:
        quality += 1  # Bonus for complete bibliographic info
    return quality


def quality_scores(df: pd.DataFrame) -> pd.Series:
    """Vectorized ``getquality`` over every row and column of ``df``.

    Args:
        df: Aggregated papers.

    Returns:
        Integer quality score per row, aligned on ``df.index``.
    """
    valid = df.apply(lambda column: column.map(is_valid)).astype(bool)
    weights = pd.Series({col: _quality_weight(col) for col in df.columns}, dtype=int)
    scores = valid.mul(weights, axis=1).sum(axis=1)
    if "volume" in valid.columns and "issue" in valid.columns:
        scores += (valid["volume"] & valid["issue"]).astype(int)
    return scores.astype(int)


def _apply_semantic_scholar_venue(record, venue):
    """Set itemType and journal/conference name from a Semantic Scholar venue dict."""
    venue_type = get_valid(venue, "type")
    venue_name = get_valid(venue, "name")
    if venue_type == "journal":
        record["itemType"] = "journalArticle"
        fill_record(record, journalAbbreviation=venue_name)
    elif venue_type == "conference":
        record["itemType"] = "conferencePaper"
        fill_record(record, conferenceName=venue_name)


def _semantic_scholar_item_type(publication_types):
    """Pick one Zotero itemType from Semantic Scholar's publicationTypes list."""
    if not isinstance(publication_types, list):
        return MISSING_VALUE
    if len(publication_types) == 1:
        return map_item_type(
            publication_types[0], _SS_SINGLE_TYPE_TO_ITEM_TYPE, MISSING_VALUE
        )
    for publication_type, item_type in _SS_MULTI_TYPE_PRIORITY:
        if publication_type in publication_types:
            return item_type
    return MISSING_VALUE


def SemanticScholartoZoteroFormat(row):
    """Convert a Semantic Scholar paper to the internal Zotero-style record."""
    record = new_record(
        "SemanticScholar",
        item_type=_semantic_scholar_item_type(get_valid(row, "publicationTypes")),
    )

    # publicationVenue is richer than the legacy venue field, so it goes first.
    publication_venue = get_valid(row, "publicationVenue")
    fill_record(
        record,
        publisher=get_valid(publication_venue, "publisher"),
        serie=get_valid(publication_venue, "issn"),
    )
    _apply_semantic_scholar_venue(record, publication_venue)
    _apply_semantic_scholar_venue(record, get_valid(row, "venue"))

    journal = get_valid(row, "journal")
    if journal is not None:
        journal_pages = get_valid(journal, "pages")
        if journal_pages is not None and record["itemType"] == "book":
            record["itemType"] = "bookSection"
        if not is_valid(record["itemType"]):
            # Journal metadata without a known type (e.g. reviews): assume article.
            record["itemType"] = "journalArticle"
        fill_record(
            record,
            pages=journal_pages,
            journalAbbreviation=get_valid(journal, "name"),
            volume=get_valid(journal, "volume"),
        )

    if not is_valid(record["itemType"]):
        # Zotero rejects items without a type.
        record["itemType"] = "Manuscript"

    author_entries = get_valid(row, "authors")
    author_names = [
        get_valid(author, "name")
        for author in (author_entries if isinstance(author_entries, list) else [])
    ]
    fill_record(
        record,
        title=get_valid(row, "title"),
        abstract=get_valid(row, "abstract"),
        archiveID=get_valid(row, "paper_id"),
        date=get_valid(row, "publication_date"),
        url=get_valid(row, "url"),
        authors=join_authors(author_names),
    )
    record["DOI"] = clean_doi(get_valid(row, "DOI"))

    open_access_pdf = get_valid(row, "open_access_pdf")
    if open_access_pdf is not None:
        record["pdf_url"] = open_access_pdf
        record["rights"] = "open_access"

    # Citation data kept as fallback for the citation step (0 is a real value).
    fill_record(
        record,
        ss_citation_count=get_valid(row, "citationCount"),
        ss_reference_count=get_valid(row, "referenceCount"),
    )
    return record


def IstextoZoteroFormat(row):
    """Convert an Istex record to the internal Zotero-style record."""
    record = new_record("Istex")

    genre = get_valid(row, "genre")
    if isinstance(genre, list) and len(genre) != 1:
        # Several genres are ambiguous: leave the type to the default.
        genre = None
    record["itemType"] = map_item_type(
        first_of(genre), _ISTEX_GENRE_TO_ITEM_TYPE, MISSING_VALUE
    )

    author_entries = get_valid(row, "author")
    dois = get_valid(row, "doi")
    dois = dois if isinstance(dois, list) else [dois]
    host = get_valid(row, "host")
    pages = get_valid(host, "pages")
    series = get_valid(row, "series")
    publisher = first_of(get_valid(host, "publisherId")) or get_valid(host, "publisher")
    fill_record(
        record,
        title=get_valid(row, "title"),
        abstract=get_valid(row, "abstract"),
        archiveID=get_valid(row, "arkIstex"),
        date=get_valid(row, "publicationDate"),
        language=first_of(get_valid(row, "language")),
        serie=get_valid(series, "title"),
        volume=get_valid(host, "volume"),
        issue=get_valid(host, "issue"),
        journalAbbreviation=get_valid(host, "title"),
        publisher=publisher,
        url=get_valid(row, "url"),
        rights=dig(row, "accessCondition", "contentType") or None,
        authors=join_authors(
            [get_valid(a, "name") for a in author_entries]
            if isinstance(author_entries, list)
            else None
        ),
    )
    if dois[0] is not None:
        record["DOI"] = ";".join(clean_doi(doi) for doi in dois)
    if isinstance(pages, dict):
        record["pages"] = page_range(pages.get("first"), pages.get("last"))

    fulltext = get_valid(row, "fulltext")
    for entry in fulltext if isinstance(fulltext, list) else []:
        if get_valid(entry, "extension") == "pdf" and get_valid(entry, "uri"):
            record["pdf_url"] = entry["uri"]
            break

    if not is_valid(record["itemType"]):
        record["itemType"] = "Manuscript"
    return record


def ArxivtoZoteroFormat(row):
    """Convert an arXiv entry to the internal Zotero-style record."""
    # arXiv is always open access; an entry is a preprint unless a journal is given.
    record = new_record("Arxiv", item_type="preprint")
    record["rights"] = "open_access"
    record["publisher"] = "arXiv"

    fill_record(
        record,
        abstract=get_valid(row, "abstract"),
        title=get_valid(row, "title"),
        date=get_valid(row, "published"),
        authors=join_authors(get_valid(row, "authors")),
    )
    record["DOI"] = clean_doi(get_valid(row, "doi"))

    arxiv_id = get_valid(row, "id")
    if arxiv_id is not None:
        arxiv_id = str(arxiv_id)
        record["archiveID"] = arxiv_id
        if arxiv_id.startswith("http"):
            # e.g. https://arxiv.org/abs/2301.12345 or http://arxiv.org/abs/cs/0601078v1
            record["url"] = arxiv_id
            url_id = arxiv_id.rstrip("/")
            if "/abs/" in url_id:
                url_id = url_id.split("/abs/")[-1]
            elif "/pdf/" in url_id:
                url_id = url_id.split("/pdf/")[-1].replace(".pdf", "")
        else:
            url_id = arxiv_id.split("/")[-1]
            record["url"] = f"https://arxiv.org/abs/{url_id}"
        record["pdf_url"] = f"https://arxiv.org/pdf/{url_id}.pdf"

    categories = get_valid(row, "categories")
    if isinstance(categories, list):
        record["journalAbbreviation"] = ", ".join(categories)
    elif isinstance(categories, str):
        record["journalAbbreviation"] = categories

    journal = get_valid(row, "journal")
    if journal is not None:
        record["journalAbbreviation"] = journal
        record["itemType"] = "journalArticle"
    return record


def BioRxivtoZoteroFormat(row):
    """Convert a bioRxiv ``/details/`` entry to the internal Zotero-style record."""
    record = new_record("BioRxiv", item_type="preprint")
    record["rights"] = "open_access"
    record["language"] = "en"
    record["publisher"] = "bioRxiv"

    fill_record(
        record,
        title=get_valid(row, "title"),
        authors=get_valid(row, "authors"),  # already ';'-separated by the API
        abstract=get_valid(row, "abstract"),
        date=get_valid(row, "date"),
        journalAbbreviation=get_valid(row, "category"),
    )

    raw_doi = get_valid(row, "doi")
    if raw_doi is not None:
        doi = clean_doi(raw_doi)
        record["DOI"] = doi
        record["archiveID"] = doi
        record["url"] = f"https://www.biorxiv.org/content/{raw_doi}"
        version = get_valid(row, "version") or "1"
        record["pdf_url"] = (
            f"https://www.biorxiv.org/content/{raw_doi}v{version}.full.pdf"
        )

    # Published in a journal: upgrade the item type
    if get_valid(row, "published") is not None:
        record["itemType"] = "journalArticle"
    return record


def _dblp_author_names(authors_field):
    """Return author names from DBLP's single-dict or list `author` entry."""
    author_entries = dig(authors_field, "author")
    if isinstance(author_entries, dict):
        author_entries = [author_entries]
    if not isinstance(author_entries, list):
        return []
    return [get_valid(entry, "text") for entry in author_entries]


def DBLPtoZoteroFormat(row):
    """Convert a DBLP hit to the internal Zotero-style record."""
    info = get_valid(row, "info")
    if not isinstance(info, dict):
        info = {}
    record = new_record("DBLP")

    venue = get_valid(info, "venue")
    item_type = map_item_type(info.get("type"), _DBLP_TYPE_TO_ITEM_TYPE, "Manuscript")
    record["itemType"] = item_type
    fill_record(
        record,
        archiveID=get_valid(row, "@id"),
        title=get_valid(info, "title"),
        date=get_valid(info, "year"),
        authors=join_authors(_dblp_author_names(info.get("authors"))),
        pages=get_valid(info, "pages"),
        volume=get_valid(info, "volume"),
        issue=get_valid(info, "number"),
        publisher=get_valid(info, "publisher"),
        rights=get_valid(info, "access"),
        url=get_valid(info, "url"),
    )
    record["DOI"] = clean_doi(get_valid(info, "doi"))
    if item_type == "journalArticle":
        fill_record(record, journalAbbreviation=venue)
    elif item_type == "conferencePaper":
        fill_record(record, conferenceName=venue)
    return record


def HALtoZoteroFormat(row):
    """Convert a HAL document to the internal Zotero-style record."""
    doc_type = get_valid(row, "docType_s")
    item_type = map_item_type(doc_type, _HAL_DOC_TYPE_TO_ITEM_TYPE, "Manuscript")
    record = new_record("HAL", item_type=item_type)
    # HAL is open access by default.
    record["rights"] = "open_access"

    hal_id = get_valid(row, "halId_s")
    year = get_valid(row, "submittedDateY_i")
    pdf_candidates = get_valid(row, "files_s")
    pdf_url = next(
        (
            file_url
            for file_url in (pdf_candidates if isinstance(pdf_candidates, list) else [])
            if isinstance(file_url, str) and file_url.endswith(".pdf")
        ),
        None,
    )
    author_entries = get_valid(row, "authFullNameIdHal_fs")
    author_names = [
        entry.split("_FacetSep_")[0].strip()
        for entry in (author_entries if isinstance(author_entries, list) else [])
        if isinstance(entry, str)
    ]
    fill_record(
        record,
        archiveID=hal_id,
        title=first_of(get_valid(row, "title_s")),
        abstract=first_of(get_valid(row, "abstract_s")),
        serie=get_valid(row, "bookTitle_s"),
        conferenceName=get_valid(row, "conferenceTitle_s"),
        journalAbbreviation=get_valid(row, "journalTitle_t"),
        date=None if year is None else str(year),
        volume=get_valid(row, "volume_s"),
        issue=get_valid(row, "issue_s"),
        pages=get_valid(row, "page_s"),
        publisher=first_of(get_valid(row, "publisher_s")),
        url=None if hal_id is None else f"https://hal.science/{hal_id}",
        pdf_url=pdf_url,
        language=first_of(get_valid(row, "language_s")),
        authors=join_authors(author_names),
    )
    record["DOI"] = clean_doi(get_valid(row, "doiId_id"))
    if doc_type == "ART":
        fill_record(record, journalAbbreviation=get_valid(row, "venue"))
    return record


def reconstruct_abstract_from_inverted_index(inverted_index):
    """Reconstruct abstract text from OpenAlex's inverted index format.

    Args:
        inverted_index: Dictionary mapping words to their positions
                       e.g., {"word": [0, 5], "another": [1]}

    Returns:
        str: Reconstructed abstract text, or None if empty/invalid

    """
    if not inverted_index:
        return None

    try:
        # Find maximum position to size the word array
        max_position = max(max(positions) for positions in inverted_index.values())
        words = [""] * (max_position + 1)

        # Place each word at its positions
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word

        # Join words with spaces
        return " ".join(words)
    except (ValueError, TypeError, KeyError):
        # Handle malformed inverted index gracefully
        return None


def _openalex_urls(row):
    """Return (url, pdf_url): best OA location, then primary location, then DOI."""
    best_location = get_valid(row, "best_oa_location")
    if best_location is not None:
        pdf_url = get_valid(best_location, "pdf_url")
        landing_page = get_valid(best_location, "landing_page_url")
        return (landing_page if landing_page is not None else pdf_url), pdf_url

    primary_location = get_valid(row, "primary_location")
    if primary_location is not None:
        return (
            get_valid(primary_location, "landing_page_url"),
            get_valid(primary_location, "pdf_url"),
        )

    doi = get_valid(row, "doi")
    if isinstance(doi, str):
        if doi.startswith("http"):
            return doi, None
        if doi.startswith("10."):
            return f"https://doi.org/{doi}", None
    return None, None


def OpenAlextoZoteroFormat(row):
    """Convert an OpenAlex work to the internal Zotero-style record."""
    record = new_record(
        "OpenAlex",
        item_type=map_item_type(
            get_valid(row, "type"), _OPENALEX_TYPE_TO_ITEM_TYPE, MISSING_VALUE
        ),
    )

    url, pdf_url = _openalex_urls(row)
    open_access = get_valid(row, "open_access")
    rights = None
    if isinstance(open_access, dict) and "is_oa" in open_access:
        rights = "open_access" if open_access["is_oa"] else "restricted"

    authorships = get_valid(row, "authorships")
    author_names = [
        dig(authorship, "author", "display_name")
        for authorship in (authorships if isinstance(authorships, list) else [])
    ]

    biblio = get_valid(row, "biblio")
    # primary_location.source replaces the deprecated host_venue.
    source = dig(row, "primary_location", "source", default={})
    source_name = get_valid(source, "display_name")
    source_type = get_valid(source, "type")

    fill_record(
        record,
        archiveID=get_valid(row, "id"),
        DOI=clean_doi(get_valid(row, "doi")),
        title=get_valid(row, "title"),
        date=get_valid(row, "publication_date"),
        language=get_valid(row, "language"),
        url=url,
        pdf_url=pdf_url,
        abstract=reconstruct_abstract_from_inverted_index(
            get_valid(row, "abstract_inverted_index")
        ),
        rights=rights,
        authors=join_authors(author_names),
        volume=get_valid(biblio, "volume"),
        issue=get_valid(biblio, "issue"),
        pages=page_range(
            get_valid(biblio, "first_page"), get_valid(biblio, "last_page")
        ),
        publisher=get_valid(source, "host_organization_name"),
        serie=get_valid(source, "issn_l"),
    )

    if source_name is not None:
        if source_type == "conference":
            record["itemType"] = "conferencePaper"
            record["conferenceName"] = source_name
        elif source_type == "journal":
            record["itemType"] = "journalArticle"
            record["journalAbbreviation"] = source_name
        elif source_type == "repository" and not is_valid(
            record["journalAbbreviation"]
        ):
            # Preprint servers (arXiv, bioRxiv, medRxiv, ...).
            record["journalAbbreviation"] = source_name

    cited_by_count = get_valid(row, "cited_by_count")
    if cited_by_count is not None:
        with contextlib.suppress(TypeError, ValueError):
            record["oa_citation_count"] = int(cited_by_count)

    if not is_valid(record["itemType"]):
        record["itemType"] = "Manuscript"
    return record


def IEEEtoZoteroFormat(row):
    """Convert an IEEE Xplore article to the internal Zotero-style record."""
    record = new_record(
        "IEEE",
        item_type=map_item_type(
            get_valid(row, "content_type"),
            _IEEE_CONTENT_TYPE_TO_ITEM_TYPE,
            "Manuscript",
        ),
    )

    authors_field = get_valid(row, "authors")
    if isinstance(authors_field, dict):
        authors_field = authors_field.get("authors")
    author_names = [
        get_valid(author, "full_name")
        for author in (authors_field if isinstance(authors_field, list) else [])
    ]

    fill_record(
        record,
        archiveID=get_valid(row, "article_number"),
        date=first_valid(row, "publication_date", "publication_year"),
        title=get_valid(row, "title"),
        abstract=get_valid(row, "abstract"),
        url=get_valid(row, "html_url"),
        rights=get_valid(row, "access_type"),
        DOI=clean_doi(get_valid(row, "doi")),
        publisher=get_valid(row, "publisher"),
        volume=get_valid(row, "volume"),
        issue=get_valid(row, "issue"),
        journalAbbreviation=get_valid(row, "publication_title"),
        authors=join_authors(author_names),
        pages=page_range(get_valid(row, "start_page"), get_valid(row, "end_page")),
        pdf_url=get_valid(row, "pdf_url"),
    )
    return record


def _springer_urls(url_field):
    """Return (url, pdf_url) from Springer's list of URL objects (or plain string)."""
    if isinstance(url_field, str):
        return url_field, None
    if not isinstance(url_field, list):
        return None, None

    url = None
    pdf_url = None
    for url_object in url_field:
        if isinstance(url_object, dict):
            url_format = url_object.get("format")
            value = url_object.get("value")
            if url_format == "html" and value:
                url = value
            elif url_format == "pdf" and value:
                pdf_url = value
        elif isinstance(url_object, str) and url is None:
            url = url_object
    if url is None:
        # No html URL: fall back to the first available value.
        url = next(
            (
                get_valid(url_object, "value")
                for url_object in url_field
                if get_valid(url_object, "value") is not None
            ),
            None,
        )
    return url, pdf_url


def SpringertoZoteroFormat(row):
    """Convert a Springer record to the internal Zotero-style record."""
    record = new_record(
        "Springer",
        item_type=item_type_from_text(
            get_valid(row, "contentType"), _SPRINGER_TYPE_PATTERNS, "Manuscript"
        ),
    )

    url, pdf_url = _springer_urls(get_valid(row, "url"))
    creators = get_valid(row, "creators")
    author_names = [
        get_valid(creator, "creator")
        for creator in (creators if isinstance(creators, list) else [])
    ]

    fill_record(
        record,
        archiveID=get_valid(row, "identifier"),
        date=get_valid(row, "publicationDate"),
        title=get_valid(row, "title"),
        abstract=get_valid(row, "abstract"),
        url=url,
        pdf_url=pdf_url,
        rights=get_valid(row, "openaccess"),
        DOI=clean_doi(get_valid(row, "doi")),
        publisher=get_valid(row, "publisher"),
        volume=get_valid(row, "volume"),
        # Springer calls the issue "number".
        issue=first_valid(row, "number", "issue"),
        journalAbbreviation=get_valid(row, "publicationName"),
        authors=join_authors(author_names),
        pages=page_range(get_valid(row, "startingPage"), get_valid(row, "endingPage")),
    )
    return record


def ElseviertoZoteroFormat(row):
    """Convert an Elsevier (Scopus) entry to the internal Zotero-style record."""
    record = new_record(
        "Elsevier",
        item_type=item_type_from_text(
            get_valid(row, "subtypeDescription"), _ELSEVIER_TYPE_PATTERNS, "Manuscript"
        ),
    )
    fill_record(
        record,
        archiveID=get_valid(row, "source-id"),
        date=get_valid(row, "prism:coverDate"),
        title=get_valid(row, "dc:title"),
        abstract=get_valid(row, "dc:description"),
        url=get_valid(row, "prism:url"),
        rights=get_valid(row, "openaccess"),
        DOI=clean_doi(get_valid(row, "prism:doi")),
        publisher=get_valid(row, "publisher"),
        volume=get_valid(row, "prism:volume"),
        issue=get_valid(row, "prism:issueIdentifier"),
        journalAbbreviation=get_valid(row, "prism:publicationName"),
        authors=get_valid(row, "dc:creator"),
        pages=get_valid(row, "prism:pageRange"),
    )
    return record


def _ncbi_common_fields(row):
    """Fields shared by PubMed and PubMed Central collector rows."""
    return {
        "title": get_valid(row, "title"),
        "authors": join_authors(get_valid(row, "authors")),
        "abstract": get_valid(row, "abstract"),
        "DOI": clean_doi(get_valid(row, "doi")),
        "date": get_valid(row, "date"),
        "journalAbbreviation": get_valid(row, "journal"),
        "volume": get_valid(row, "volume"),
        "issue": get_valid(row, "issue"),
        "pages": get_valid(row, "pages"),
        "language": get_valid(row, "language"),
    }


def PubMedCentraltoZoteroFormat(row):
    """Convert PubMed Central (PMC) results to Zotero format.

    PMC provides open-access biomedical literature with comprehensive metadata.
    All PMC articles have full-text access and typically include complete
    bibliographic information.

    Args:
        row: Dictionary containing PMC article data from collector

    Returns:
        dict: Zotero-formatted article metadata
    """
    # Most PMC articles are journal articles; all of them are open access.
    record = new_record(
        "PubMedCentral", item_type="journalArticle", extra_keys=("tags",)
    )
    record["rights"] = "open-access"
    fill_record(
        record, publisher=get_valid(row, "publisher"), **_ncbi_common_fields(row)
    )

    pmc_id = get_valid(row, "pmc_id")
    pmid = get_valid(row, "pmid")
    if pmc_id is not None:
        record["archiveID"] = pmc_id
        if str(pmc_id).startswith("PMC"):
            record["url"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/"
            # PMC provides direct PDF access for all articles.
            record["pdf_url"] = (
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/"
            )
    elif pmid is not None:
        # No PMC id: fall back to the PMID.
        record["archiveID"] = pmid
        record["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return record


def PubMedtoZoteroFormat(row):
    """Convert PubMed results to Zotero format.

    PubMed provides comprehensive biomedical literature metadata (35M+ papers)
    including both open-access and paywalled content. When PMCID is available,
    PDF URLs are automatically generated for PMC open-access subset.

    Args:
        row: Dictionary containing PubMed article data from collector

    Returns:
        dict: Zotero-formatted article metadata
    """
    record = new_record(
        "PubMed",
        item_type=map_item_type(
            get_valid(row, "publication_type"),
            _PUBMED_TYPE_TO_ITEM_TYPE,
            "journalArticle",
        ),
        extra_keys=("tags",),
    )
    # Only open access when the article is in PMC.
    if get_valid(row, "pmcid") is not None:
        record["rights"] = "open-access"
    fill_record(record, **_ncbi_common_fields(row))

    pmid = get_valid(row, "pmid")
    if pmid is not None:
        record["archiveID"] = pmid
        record["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    # pdf_url is populated by the collector when a PMCID is present.
    fill_record(record, pdf_url=get_valid(row, "pdf_url"))

    # MeSH terms are exported as tags.
    mesh_terms = get_valid(row, "mesh_terms")
    if isinstance(mesh_terms, list):
        record["tags"] = join_values(mesh_terms)
    return record


def OpenAIREtoZoteroFormat(row):
    """Convert an OpenAIRE result to the internal Zotero-style record."""
    record = new_record("OpenAIRE")
    entity = dig(row, "metadata", "oaf:entity", "oaf:result")
    if not isinstance(entity, dict):
        return record

    creators = _as_list(entity.get("creator"))
    pids = _as_list(entity.get("pid"))
    doi_raw = next(
        (
            get_valid(pid, "$")
            for pid in pids
            if get_valid(pid, "@classid") == "doi" and get_valid(pid, "$")
        ),
        None,
    )
    description = entity.get("description")
    access_right = dig(entity, "bestaccessright", "@classname")
    resource_type = dig(entity, "resourcetype", "@classname")
    url = next(
        (
            url_value
            for instance in _as_list(dig(entity, "children", "instance"))
            if (url_value := get_valid(dig(instance, "webresource", "url"), "$"))
        ),
        None,
    )

    fill_record(
        record,
        title=get_valid(entity.get("title"), "$"),
        authors=join_authors([get_valid(creator, "$") for creator in creators]),
        date=get_valid(entity.get("dateofacceptance"), "$"),
        abstract=(
            get_valid(description, "$")
            if isinstance(description, dict)
            else get_valid(entity, "description")
        ),
        DOI=clean_doi(doi_raw),
        journalAbbreviation=get_valid(entity.get("journal"), "$"),
        language=get_valid(entity.get("language"), "@classid"),
        rights=(
            None
            if access_right is None
            else "open_access"
            if "Open" in access_right
            else "restricted"
        ),
        archiveID=valid_or_none(first_of(entity.get("originalId"))),
        url=url,
    )
    if resource_type is not None:
        record["itemType"] = map_item_type(
            resource_type, _OPENAIRE_TYPE_TO_ITEM_TYPE, "journalArticle"
        )
    return record


def _as_list(value):
    """Wrap a lone dict in a list (OpenAIRE returns dict for one item, list for many)."""
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def ORKGtoZoteroFormat(row):
    """Convert an ORKG paper to the internal Zotero-style record."""
    record = new_record("ORKG", item_type="journalArticle")

    orkg_id = get_valid(row, "id")
    publication_info = get_valid(row, "publication_info")
    if not isinstance(publication_info, dict):
        publication_info = {}
    published_year = get_valid(publication_info, "published_year")
    published_in = get_valid(publication_info, "published_in")
    if isinstance(published_in, dict):
        published_in = get_valid(published_in, "label")
    authors = get_valid(row, "authors")
    doi = first_of(dig(row, "identifiers", "doi"))

    fill_record(
        record,
        archiveID=orkg_id,
        title=get_valid(row, "title"),
        DOI=clean_doi(doi),
        date=None if published_year is None else str(published_year),
        journalAbbreviation=published_in if isinstance(published_in, str) else None,
        # Fall back to the ORKG paper page when no URL is given.
        url=get_valid(publication_info, "url")
        or (None if orkg_id is None else f"https://orkg.org/paper/{orkg_id}"),
        authors=join_authors(
            [get_valid(author, "name") for author in authors]
            if isinstance(authors, list)
            else None
        ),
    )
    return record


# ============================================================================
# FORMAT CONVERTERS REGISTRY
# ============================================================================

FORMAT_CONVERTERS = {
    "SemanticScholar": SemanticScholartoZoteroFormat,
    "OpenAlex": OpenAlextoZoteroFormat,
    "IEEE": IEEEtoZoteroFormat,
    "Elsevier": ElseviertoZoteroFormat,
    "Springer": SpringertoZoteroFormat,
    "HAL": HALtoZoteroFormat,
    "DBLP": DBLPtoZoteroFormat,
    "Istex": IstextoZoteroFormat,
    "Arxiv": ArxivtoZoteroFormat,
    "BioRxiv": BioRxivtoZoteroFormat,
    "PubMed": PubMedtoZoteroFormat,
    "PubMedCentral": PubMedCentraltoZoteroFormat,
    "OpenAIRE": OpenAIREtoZoteroFormat,
    "ORKG": ORKGtoZoteroFormat,
}
"""Maps API names to their format converter functions."""
