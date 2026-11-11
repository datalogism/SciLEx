"""Namespace declarations for the SciLEx RDF vocabulary.

All RDF namespace objects used across the ``scilex.rdf`` package are defined
here.  Import from this module rather than re-declaring namespaces in each file.
"""

from rdflib.namespace import DCTERMS, FOAF, OWL, PROV, RDF, XSD, Namespace

BIBO = Namespace("http://purl.org/ontology/bibo/")
SCHEMA = Namespace("https://schema.org/")
SCILEX = Namespace("https://w3id.org/scilex/vocab#")

__all__ = ["BIBO", "DCTERMS", "FOAF", "OWL", "PROV", "RDF", "SCHEMA", "SCILEX", "XSD"]
