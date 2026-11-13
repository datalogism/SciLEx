"""Start a review from a SciLEx knowledge graph (scilex-lpwc-ap Turtle export).

The graph written by ⑧ Export (``output/<review>/kg/<review>.ttl``) is the
richest record of a review: bibliographic data, authors, venues, coding
(``DIMENSION:Value`` concepts), citation links and sub-corpora. Its corpus
papers (the resources with a citation key, ``dcterms:identifier``) are turned
back into Zotero-shaped items, so the review is created exactly like an import
from Zotero: results table, deduced keywords / years / annotation grid.

The graph itself is copied into the new review (``kg/``), so nothing it holds
is lost. Every text read from the graph goes through
:func:`scilex.crawlers.utils.sanitize_secrets`: a key or token that slipped
into a URL never reaches the review.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, FOAF, RDF, SKOS, VOID, Namespace

from scilex.crawlers.utils import sanitize_secrets

logger = logging.getLogger(__name__)

FABIO = Namespace("http://purl.org/spar/fabio/")
FRBR = Namespace("http://purl.org/vocab/frbr/core#")
PRISM = Namespace("http://prismstandard.org/namespaces/basic/2.0/")
PRO = Namespace("http://purl.org/spar/pro/")
CITO = Namespace("http://purl.org/spar/cito/")
DATACITE = Namespace("http://purl.org/spar/datacite/")
LITERAL = Namespace("http://www.essepuntato.it/2010/06/literalreification/")
DCAT = Namespace("http://www.w3.org/ns/dcat#")
LPWC = Namespace("https://linkedpaperswithcode.com/class/")
LPWCP = Namespace("https://linkedpaperswithcode.com/property/")
SXV = Namespace("https://w3id.org/scilex/vocab#")

KG_SOURCE_FILENAME = "kg_source.yml"
KG_SUFFIXES = (".ttl", ".nt", ".trig", ".jsonld", ".rdf", ".owl", ".xml", ".n3")

# fabio class -> Zotero item type (first match wins).
ITEM_TYPES = (
    (FABIO.JournalArticle, "journalArticle"),
    (FABIO.ProceedingsPaper, "conferencePaper"),
    (FABIO.BookChapter, "bookSection"),
    (FABIO.Book, "book"),
    (FABIO.Thesis, "thesis"),
    (FABIO.DoctoralThesis, "thesis"),
    (FABIO.ReportDocument, "report"),
    (FABIO.Preprint, "preprint"),
    (FABIO.ComputerProgram, "computerProgram"),
    (FABIO.WebContent, "webpage"),
    (FABIO.Dataset, "dataset"),
)
# Container class -> Zotero field holding its title.
VENUE_FIELD = {
    FABIO.Journal: "publicationTitle",
    FABIO.AcademicProceedings: "proceedingsTitle",
    FABIO.Book: "bookTitle",
}


class KgImportError(ValueError):
    """The file is not a SciLEx knowledge graph (or cannot be read)."""


@dataclass
class KgInfo:
    """What a knowledge graph holds, shown before importing it."""

    path: Path
    title: str
    papers: int
    triples: int
    subcorpora: list[str]
    creator: str
    profile: str


def _text(value) -> str:
    """A literal as clean text, credentials masked."""
    if value is None:
        return ""
    return sanitize_secrets(str(value)).strip()


def read_graph(path: Path) -> Graph:
    """Parse a knowledge graph file (format from its extension).

    Raises:
        KgImportError: If the file cannot be parsed or holds no review paper.
    """
    path = Path(path)
    if not path.is_file():
        raise KgImportError(f"No such file: {path}")
    graph = Graph()
    try:
        graph.parse(path)  # rdflib guesses the format from the extension
    except Exception as exc:  # rdflib raises many parser-specific errors
        raise KgImportError(f"{path.name} is not a readable RDF file: {exc}") from exc
    if not corpus_papers(graph):
        raise KgImportError(
            f"{path.name} holds no review paper: expected a SciLEx knowledge graph "
            "(⑧ Export, scilex-lpwc-ap profile)."
        )
    return graph


def corpus_papers(graph: Graph) -> list[URIRef]:
    """The review's own papers: the resources with a citation key."""
    return sorted(
        {s for s in graph.subjects(DCTERMS.identifier, None) if isinstance(s, URIRef)},
        key=str,
    )


def _main_dataset(graph: Graph) -> URIRef | None:
    for dataset in graph.subjects(RDF.type, DCAT.Dataset):
        if (dataset, DCTERMS.isPartOf, None) not in graph:
            return dataset
    return None


def describe(path: Path, graph: Graph | None = None) -> KgInfo:
    """Summarise a knowledge graph (title, papers, sub-corpora, creator)."""
    graph = graph if graph is not None else read_graph(path)
    dataset = _main_dataset(graph)
    title = _text(graph.value(dataset, DCTERMS.title)) if dataset else ""
    profile = (
        ", ".join(sorted(str(o) for o in graph.objects(dataset, DCTERMS.conformsTo)))
        if dataset
        else ""
    )
    return KgInfo(
        path=Path(path),
        title=title.removeprefix("SciLEx review: ") or Path(path).stem,
        papers=len(corpus_papers(graph)),
        triples=len(graph),
        subcorpora=sorted(_subcorpora(graph).keys()),
        creator=_text(graph.value(dataset, DCTERMS.creator)) if dataset else "",
        profile=profile,
    )


def _subcorpora(graph: Graph) -> dict[str, set[URIRef]]:
    """``{sub-corpus title: papers}`` from the ``dcat:Dataset`` parts."""
    parts: dict[str, set[URIRef]] = {}
    for dataset in graph.subjects(RDF.type, DCAT.Dataset):
        if (dataset, DCTERMS.isPartOf, None) not in graph:
            continue
        title = _text(graph.value(dataset, DCTERMS.title))
        if title:
            # dcterms:hasPart (SciLEx, profiles up to iteration 3), void:inDataset (iter4+)
            parts[title] = set(graph.objects(dataset, DCTERMS.hasPart)) | set(
                graph.subjects(VOID.inDataset, dataset)
            )
    return parts


def _doi(graph: Graph, resource) -> str:
    for identifier in graph.objects(resource, DATACITE.hasIdentifier):
        if (identifier, DATACITE.usesIdentifierScheme, DATACITE.doi) in graph:
            value = _text(graph.value(identifier, LITERAL.hasLiteralValue))
            if value:
                return value
    return ""


def _creators(graph: Graph, paper) -> tuple[list[dict], str]:
    """Zotero creators (authors and editors, in order) and the publisher name."""
    roles: dict[str, list[tuple[int, str, dict]]] = defaultdict(list)
    publisher = ""
    for role in graph.objects(paper, PRO.isDocumentContextFor):
        kind = graph.value(role, PRO.withRole)
        agent = graph.value(role, PRO.isHeldBy)
        if kind is None or agent is None:
            continue
        name = _text(graph.value(agent, FOAF.name))
        if kind == PRO.publisher:
            publisher = publisher or name
            continue
        if kind not in (PRO.author, PRO.editor):
            continue
        position = graph.value(role, SXV.position)
        try:
            order = int(position)
        except (TypeError, ValueError):
            order = 10_000
        given = _text(graph.value(agent, FOAF.givenName))
        family = _text(graph.value(agent, FOAF.familyName))
        creator_type = "author" if kind == PRO.author else "editor"
        if family:
            entry = {
                "creatorType": creator_type,
                "firstName": given,
                "lastName": family,
            }
        else:
            entry = {"creatorType": creator_type, "name": name}
        roles[creator_type].append((order, str(role), entry))
    creators = [
        entry
        for kind in ("author", "editor")
        for _, _, entry in sorted(roles[kind], key=lambda r: (r[0], r[1]))
    ]
    return creators, publisher


def _tags(graph: Graph, paper) -> list[str]:
    """The paper's coding as ``DIMENSION:Value`` tags (the concepts' notations)."""
    tags = []
    for concept in graph.objects(paper, DCTERMS.subject):
        tag = _concept_tag(graph, concept)
        if tag:
            tags.append(tag)
    return sorted(set(tags))


def _concept_tag(graph: Graph, concept) -> str:
    """One tag for a coding concept.

    The profile merges spelling variants of a value into one concept and keeps
    them all as ``skos:notation`` (``SOURCE:DBpedia``, ``SOURCE/WIKIpedia``…),
    without saying which paper used which. Prefer ``DIMENSION:Value`` whose
    value is the preferred label, then any ``DIMENSION:Value``, then the rest.
    """
    notations = sorted(_text(n) for n in graph.objects(concept, SKOS.notation))
    label = _text(graph.value(concept, SKOS.prefLabel))
    scheme = graph.value(concept, SKOS.inScheme)
    dimension = str(scheme).rstrip("/").rsplit("/", 1)[-1] if scheme else ""
    if dimension in ("TOPIC", "UNPARSED"):  # free keywords: the raw tag
        dimension = ""
    prefix = f"{dimension}:" if dimension else ""

    def rank(notation: str) -> tuple:
        value = (
            notation[len(prefix) :] if prefix and notation.startswith(prefix) else None
        )
        return (
            value is None,  # DIMENSION:Value first
            value != label if value is not None else True,  # exactly the label
            value.casefold() != label.casefold() if value is not None else True,
            notation,
        )

    if notations:
        return min(notations, key=rank)
    return f"{prefix}{label}" if label else ""


def _citation_note(graph: Graph, paper, dois: dict) -> str:
    """The SciLEx citation note (``{'citing': [...], 'cited': [...]}``) of a paper."""
    cited = sorted({d for t in graph.objects(paper, CITO.cites) if (d := dois.get(t))})
    citing = sorted(
        {d for s in graph.subjects(CITO.cites, paper) if (d := dois.get(s))}
    )
    if not cited and not citing:
        return ""
    return repr({"citing": citing, "cited": cited})


def paper_to_item(graph: Graph, paper, dois: dict, collections: list[str]) -> dict:
    """A Zotero-shaped item (``{"key", "data"}``) from one corpus paper."""
    key = _text(graph.value(paper, DCTERMS.identifier))
    types = set(graph.objects(paper, RDF.type))
    item_type = next((z for cls, z in ITEM_TYPES if cls in types), "document")
    creators, publisher = _creators(graph, paper)
    data: dict = {
        "itemType": item_type,
        "title": _text(graph.value(paper, DCTERMS.title)),
        "abstractNote": _text(graph.value(paper, DCTERMS.abstract)),
        "date": _text(graph.value(paper, PRISM.publicationDate)),
        "DOI": _doi(graph, paper),
        "creators": creators,
        "publisher": publisher,
        "language": _text(graph.value(paper, DCTERMS.language)),
        "rights": _text(graph.value(paper, DCTERMS.rights)),
        "shortTitle": _text(graph.value(paper, FABIO.hasShortTitle)),
        "tags": [{"tag": tag} for tag in _tags(graph, paper)],
        "extra": _citation_note(graph, paper, dois),
    }
    embodiment = graph.value(paper, FRBR.embodiment)
    if embodiment is not None:
        data["url"] = _text(graph.value(embodiment, FRBR.exemplar))
        data["pages"] = _text(graph.value(embodiment, PRISM.pageRange))
        data["accessDate"] = _text(graph.value(embodiment, FABIO.hasAccessDate))
    for venue in graph.objects(paper, FRBR.partOf):
        title = _text(graph.value(venue, DCTERMS.title))
        field = next(
            (f for cls, f in VENUE_FIELD.items() if (venue, RDF.type, cls) in graph),
            "publicationTitle",
        )
        if title:
            data.setdefault(field, title)
        for prop, name in ((PRISM.volume, "volume"), (PRISM.number, "issue")):
            value = _text(graph.value(venue, prop)) or _text(graph.value(paper, prop))
            if value:
                data.setdefault(name, value)
    for prop, name in ((PRISM.volume, "volume"), (PRISM.number, "issue")):
        if name not in data and (value := _text(graph.value(paper, prop))):
            data[name] = value
    conference = graph.value(paper, LPWCP.hasConference)
    if conference is not None:
        name = _text(graph.value(conference, FOAF.name)) or _text(
            graph.value(conference, DCTERMS.title)
        )
        if name:
            data["conferenceName"] = name
    data = {k: v for k, v in data.items() if v not in ("", None, [])}
    data.setdefault("title", key)  # is_paper() needs a title
    data.setdefault("tags", [])
    return {"key": key, "data": data, "_scilex_collections": collections}


def graph_to_items(graph: Graph) -> list[dict]:
    """Zotero-shaped items of every corpus paper of the graph."""
    papers = corpus_papers(graph)
    dois = {
        resource: doi
        for resource in set(graph.subjects(CITO.cites, None))
        | set(graph.objects(None, CITO.cites))
        if (doi := _doi(graph, resource))
    }
    membership: dict = defaultdict(list)
    for title, members in _subcorpora(graph).items():
        for member in members:
            membership[member].append(title)
    return [
        paper_to_item(graph, paper, dois, sorted(membership.get(paper, [])))
        for paper in papers
    ]


def save_kg_source(folder: Path, kg_copy: Path, info: KgInfo) -> Path:
    """Remember the knowledge graph a review was created from."""
    import yaml

    path = Path(folder) / KG_SOURCE_FILENAME
    path.write_text(
        yaml.safe_dump(
            {
                "file": str(kg_copy),
                "imported_from": str(info.path),
                "title": info.title,
                "papers": info.papers,
                "triples": info.triples,
                "subcorpora": info.subcorpora,
                "profile": info.profile,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def create_review_from_kg(
    workspace,
    folder: Path,
    name: str,
    kg_path: Path,
    config_file: Path | None = None,
):
    """Create a review from a SciLEx knowledge graph file.

    Returns:
        ``(review, summary)`` as :func:`zotero_library.create_review_from_items`.

    Raises:
        KgImportError: If the file is not a SciLEx knowledge graph.
        FileExistsError, SettingsError: As for a Zotero import.
    """
    from scilex.gui.services.zotero_library import create_review_from_items

    kg_path = Path(kg_path)
    graph = read_graph(kg_path)
    info = describe(kg_path, graph)
    items = graph_to_items(graph)

    def finish(review) -> None:
        target_dir = review.collection_dir / "kg"
        target_dir.mkdir(parents=True, exist_ok=True)
        copy = target_dir / f"imported-{kg_path.name}"
        # Credentials masked in the copy too (values only: the syntax stays valid).
        copy.write_text(
            sanitize_secrets(kg_path.read_text(encoding="utf-8")), encoding="utf-8"
        )
        save_kg_source(review.folder, copy, info)

    review, summary = create_review_from_items(
        workspace,
        folder,
        name,
        items,
        config_file,
        origin=f"the knowledge graph '{kg_path.name}'",
        archive="KG",
        snapshot_origin="kg-import",
        finish=finish,
    )
    if info.subcorpora:
        summary.warnings.append(
            f"Sub-corpora kept in the 'zotero_collections' column: {', '.join(info.subcorpora)}."
        )
    return review, summary
