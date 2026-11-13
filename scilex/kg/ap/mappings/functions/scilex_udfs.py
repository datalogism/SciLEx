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
#
# iter4: this file is pure ASCII (non-ASCII characters are written as \u escapes).
# morph-kgc opens it with the locale encoding (cp1252 on Windows), where UTF-8
# superscripts crashed it (iter4 proposal, A5). scripts/validate.sh checks it.

import ast
import json
import os
import re
import unicodedata
from urllib.parse import quote

FN = "https://w3id.org/scilex/fn#"
P1 = FN + "value"
P2 = FN + "value2"
SXV = "https://w3id.org/scilex/vocab#"

# --------------------------------------------------------------------------
# Collection profile. The caller (scripts/build_iteration.py, or SciLEx) sets
# SCILEX_PROFILE to the *effective* profile written by mappings/ap_profile.py:
# reference profiles merged, defaults filled in, "effective": true. It gives the
# collection's namespace ("base", iter4: no longer rebuilt from the slug, A3) and
# its tag grammar (dimensions with their origin, patterns, aliases, plain tags).
# --------------------------------------------------------------------------

_PROFILES = {}


def profile():
    path = os.environ["SCILEX_PROFILE"]
    if path not in _PROFILES:
        with open(path, encoding="utf-8") as fh:
            p = json.load(fh)
        if not p.get("effective"):
            raise ValueError(
                "SCILEX_PROFILE must be an effective profile (mappings/ap_profile.py "
                "load_profile + write_effective_profile), got " + path
            )
        t = p["tags"]
        dims = [{"name": d} if isinstance(d, str) else d for d in t["dimensions"]]
        pats = [
            {"pattern": x} if isinstance(x, str) else x
            for x in t.get("dimension_patterns", [])
        ]
        t["_origin"] = {d["name"]: d.get("origin", "grid") for d in dims}
        # iter6 (UCR4): declared value type of each dimension ("binary", "closed", ...)
        t["_vtype"] = {d["name"]: d["values"]["type"] for d in dims if "values" in d}
        t["_dims"] = set(t["_origin"]) | set(t.get("dimension_aliases", {}).values())
        t["_patterns"] = [
            (re.compile(x["pattern"]), x.get("origin", "grid")) for x in pats
        ]
        t["_plain"] = {
            tag.upper(): dim for dim, tags in t.get("plain", {}).items() for tag in tags
        }
        t["_plain_origin"] = t.get("plain_origins", {})
        _PROFILES[path] = p
    return _PROFILES[path]


def base():
    return profile()["base"]


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
    became "unnamed" and "Hern\u00e1ndez" became "hern-ndez" with an ASCII-only slug)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = "-".join(re.findall(r"\w+", text.casefold())).replace("_", "-")
    return quote(text, safe="-") if text else "unnamed"


@udf(fun_id=FN + "entityIri", value=P1, value2=P2)
def entity_iri(value, value2):
    """IRI of a named entity: value = path (e.g. "br/venue/journal"), value2 = name -> slug."""
    return f"{base()}{value}/{slug(value2)}"


# --------------------------------------------------------------------------
# iter8 (ORSD VR4, VR5): conference series and editions from `eventtitle`.
# BibLaTeX eventtitles mix levels: "AAAI" (series), "EMNLP 2020 11", "ACL 2019 7",
# "WWW '22: The ACM Web Conference 2022", "iPRES 2025: The 21st International Conference
# on Digital Preservation". The series key drops years, ordinals, edition numbers and a
# subtitle after an acronym; the edition is (series, year), the year coming from the
# eventtitle, else from the paper's date.
# --------------------------------------------------------------------------

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_SHORT_YEAR = re.compile(r"'(\d{2})\b")


def conference_series_name(title):
    t = (title or "").strip()
    if not t:
        return None
    head, sep, _ = t.partition(":")
    # "WWW '22: The ACM Web Conference 2022" -> "WWW '22" (acronym before the subtitle)
    if sep and re.fullmatch(
        r"[A-Za-z][\w&.\-]*\s*('\d{2}|(19|20)\d{2})?\s*", head.strip() + " "
    ):
        t = head
    t = re.sub(r"^(proceedings of( the)?)\s+", "", t, flags=re.I)
    t = _YEAR.sub(" ", t)
    t = _SHORT_YEAR.sub(" ", t)
    t = re.sub(r"\b\d+(st|nd|rd|th)\b", " ", t, flags=re.I)
    t = re.sub(r"-\d{2}\b", " ", t)  # "AAAI-23"
    t = re.sub(r"(\s+\d+)+\s*$", "", t)  # trailing edition numbers ("ACL 2019 7")
    t = re.sub(r"\s+", " ", t).strip(" -,:")
    return t or None


def conference_year(title, date):
    m = _YEAR.search(title or "")
    if m:
        return m.group(0)
    m = _SHORT_YEAR.search(title or "")
    if m:
        return "20" + m.group(1) if int(m.group(1)) < 50 else "19" + m.group(1)
    m = _YEAR.search(date or "")
    return m.group(0) if m else None


@udf(fun_id=FN + "conferenceSeriesIri", value=P1)
def conference_series_iri(value):
    name = conference_series_name(value)
    return f"{base()}conference/{slug(name)}" if name else None


@udf(fun_id=FN + "conferenceEditionIri", value=P1, value2=P2)
def conference_edition_iri(value, value2):
    name, year = conference_series_name(value), conference_year(value, value2)
    return f"{base()}conference/{slug(name)}/{year}" if name and year else None


# iter4: sub-corpora (Zotero collections of a review, ORSD UCR15 / IR5)
@udf(fun_id=FN + "subcorpusIri", value=P1)
def subcorpus_iri(value):
    value = value.strip()
    return f"{base()}subcorpus/{slug(value)}" if value else None


# --------------------------------------------------------------------------
# Agent roles (BibLaTeX name-list field -> PRO role)
# --------------------------------------------------------------------------

PRO = "http://purl.org/spar/pro/"
NAME_FIELD_TO_ROLE = {
    "author": "author",
    "bookauthor": "author",
    "editor": "editor",
    "translator": "translator",
}


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
#
# iter4 (A7, ORSD IR4 / UCR11): the dict is found wherever it is in the note.
# SciLEx's Zotero push writes `Archive ID:`, `PDF URL:`, `Papers with Code:` lines
# into Extra after it, and reading the whole note as one literal lost every
# cito:cites of the paper. The `Key: value` lines are read in sparql/06.
# --------------------------------------------------------------------------

CITATION_KEYS = {"citing", "cited", "citing_dois", "cited_dois"}


def note_citation_dict(note):
    """The citation dict of a note, or None (first {...} that is a dict with citation keys)."""
    start = note.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(note)):
            if note[end] == "{":
                depth += 1
            elif note[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = ast.literal_eval(note[start : end + 1])
                    except (ValueError, SyntaxError):
                        break
                    if isinstance(value, dict) and CITATION_KEYS & set(value):
                        return value
                    break
        start = note.find("{", start + 1)
    return None


@udf(fun_id=FN + "noteCitationTargets", value=P1, value2=P2)
def note_citation_targets(value, value2):
    note = note_citation_dict(value)
    if note is None:
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
    return (
        [f"{m[1]}-{m[2].upper()}" for m in map(_ISSN.match, parts) if m]
        if parts
        else []
    )


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
    parts = [p.strip() for p in re.split("-+|\u2013", value) if p.strip()]
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
# Review coding tags  ("TASK:NER", "NBTRIPLES:10\u2075", "DONE", ...)
#
# A tag is "DIMENSION:value". The collection profile declares the dimensions
# (names or patterns, each with its origin), aliases (typos, renamings) and plain
# tags; unknown prefixes go to UNPARSED, other plain tags to TOPIC. Dimensions are
# upper-cased (spaces -> "_") and de-aliased; values get a normalised key so that
# spelling/case variants of the same code ("NER" / "Ner", "10\u00b9" / "10^1",
# "NSP" / "Nsp") collapse onto one concept. Raw spellings survive as
# skos:altLabel / skos:notation.
# --------------------------------------------------------------------------


def normalise_dimension(dim):
    dim = re.sub(r"\s+", "_", dim.strip()).upper()
    return profile()["tags"].get("dimension_aliases", {}).get(dim, dim)


def is_dimension(dim):
    t = profile()["tags"]
    return dim in t["_dims"] or any(p.fullmatch(dim) for p, _ in t["_patterns"])


SUPERSCRIPTS = str.maketrans(
    "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u00b0", "01234567890"
)


def parse_tag(tag):
    """-> (dimension, raw value, normalised value key)."""
    tag = tag.strip()
    t = profile()["tags"]
    if (
        tag.upper() in t["_plain"]
    ):  # declared plain tag: WORKFLOW, ACQUISITION, PRESENCE, ...
        dim, val = t["_plain"][tag.upper()], tag
    elif ":" in tag:
        dim, val = tag.split(":", 1)
        dim = normalise_dimension(dim)
        if not is_dimension(dim):
            dim, val = (
                "UNPARSED",
                tag,
            )  # unknown prefix, or fragment of a value containing commas
    elif (
        t.get("slash_form")
        and re.match(r"^[A-Za-z_]+/.+", tag)
        and is_dimension(normalise_dimension(tag.split("/", 1)[0]))
    ):
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
    vtype = profile()["tags"]["_vtype"].get(dim)
    # iter6: orders of magnitude where the grid declares them; without a declaration,
    # the iter1-iter5 rule (dimension name starting with NB) still applies
    if vtype in ("magnitude", "integer") or (vtype is None and dim.startswith("NB")):
        m = re.fullmatch(
            "10\\s*\\^?\\s*([0-9\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u00b0]+)",
            val,
        )
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


# iter4: who writes the tags of a dimension (ORSD UCR3, UCR10, KR1). One of the
# sxv:TagOrigins concepts; none for TOPIC (free keywords) and UNPARSED.
ORIGIN_CONCEPT = {
    "scilex": "ScilexTags",
    "enrichment": "EnrichmentTags",
    "grid": "GridTags",
    "workflow": "WorkflowTags",
}


def dimension_origin(dim):
    t = profile()["tags"]
    if dim in t["_origin"]:
        return t["_origin"][dim]
    if dim in t["_plain_origin"]:
        return t["_plain_origin"][dim]
    for p, origin in t["_patterns"]:
        if p.fullmatch(dim):
            return origin
    return None


@udf(fun_id=FN + "tagOrigin", value=P1)
def tag_origin(value):
    origin = dimension_origin(parse_tag(value)[0])
    return SXV + ORIGIN_CONCEPT[origin] if origin else None
