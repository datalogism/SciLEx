"""Core BibTeX → RDF conversion logic."""

import re
import unicodedata
import urllib.parse

import bibtexparser
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, FOAF, RDF, XSD

from .mappings import ENTRY_TYPE_MAP, FIELD_MAP
from .namespaces import BIBO, OWL, PROV, SCHEMA, SCILEX

_MONTH_MAP: dict[str, str] = {
    "january": "01",
    "jan": "01",
    "february": "02",
    "feb": "02",
    "march": "03",
    "mar": "03",
    "april": "04",
    "apr": "04",
    "may": "05",
    "june": "06",
    "jun": "06",
    "july": "07",
    "jul": "07",
    "august": "08",
    "aug": "08",
    "september": "09",
    "sep": "09",
    "sept": "09",
    "october": "10",
    "oct": "10",
    "november": "11",
    "nov": "11",
    "december": "12",
    "dec": "12",
}


def _slug(text: str) -> str:
    """Return a URL-safe ASCII slug from *text*."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text).strip("-")


def _parse_author_name(raw: str) -> dict[str, str]:
    """Parse a single author name string into first/last components.

    Handles both "Last, First" and "First Last" formats.

    Args:
        raw: A raw author name string, e.g. "Doe, John" or "John Doe".

    Returns:
        A dict with keys ``first`` and ``last``.
    """
    raw = raw.strip()
    if "," in raw:
        parts = [p.strip() for p in raw.split(",", 1)]
        return {"last": parts[0], "first": parts[1]}
    parts = raw.rsplit(" ", 1)
    if len(parts) == 2:
        return {"first": parts[0], "last": parts[1]}
    return {"first": "", "last": raw}


def _person_uri(base_uri: str, name: dict[str, str]) -> URIRef:
    """Build a deterministic URI for a person from their name.

    Args:
        base_uri: The base URI prefix for locally-minted URIs.
        name: A dict with ``first`` and ``last`` keys.

    Returns:
        A URIRef for the person.
    """
    full = f"{name['first']}-{name['last']}" if name["first"] else name["last"]
    return URIRef(f"{base_uri}person/{_slug(full)}")


def _add_person(
    graph: Graph,
    base_uri: str,
    raw_name: str,
    predicate: URIRef,
    subject: URIRef,
) -> None:
    """Mint a FOAF.Person node and link it to *subject* via *predicate*.

    Args:
        graph: The RDF graph to add triples to.
        base_uri: Base URI for person nodes.
        raw_name: Raw name string (may contain "First Last" or "Last, First").
        predicate: The predicate linking subject to the person.
        subject: The bibliographic resource URI.
    """
    parsed = _parse_author_name(raw_name)
    person_uri = _person_uri(base_uri, parsed)
    graph.add((person_uri, RDF.type, FOAF.Person))
    if parsed["first"]:
        graph.add((person_uri, FOAF.firstName, Literal(parsed["first"])))
    graph.add((person_uri, FOAF.lastName, Literal(parsed["last"])))
    graph.add(
        (person_uri, FOAF.name, Literal(f"{parsed['first']} {parsed['last']}".strip()))
    )
    graph.add((subject, predicate, person_uri))


def _typed_literal(value: str, xsd_type: str | None) -> Literal:
    """Return a Literal with optional XSD datatype.

    Args:
        value: The string value to convert.
        xsd_type: One of ``"xsd:integer"``, ``"xsd:decimal"``, or ``None``
            for a plain string literal.  Invalid values fall back to a plain
            string literal rather than raising.

    Returns:
        An RDFLib :class:`~rdflib.Literal`.
    """
    if xsd_type == "xsd:integer":
        try:
            return Literal(int(value), datatype=XSD.integer)
        except ValueError:
            return Literal(value)
    if xsd_type == "xsd:decimal":
        try:
            return Literal(float(value), datatype=XSD.decimal)
        except ValueError:
            return Literal(value)
    return Literal(value)


def _add_page_range(graph: Graph, subject: URIRef, pages: str) -> None:
    """Emit ``bibo:pageStart`` and ``bibo:pageEnd`` from a page range string.

    Handles common separators: hyphen, en-dash (–), em-dash (—), and
    double-hyphen (--).  Single page numbers are emitted as ``bibo:pageStart``
    only.

    Args:
        graph: The RDF graph to add triples to.
        subject: The bibliographic resource URI.
        pages: Raw pages string, e.g. ``"123-145"`` or ``"123--145"``.
    """
    range_match = re.match(r"^\s*(\d+)\s*[-\u2013\u2014]{1,2}\s*(\d+)\s*$", pages)
    if range_match:
        graph.add(
            (
                subject,
                BIBO.pageStart,
                Literal(int(range_match.group(1)), datatype=XSD.integer),
            )
        )
        graph.add(
            (
                subject,
                BIBO.pageEnd,
                Literal(int(range_match.group(2)), datatype=XSD.integer),
            )
        )
    elif re.match(r"^\s*\d+\s*$", pages):
        graph.add(
            (subject, BIBO.pageStart, Literal(int(pages.strip()), datatype=XSD.integer))
        )


def _make_graph() -> Graph:
    """Create a new RDF graph with standard namespace bindings."""
    graph = Graph()
    graph.bind("bibo", BIBO)
    graph.bind("dcterms", DCTERMS)
    graph.bind("foaf", FOAF)
    graph.bind("schema", SCHEMA)
    graph.bind("xsd", XSD)
    graph.bind("scilex", SCILEX)
    graph.bind("prov", PROV)
    graph.bind("owl", OWL)
    return graph


def convert(
    bib_path: str,
    base_uri: str = "http://example.org/pub/",
    collect_name: str | None = None,
) -> Graph:
    """Parse a BibTeX file and return an RDF graph.

    URI strategy:

    - Uses ``https://doi.org/{doi}`` when a DOI field is present.
    - Falls back to ``{base_uri}{bibtex_key}`` otherwise.

    The ``references`` BibTeX field (comma-separated DOIs) is converted to
    ``bibo:cites`` triples.  The ``cited_by`` field is converted to
    ``bibo:citedBy`` triples.

    Args:
        bib_path: Path to the ``.bib`` file.
        base_uri: Base URI for locally-minted resource URIs.
        collect_name: Optional collection name from ``scilex.config.yml``; when
            provided, a ``prov:Activity`` provenance node is added to the graph.

    Returns:
        An :class:`rdflib.Graph` populated with bibliographic triples.

    Raises:
        ValueError: If the BibTeX file cannot be parsed.
    """
    if not base_uri.endswith("/"):
        base_uri = base_uri + "/"

    graph = _make_graph()

    try:
        library = bibtexparser.parse_file(bib_path)
    except Exception as exc:
        raise ValueError(f"Failed to parse BibTeX file {bib_path!r}: {exc}") from exc

    for entry in library.entries:
        entry_type = entry.entry_type.lower()
        fields = {k.lower(): v.value for k, v in entry.fields_dict.items()}

        # --- Build resource URI ---
        doi = fields.get("doi", "").strip()
        if doi:
            resource_uri = URIRef(
                f"https://doi.org/{urllib.parse.quote(doi, safe='/')}"
            )
        else:
            resource_uri = URIRef(f"{base_uri}{entry.key}")

        # --- rdf:type ---
        rdf_class = ENTRY_TYPE_MAP.get(entry_type, BIBO.Document)
        graph.add((resource_uri, RDF.type, rdf_class))

        # --- Authors ---
        authors_raw = fields.get("author", "")
        if authors_raw:
            for raw in re.split(r"\s+and\s+", authors_raw, flags=re.IGNORECASE):
                if raw.strip():
                    _add_person(graph, base_uri, raw, DCTERMS.creator, resource_uri)

        # --- Editors ---
        editors_raw = fields.get("editor", "")
        if editors_raw:
            for raw in re.split(r"\s+and\s+", editors_raw, flags=re.IGNORECASE):
                if raw.strip():
                    _add_person(graph, base_uri, raw, DCTERMS.contributor, resource_uri)

        # --- Publisher (literal) ---
        publisher = fields.get("publisher", "").strip()
        if publisher:
            graph.add((resource_uri, DCTERMS.publisher, Literal(publisher)))

        # --- Journal / booktitle → BIBO.Journal / BIBO.Proceedings link ---
        journal = fields.get("journal", "").strip()
        if journal:
            journal_uri = URIRef(f"{base_uri}journal/{_slug(journal)}")
            graph.add((journal_uri, RDF.type, BIBO.Journal))
            graph.add((journal_uri, DCTERMS.title, Literal(journal)))
            graph.add((resource_uri, BIBO.journal, journal_uri))

        booktitle = fields.get("booktitle", "").strip()
        if booktitle and not journal:
            proc_uri = URIRef(f"{base_uri}proceedings/{_slug(booktitle)}")
            graph.add((proc_uri, RDF.type, BIBO.Proceedings))
            graph.add((proc_uri, DCTERMS.title, Literal(booktitle)))
            graph.add((resource_uri, DCTERMS.isPartOf, proc_uri))

        # --- Year + optional month → dcterms:date with XSD typed literal ---
        year_val = fields.get("year", "").strip()
        if year_val:
            month_raw = fields.get("month", "").strip()
            month_num = _MONTH_MAP.get(month_raw.lower(), "")
            if month_num:
                graph.add(
                    (
                        resource_uri,
                        DCTERMS.date,
                        Literal(f"{year_val}-{month_num}", datatype=XSD.gYearMonth),
                    )
                )
            else:
                graph.add(
                    (resource_uri, DCTERMS.date, Literal(year_val, datatype=XSD.gYear))
                )

        # --- Standard field mappings (from FIELD_MAP) ---
        for bib_field, (predicate, value_type, xsd_type) in FIELD_MAP.items():
            value = fields.get(bib_field, "").strip()
            if not value:
                continue

            if value_type == "keyword_list":
                for kw in re.split(r"[,;]", value):
                    kw = kw.strip()
                    if kw:
                        graph.add((resource_uri, predicate, Literal(kw)))

            elif value_type == "uri":
                if value.startswith(("http://", "https://")):
                    encoded = urllib.parse.quote(value, safe=":/?#[]@!$&'()*+,;=%")
                    graph.add((resource_uri, predicate, URIRef(encoded)))

            elif value_type == "page_range":
                graph.add((resource_uri, predicate, Literal(value)))
                _add_page_range(graph, resource_uri, value)

            else:  # "literal"
                graph.add((resource_uri, predicate, _typed_literal(value, xsd_type)))

        # --- References → bibo:cites triples (outgoing citations) ---
        references_raw = fields.get("references", "").strip()
        if references_raw:
            for cited_doi in re.split(r",\s*", references_raw):
                cited_doi = cited_doi.strip()
                if cited_doi:
                    graph.add(
                        (
                            resource_uri,
                            BIBO.cites,
                            URIRef(
                                f"https://doi.org/{urllib.parse.quote(cited_doi, safe='/')}"
                            ),
                        )
                    )

        # --- cited_by → bibo:citedBy triples (incoming citations) ---
        cited_by_raw = fields.get("cited_by", "").strip()
        if cited_by_raw:
            for citing_doi in re.split(r",\s*", cited_by_raw):
                citing_doi = citing_doi.strip()
                if citing_doi:
                    graph.add(
                        (
                            resource_uri,
                            BIBO.citedBy,
                            URIRef(
                                f"https://doi.org/{urllib.parse.quote(citing_doi, safe='/')}"
                            ),
                        )
                    )

    # --- Optional provenance node ---
    if collect_name:
        from .provenance import add_collection_provenance

        add_collection_provenance(graph, base_uri, collect_name)

    return graph


def convert_to_string(
    bib_path: str,
    base_uri: str = "http://example.org/pub/",
    fmt: str = "turtle",
    collect_name: str | None = None,
) -> str:
    """Convert a BibTeX file and serialise the graph to a string.

    Args:
        bib_path: Path to the ``.bib`` file.
        base_uri: Base URI for locally-minted resource URIs.
        fmt: RDFLib serialisation format (e.g. ``"turtle"``, ``"n3"``, ``"xml"``).
        collect_name: Optional collection name; passed through to :func:`convert`.

    Returns:
        The serialised RDF graph as a string.
    """
    graph = convert(bib_path, base_uri, collect_name)
    return graph.serialize(format=fmt)
