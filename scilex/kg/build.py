"""Build a review's knowledge graph with the scilex-lpwc-ap application profile.

Pipeline (the profile's own, adapted to the review by :mod:`scilex.kg.profile`)::

    <review>.bib  (Zotero BibLaTeX export of the review's collection)
      │ 1. scilex.kg.bib2json                generic JSON tables
      │    + SciLEx clean-up                  automation tags dropped, citation note isolated
      │ 2. profile RML + FnO functions        morph-kgc
      │ 3. profile SPARQL UPDATE files        pyoxigraph, in file-name order
      ▼
    <review>/kg/<slug>.ttl   + dataset metadata (profile version) + SHACL report

Stages 2 and 3 need the optional ``kg`` dependencies (``pip install scilex[kg]``).
"""

from __future__ import annotations

import ast
import datetime as dt
import io
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, RDFS

from scilex.kg import bib2json
from scilex.kg.profile import (
    PROFILE_DIR,
    PROFILE_IRI,
    PreparedMapping,
    is_templated,
    prepare_mapping,
    read_version,
    shapes_paths,
)
from scilex.tagging.grid import is_automation_tag

logger = logging.getLogger(__name__)

DCAT = Namespace("http://www.w3.org/ns/dcat#")

PREFIXES = {
    "dcterms": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "fabio": "http://purl.org/spar/fabio/",
    "frbr": "http://purl.org/vocab/frbr/core#",
    "cito": "http://purl.org/spar/cito/",
    "c4o": "http://purl.org/spar/c4o/",
    "pro": "http://purl.org/spar/pro/",
    "datacite": "http://purl.org/spar/datacite/",
    "literal": "http://www.essepuntato.it/2010/06/literalreification/",
    "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "oco": "https://w3id.org/oc/ontology/",
    "lpwc": "https://linkedpaperswithcode.com/class/",
    "lpwcp": "https://linkedpaperswithcode.com/property/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
    "sxv": "https://w3id.org/scilex/vocab#",
}
OCDM_FOLDERS = ("br", "ar", "ra", "id", "coding")

# Keys of the citation dict SciLEx writes in Zotero's Extra (two generations).
CITATION_KEYS = {"citing", "cited", "citing_dois", "cited_dois"}

KG_EXTRA_HINT ="Building a knowledge graph needs the 'kg' extra: pip install 'scilex[kg]'"


class KgDependencyError(ImportError):
    """morph-kgc / pyoxigraph are not installed."""


@dataclass
class BuildReport:
    """What a build produced."""

    output: Path
    triples: int = 0
    papers: int = 0
    dropped_tags: int = 0
    notes_cleaned: int = 0
    profile: dict = field(default_factory=dict)
    conforms: bool | None = None  # None: not validated
    validation_report: Path | None = None
    stage_seconds: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 1 clean-up: SciLEx-specific fixes on the generic tables
# ---------------------------------------------------------------------------


def citation_dict_line(note: str) -> str | None:
    """Return the ``{'citing': [...], 'cited': [...]}`` part of a note, if any.

    SciLEx stores the citation lists in Zotero's Extra field, followed by other
    lines (``Archive ID: ...``, ``PDF URL: ...``). Zotero exports Extra as the
    BibLaTeX ``note``, where the profile reads the whole value as one Python
    literal, so the extra lines would make every citation of the paper vanish.
    """
    start = note.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(note)):
            if note[end] == "{":
                depth += 1
            elif note[end] == "}":
                depth -= 1
                if depth == 0:
                    candidate = note[start : end + 1]
                    try:
                        value = ast.literal_eval(candidate)
                    except (ValueError, SyntaxError):
                        break
                    if isinstance(value, dict) and (CITATION_KEYS & set(value)):
                        return candidate
                    break
        start = note.find("{", start + 1)
    return None


def clean_tables(data: dict, drop_automation_tags: bool = True) -> tuple[dict, int, int]:
    """Drop SciLEx automation tags and isolate the citation dict of each note.

    Profiles from iteration 3 map SciLEx's own tags (``Collect_KW1:...``,
    ``HavePDF``...): pass ``drop_automation_tags=False`` to keep them.

    Returns:
        ``(data, dropped tag count, cleaned note count)``.
    """
    kept, dropped = [], 0
    for row in data["lists"]:
        if (
            drop_automation_tags
            and row["field"] == "keywords"
            and is_automation_tag(row["value"])
        ):
            dropped += 1
            continue
        kept.append(row)
    data["lists"] = kept

    cleaned = 0
    for entry in data["entries"]:
        note = entry.get("note")
        if not note:
            continue
        line = citation_dict_line(note)
        if line is None:
            continue
        if line != note.strip():
            cleaned += 1
        entry["note"] = line
    return data, dropped, cleaned


# ---------------------------------------------------------------------------
# Stages 2 and 3
# ---------------------------------------------------------------------------


def _kg_modules():
    try:
        import morph_kgc
        import pyoxigraph
    except ImportError as exc:
        raise KgDependencyError(KG_EXTRA_HINT) from exc
    return morph_kgc, pyoxigraph


def run_rml(mapping: PreparedMapping) -> Graph:
    """Stage 2: materialize the RML mapping with morph-kgc."""
    morph_kgc, _ = _kg_modules()
    config = (
        "[CONFIGURATION]\n"
        "output_format=N-TRIPLES\n"
        f"udfs={mapping.udfs.resolve().as_posix()}\n"
        "[DataSource]\n"
        f"mappings={','.join(p.resolve().as_posix() for p in mapping.rml)}\n"
    )
    # The FnO functions read the collection profile from the environment (iter3+).
    saved = {key: os.environ.get(key) for key in mapping.env}
    os.environ.update(mapping.env)
    try:
        return morph_kgc.materialize(config)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _store_to_ntriples(store, pyoxigraph) -> str:
    buffer = io.BytesIO()
    try:  # pyoxigraph >= 0.4
        store.dump(buffer, format=pyoxigraph.RdfFormat.N_TRIPLES, from_graph=pyoxigraph.DefaultGraph())
    except (AttributeError, TypeError):  # pyoxigraph 0.3 (pinned by morph-kgc 2.10)
        store.dump(buffer, mime_type="application/n-triples", from_graph=pyoxigraph.DefaultGraph())
    return buffer.getvalue().decode("utf-8")


def _store_load(store, data: bytes, pyoxigraph) -> None:
    try:
        store.load(data, format=pyoxigraph.RdfFormat.N_TRIPLES)
    except (AttributeError, TypeError):
        store.load(data, mime_type="application/n-triples")


def run_sparql(mapping: PreparedMapping, graph: Graph) -> Graph:
    """Stage 3: apply the SPARQL UPDATE files in order with Oxigraph."""
    _, pyoxigraph = _kg_modules()
    store = pyoxigraph.Store()
    _store_load(store, graph.serialize(format="nt", encoding="utf-8"), pyoxigraph)
    for ru in mapping.sparql:
        before, started = len(store), time.perf_counter()
        store.update(ru.read_text(encoding="utf-8"))
        logger.info(
            "%s: %d -> %d triples (%.1fs)", ru.name, before, len(store), time.perf_counter() - started
        )
    return Graph().parse(data=_store_to_ntriples(store, pyoxigraph), format="nt")


# ---------------------------------------------------------------------------
# Dataset metadata and validation
# ---------------------------------------------------------------------------


def describe_subcorpora(graph: Graph, base_iri: str, subcorpora: dict[str, list[str]]) -> None:
    """Add one ``dcat:Dataset`` per sub-corpus (Zotero collection) with its papers.

    ``subcorpora`` maps a collection path (``Parent / Child``) to the citation
    keys of its papers; a paper may belong to several.
    """
    from scilex.kg.profile import slugify

    dataset = URIRef(base_iri)
    for path, keys in sorted(subcorpora.items()):
        part = URIRef(f"{base_iri}subcorpus/{slugify(path)}")
        graph.add((part, RDF.type, DCAT.Dataset))
        graph.add((part, DCTERMS.title, Literal(path)))
        graph.add((part, DCTERMS.isPartOf, dataset))
        graph.add((dataset, DCTERMS.hasPart, part))
        for key in keys:
            graph.add((part, DCTERMS.hasPart, URIRef(f"{base_iri}br/{key}")))


def describe_dataset(
    graph: Graph,
    base_iri: str,
    review_name: str,
    source_name: str,
    profile: dict,
    creator: str | None = None,
) -> None:
    """Replace the profile's sample dataset description with this review's.

    ``creator`` is the IRI of the user's ORCID iD.
    """
    dataset = URIRef(base_iri)
    if creator:
        graph.add((dataset, DCTERMS.creator, URIRef(creator)))
        graph.add((dataset, PROV.wasAttributedTo, URIRef(creator)))
    for prop in (DCTERMS.title, DCTERMS.description):
        graph.remove((dataset, prop, None))
    graph.add((dataset, RDF.type, DCAT.Dataset))
    graph.add((dataset, DCTERMS.title, Literal(f"SciLEx review: {review_name}", lang="en")))
    graph.add(
        (
            dataset,
            DCTERMS.description,
            Literal(
                f"Bibliographic records, citation links and review coding of the SciLEx "
                f"review '{review_name}', mapped with the scilex-lpwc-ap application profile "
                f"(OCDM/SPAR + Linked Papers With Code).",
                lang="en",
            ),
        )
    )
    graph.add((dataset, DCTERMS.conformsTo, URIRef(PROFILE_IRI)))
    if profile.get("version_iri"):
        graph.add((dataset, DCTERMS.conformsTo, URIRef(profile["version_iri"])))
    graph.add((dataset, DCTERMS.created, Literal(dt.date.today())))
    for source in graph.objects(dataset, PROV.wasDerivedFrom):
        graph.remove((source, RDFS.label, None))
        graph.add(
            (source, RDFS.label, Literal(f"{source_name} (Zotero BibLaTeX export of the review)", lang="en"))
        )


def validate(graph: Graph, report_path: Path, profile_dir: Path = PROFILE_DIR) -> bool | None:
    """Validate ``graph`` against the profile's general shapes; write the report.

    Returns:
        True / False, or None when pyshacl or the shapes are not available.
    """
    shapes = shapes_paths(profile_dir)
    if not shapes:
        logger.warning("No SHACL shapes in the pinned profile: validation skipped")
        return None
    try:
        from pyshacl import validate as shacl_validate
    except ImportError:
        logger.warning("pyshacl is not installed: validation skipped (%s)", KG_EXTRA_HINT)
        return None
    shapes_graph = Graph()
    for path in shapes:
        shapes_graph.parse(path, format="turtle")
    conforms, report_graph, report_text = shacl_validate(
        graph, shacl_graph=shapes_graph, inference="none", allow_warnings=True
    )
    report_graph.serialize(report_path, format="turtle")
    report_path.with_suffix(".txt").write_text(report_text, encoding="utf-8")
    return bool(conforms)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_knowledge_graph(
    bib_path: Path,
    output: Path,
    *,
    review_name: str,
    base_iri: str,
    dimensions: list[str] | None = None,
    run_validation: bool = True,
    profile_dir: Path = PROFILE_DIR,
    creator: str | None = None,
    subcorpora: dict[str, list[str]] | None = None,
) -> BuildReport:
    """Build the knowledge graph of one review from its BibLaTeX export.

    Args:
        bib_path: Zotero BibLaTeX export of the review's papers.
        output: Turtle file to write.
        review_name: Human name of the review (dataset title).
        base_iri: Base IRI of the review's resources (ends with ``/``).
        dimensions: The review's coding dimensions (annotation grid); None keeps
            the profile's own list.
        run_validation: Validate against the profile's SHACL shapes.
        profile_dir: Folder of the pinned profile.
        creator: IRI of the user's ORCID iD (``dcterms:creator`` of the dataset).
        subcorpora: ``{collection path: [citation keys]}``, one sub-dataset each.

    Raises:
        KgDependencyError: If the ``kg`` extra is not installed.
        ProfileError: If the pinned profile cannot be adapted.
    """
    _kg_modules()
    profile = read_version(profile_dir)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = BuildReport(output=output, profile=profile)
    bib_path = Path(bib_path)

    with tempfile.TemporaryDirectory(prefix="scilex-kg-") as tmp:
        work = Path(tmp)
        started = time.perf_counter()
        data = bib2json.convert(bib_path)
        data, report.dropped_tags, report.notes_cleaned = clean_tables(
            data, drop_automation_tags=not is_templated(profile_dir)
        )
        report.papers = len(data["entries"])
        source_json = work / "source.json"
        source_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        report.stage_seconds["bib2json"] = time.perf_counter() - started

        mapping = prepare_mapping(
            work / "mapping",
            base_iri=base_iri,
            source_json=source_json,
            source_name=bib_path.name,
            dimensions=dimensions,
            profile_dir=profile_dir,
            title=f"SciLEx review: {review_name}",
            description=(
                f"Bibliographic records, citation links and review coding of the SciLEx "
                f"review '{review_name}'."
            ),
        )
        started = time.perf_counter()
        graph = run_rml(mapping)  # sources are absolute paths: no chdir needed
        report.stage_seconds["rml"] = time.perf_counter() - started
        logger.info("RML: %d triples", len(graph))

        started = time.perf_counter()
        graph = run_sparql(mapping, graph)
        report.stage_seconds["sparql"] = time.perf_counter() - started

    describe_dataset(graph, base_iri, review_name, bib_path.name, profile, creator)
    if subcorpora:
        describe_subcorpora(graph, base_iri, subcorpora)
    for prefix, namespace in PREFIXES.items():
        graph.bind(prefix, namespace, override=True)
    for folder in OCDM_FOLDERS:
        graph.bind(folder, f"{base_iri}{folder}/", override=True)
    graph.serialize(output, format="turtle", encoding="utf-8")
    report.triples = len(graph)

    if run_validation:
        report.validation_report = output.with_name(output.stem + ".shacl.ttl")
        report.conforms = validate(graph, report.validation_report, profile_dir)
        if report.conforms is None:
            report.validation_report = None
    return report
