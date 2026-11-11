# FnO user-defined functions for the scilex-lpwc-ap RML mappings (morph-kgc UDFs).
#
# Loaded by morph-kgc through the `udfs` config key; morph-kgc prepends the `udf`
# decorator itself, so this file must NOT import it. Function IRIs live in
# https://w3id.org/scilex/fn# (prefix `sxfn:` in the mapping files); every
# parameter is passed through `sxfn:value` / `sxfn:value2`.
#
# Rule of thumb: everything that *interprets* a SciLEx- or review-specific
# micro-format (coding tags, citation notes, entry types) lives here, so the
# RML stays a readable declaration of *what* maps to *what*.

import ast
import json
import os
import re
import unicodedata
from urllib.parse import quote

FN = "https://w3id.org/scilex/fn#"
P1 = FN + "value"
P2 = FN + "value2"

# --------------------------------------------------------------------------
# Collection profile (iter3). scripts/build_iteration.py maps one collection at a
# time and sets SCILEX_PROFILE to its mappings/collections/<slug>.json, which gives
# the collection's IRI namespace and its tag grammar (dimensions, aliases, plain
# tags). The RML / SPARQL templates get the same namespace as {{BASE}}.
# --------------------------------------------------------------------------

DATA_NS = "https://w3id.org/scilex/data/"
_PROFILES = {}


def profile():
    path = os.environ["SCILEX_PROFILE"]
    if path not in _PROFILES:
        with open(path, encoding="utf-8") as fh:
            p = json.load(fh)
        t = p["tags"]
        t["_dims"] = set(t["dimensions"]) | set(t["dimension_aliases"].values())
        t["_patterns"] = [re.compile(x) for x in t["dimension_patterns"]]
        t["_plain"] = {tag.upper(): dim for dim, tags in t["plain"].items() for tag in tags}
        _PROFILES[path] = p
    return _PROFILES[path]


def base():
    return f"{DATA_NS}{profile()['slug']}/"

FABIO = "http://purl.org/spar/fabio/"


def _iri_part(text):
    return quote(text.strip(), safe="")


def _doi_part(doi):
    # Keep DOI punctuation readable in the IRI so sparql/03 can recover the DOI
    # with STRAFTER (+ a handful of REPLACEs) -- SPARQL has no percent-decode.
    return quote(doi, safe="/():;")


# --------------------------------------------------------------------------
# Entry types (OCDM JSON-LD context mapping, BibLaTeX flavoured)
# --------------------------------------------------------------------------

ENTRYTYPE_TO_FABIO = {
    "article": "JournalArticle",
    "inproceedings": "ProceedingsPaper",
    "conference": "ProceedingsPaper",
    "inbook": "BookChapter",
    "incollection": "BookChapter",
    "book": "Book",
    "proceedings": "AcademicProceedings",
    "thesis": "Thesis",
    "phdthesis": "Thesis",
    "mastersthesis": "Thesis",
    "report": "ReportDocument",
    "techreport": "ReportDocument",
    "dataset": "DataFile",
    "software": "ComputerProgram",
    "online": "WebContent",
    "misc": "Expression",
}

# Class of the resource named by `booktitle`, per entry type.
BOOKTITLE_CONTAINER = {
    "inproceedings": "AcademicProceedings",
    "conference": "AcademicProceedings",
    "inbook": "Book",
    "incollection": "Book",
}


@udf(fun_id=FN + "fabioType", value=P1)
def fabio_type(value):
    return FABIO + ENTRYTYPE_TO_FABIO.get(value.strip().lower(), "Expression")


@udf(fun_id=FN + "booktitleContainerType", value=P1)
def booktitle_container_type(value):
    return FABIO + BOOKTITLE_CONTAINER.get(value.strip().lower(), "Expression")


def slug(text):
    """IRI segment: accents folded, any script kept (iter3: Cyrillic names all
    became "unnamed" and "Hernández" became "hern-ndez" with an ASCII-only slug)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = "-".join(re.findall(r"\w+", text.casefold())).replace("_", "-")
    return quote(text, safe="-") if text else "unnamed"


@udf(fun_id=FN + "entityIri", value=P1, value2=P2)
def entity_iri(value, value2):
    """IRI of a named entity: value = path (e.g. "br/venue/journal"), value2 = name -> slug."""
    return f"{base()}{value}/{slug(value2)}"


# --------------------------------------------------------------------------
# Agent roles (BibLaTeX name-list field -> PRO role)
# --------------------------------------------------------------------------

PRO = "http://purl.org/spar/pro/"
NAME_FIELD_TO_ROLE = {"author": "author", "bookauthor": "author", "editor": "editor",
                      "translator": "translator"}


@udf(fun_id=FN + "proRole", value=P1)
def pro_role(value):
    return PRO + NAME_FIELD_TO_ROLE.get(value.strip().lower(), "author")


# --------------------------------------------------------------------------
# URLs: only well-formed http(s) URLs become IRIs
# --------------------------------------------------------------------------

_URL = re.compile(r"^https?://[^\s<>\"{}|\^`]+$")


@udf(fun_id=FN + "urlIri", value=P1)
def url_iri(value):
    value = value.strip()
    return value if _URL.match(value) else None


# --------------------------------------------------------------------------
# Identifiers
# --------------------------------------------------------------------------

def norm_doi(doi):
    doi = doi.strip().lower()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi)
    return doi.removeprefix("doi:").strip()


@udf(fun_id=FN + "normDoi", value=P1)
def norm_doi_udf(value):
    doi = norm_doi(value)
    return doi if doi.startswith("10.") else None


@udf(fun_id=FN + "doiIdentifierIri", value=P1)
def doi_identifier_iri(value):
    doi = norm_doi(value)
    return f"{base()}id/doi/{_doi_part(doi)}" if doi.startswith("10.") else None


# --------------------------------------------------------------------------
# SciLEx citation note: "{'citing': [doi, ...], 'cited': [doi, ...]}"
#   citing = works that cite this entry   (incoming)
#   cited  = works this entry cites       (outgoing)
# Returns a list -> morph-kgc explodes it into one term per DOI.
# --------------------------------------------------------------------------

@udf(fun_id=FN + "noteCitationTargets", value=P1, value2=P2)
def note_citation_targets(value, value2):
    try:
        note = ast.literal_eval(value.strip())
    except (ValueError, SyntaxError):
        return None
    if not isinstance(note, dict):
        return None
    # SciLEx writes {'citing', 'cited'} or {'citing_dois', 'cited_dois', 'nb_cited', 'nb_citations'}
    dois = note.get(value2, note.get(value2 + "_dois", [])) or []
    dois = [norm_doi(d) for d in dois if isinstance(d, str)]
    iris = [f"{base()}br/doi/{_doi_part(d)}" for d in dois if d.startswith("10.")]
    return iris or None


# --------------------------------------------------------------------------
# series: holds ISSNs in raw SciLEx exports (ORSD UCR11), a book series name otherwise
# --------------------------------------------------------------------------

_ISSN = re.compile(r"^(\d{4})-?(\d{3}[\dXx])$")


def _issns(value):
    parts = [p.strip() for p in re.split(r"[,;\s]+", value) if p.strip()]
    return [f"{m[1]}-{m[2].upper()}" for m in map(_ISSN.match, parts) if m] if parts else []


@udf(fun_id=FN + "seriesIssnIris", value=P1)
def series_issn_iris(value):
    """ISSN identifier IRIs when `series` holds ISSN(s); completed into identifiers in sparql/01."""
    issns = _issns(value)
    return [f"{base()}id/issn/{i}" for i in issns] or None


@udf(fun_id=FN + "seriesIri", value=P1)
def series_iri(value):
    """Book-series entity when `series` is a name (not ISSNs)."""
    if _issns(value) or not value.strip():
        return None
    return f"{base()}br/venue/series/{slug(value)}"


# --------------------------------------------------------------------------
# Pages: "8472--8487" -> 8472 / 8487 ; "102563" (article number) -> start only
# --------------------------------------------------------------------------

def _pages(value):
    parts = [p.strip() for p in re.split(r"-+|–", value) if p.strip()]
    return parts if parts and parts[0].upper() != "NA" else []


@udf(fun_id=FN + "startPage", value=P1)
def start_page(value):
    parts = _pages(value)
    return parts[0] if parts else None


@udf(fun_id=FN + "endPage", value=P1)
def end_page(value):
    parts = _pages(value)
    return parts[1] if len(parts) > 1 else None


# --------------------------------------------------------------------------
# Review coding tags  ("TASK:NER", "NBTRIPLES:10⁵", "DONE", ...)
#
# A tag is "DIMENSION:value". The collection profile (iter3) declares the
# dimensions (names or patterns), aliases (typos, renamings) and plain tags;
# unknown prefixes go to UNPARSED, other plain tags to TOPIC. Dimensions are
# upper-cased (spaces -> "_") and de-aliased; values
# get a normalised key so that spelling/case variants of the same code
# ("NER" / "Ner", "10¹" / "10^1", "NSP" / "Nsp") collapse onto one concept.
# Raw spellings survive as skos:altLabel / skos:notation.
# --------------------------------------------------------------------------

def normalise_dimension(dim):
    dim = re.sub(r"\s+", "_", dim.strip()).upper()
    return profile()["tags"]["dimension_aliases"].get(dim, dim)


def is_dimension(dim):
    t = profile()["tags"]
    return dim in t["_dims"] or any(p.fullmatch(dim) for p in t["_patterns"])


SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹°", "01234567890")


def parse_tag(tag):
    """-> (dimension, raw value, normalised value key)."""
    tag = tag.strip()
    t = profile()["tags"]
    if tag.upper() in t["_plain"]:  # declared plain tag: WORKFLOW, ACQUISITION, PRESENCE, ...
        dim, val = t["_plain"][tag.upper()], tag
    elif ":" in tag:
        dim, val = tag.split(":", 1)
        dim = normalise_dimension(dim)
        if not is_dimension(dim):
            dim, val = "UNPARSED", tag  # unknown prefix, or fragment of a value containing commas
    elif t["slash_form"] and re.match(r"^[A-Za-z_]+/.+", tag) and is_dimension(normalise_dimension(tag.split("/", 1)[0])):
        dim, val = tag.split("/", 1)  # "SOURCE/WIKIpedia"
        dim = normalise_dimension(dim)
    else:
        dim, val = "TOPIC", tag  # free keyword / comment
    return dim, val.strip(), value_key(dim, val.strip())


def value_key(dim, val):
    upper = val.upper()
    if val in ("", "?"):
        return "unknown"
    if upper in ("NSP", "NS"):
        return "not-specified"
    if upper == "NONE":
        return "none"
    if dim.startswith("NB"):
        m = re.fullmatch(r"10\s*\^?\s*([0-9⁰¹²³⁴⁵⁶⁷⁸⁹°]+)", val)
        if m:
            return "1e" + m.group(1).translate(SUPERSCRIPTS)
        if val.isdigit():
            return val
    key = re.sub(r"[^0-9a-z.]+", "", val.lower())
    return key or _iri_part(val.lower())


@udf(fun_id=FN + "codingConcept", value=P1)
def coding_concept(value):
    dim, _, key = parse_tag(value)
    return f"{base()}coding/{_iri_part(dim)}/{_iri_part(key)}"


@udf(fun_id=FN + "codingScheme", value=P1)
def coding_scheme(value):
    return f"{base()}coding/{_iri_part(parse_tag(value)[0])}"


@udf(fun_id=FN + "codingValue", value=P1)
def coding_value(value):
    return parse_tag(value)[1] or None
