"""Mappings from BibTeX entry types and fields to RDF ontology terms.

Uses BIBO (Bibliographic Ontology), DCTERMS, SCHEMA, and SCILEX namespaces.
"""

from rdflib.namespace import DCTERMS

from .namespaces import BIBO, SCHEMA, SCILEX

# Maps BibTeX entry type strings to BIBO classes.
#
# Note: bibo:AcademicArticle is used for both journal articles and conference
# papers.  For inproceedings, bibo:Proceedings is the *container* and the paper
# itself is a bibo:AcademicArticle linked via dcterms:isPartOf.
ENTRY_TYPE_MAP: dict[str, object] = {
    "article": BIBO.AcademicArticle,
    "book": BIBO.Book,
    "booklet": BIBO.Book,
    "inbook": BIBO.BookSection,
    "incollection": BIBO.BookSection,
    "inproceedings": BIBO.AcademicArticle,  # conference paper; bibo:Proceedings is the container
    "conference": BIBO.AcademicArticle,
    "manual": BIBO.Manual,
    "mastersthesis": BIBO.Thesis,
    "phdthesis": BIBO.Thesis,
    "proceedings": BIBO.Proceedings,
    "techreport": BIBO.Report,
    "unpublished": BIBO.Manuscript,
    "misc": BIBO.Document,
}

# Maps BibTeX field names to (predicate, value_type, xsd_datatype_or_None) tuples.
#
# value_type is one of:
#   "literal"      — plain or typed RDF literal
#   "uri"          — cast to URIRef; ignored if value does not start with http/https
#   "keyword_list" — split on comma/semicolon and emit one Literal per keyword
#   "page_range"   — emit bibo:pages Literal + bibo:pageStart/bibo:pageEnd integers
#
# year, author, editor, publisher, journal, and booktitle are handled
# separately in converter.py and are intentionally absent here.
FIELD_MAP: dict[str, tuple] = {
    "title": (DCTERMS.title, "literal", None),
    "abstract": (DCTERMS.abstract, "literal", None),
    "doi": (BIBO.doi, "literal", None),
    "url": (SCHEMA.url, "uri", None),
    "file": (SCHEMA.contentUrl, "uri", None),
    "volume": (BIBO.volume, "literal", None),
    "number": (BIBO.number, "literal", None),
    "pages": (BIBO.pages, "page_range", None),
    "isbn": (BIBO.isbn, "literal", None),
    "issn": (BIBO.issn, "literal", None),
    "series": (DCTERMS.isPartOf, "literal", None),
    "edition": (BIBO.edition, "literal", None),
    "note": (DCTERMS.description, "literal", None),
    "keywords": (DCTERMS.subject, "keyword_list", None),
    "language": (DCTERMS.language, "literal", None),
    "copyright": (DCTERMS.rights, "literal", None),
    "eprint": (DCTERMS.identifier, "literal", None),
    "archiveprefix": (SCILEX.collectedFrom, "literal", None),
    "howpublished": (SCHEMA.codeRepository, "uri", None),
    "citationcount": (SCHEMA.citationCount, "literal", "xsd:integer"),
    "relevancescore": (SCILEX.relevanceScore, "literal", "xsd:decimal"),
    # --- Papers with Code enrichment fields (hfurl kept for old .bib files) ---
    "task": (SCILEX.task, "literal", None),
    "ptm": (SCILEX.pretrainedModel, "literal", None),
    "archi": (SCILEX.architecture, "literal", None),
    "hfdataset": (SCILEX.usesDataset, "keyword_list", None),
    "framework": (SCILEX.framework, "literal", None),
    "githubstars": (SCILEX.githubStars, "literal", "xsd:integer"),
    "citingdatasets": (SCILEX.citedByDataset, "keyword_list", None),
    "pwcurl": (SCILEX.papersWithCodeUrl, "uri", None),
    "hfurl": (SCILEX.huggingFaceUrl, "uri", None),
}

__all__ = ["BIBO", "DCTERMS", "SCHEMA", "SCILEX", "ENTRY_TYPE_MAP", "FIELD_MAP"]
