"""PROV-O provenance triples for SciLEx collection activities.

Adds a ``prov:Activity`` node representing a SciLEx collection run to an
existing RDF graph.  This enables downstream consumers to trace which API
collection produced each bibliographic record.
"""

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, XSD

from .namespaces import SCILEX


def add_collection_provenance(
    graph: Graph,
    base_uri: str,
    collect_name: str,
    collection_date: str | None = None,
) -> URIRef:
    """Mint a ``prov:Activity`` node representing a SciLEx collection run.

    The activity URI is ``{base_uri}collection/{collect_name}`` and is typed
    as both ``prov:Activity`` and ``scilex:Collection``.

    Args:
        graph: The RDF graph to add triples to.
        base_uri: Base URI for locally-minted URIs (must end with ``/``).
        collect_name: The ``collect_name`` value from ``scilex.config.yml``.
        collection_date: Optional ISO date string (``YYYY-MM-DD``) of when the
            collection ran; emitted as ``prov:endedAtTime``.

    Returns:
        The ``URIRef`` of the newly-minted collection activity node.
    """
    activity_uri = URIRef(f"{base_uri}collection/{collect_name}")
    graph.add((activity_uri, RDF.type, PROV.Activity))
    graph.add((activity_uri, RDF.type, SCILEX.Collection))
    graph.add(
        (activity_uri, DCTERMS.title, Literal(f"SciLEx collection: {collect_name}"))
    )
    if collection_date:
        graph.add(
            (
                activity_uri,
                PROV.endedAtTime,
                Literal(collection_date, datatype=XSD.date),
            )
        )
    return activity_uri
