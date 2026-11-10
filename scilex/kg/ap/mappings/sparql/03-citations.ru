# 03 -- Citation graph.
# RML points every DOI found in the SciLEx citation notes at a stub
# br/doi/<doi>. Here: (a) stubs whose DOI belongs to a corpus paper are merged
# into that paper, (b) remaining stubs become minimal OCDM resources with a DOI
# identifier, (c) each corpus paper gets a C4O global citation count.

PREFIX xsd:      <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs:     <http://www.w3.org/2000/01/rdf-schema#>
PREFIX dcterms:  <http://purl.org/dc/terms/>
PREFIX fabio:    <http://purl.org/spar/fabio/>
PREFIX cito:     <http://purl.org/spar/cito/>
PREFIX c4o:      <http://purl.org/spar/c4o/>
PREFIX datacite: <http://purl.org/spar/datacite/>
PREFIX literal:  <http://www.essepuntato.it/2010/06/literalreification/>

# (a) merge stubs into corpus papers. The stub IRI is rebuilt from each corpus DOI:
#     ENCODE_FOR_URI + restoring "/():;" == Python quote(safe="/():;") used by the FnO
#     function, so this is a direct lookup instead of decoding every stub.
DELETE { ?stub ?p ?o }
INSERT { ?br ?p ?o }
WHERE {
  ?br dcterms:identifier ?key ; datacite:hasIdentifier ?id .
  ?id datacite:usesIdentifierScheme datacite:doi ; literal:hasLiteralValue ?v .
  BIND (IRI(CONCAT("{{BASE}}br/doi/",
        REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ENCODE_FOR_URI(STR(?v)),
        "%2F", "/"), "%28", "("), "%29", ")"), "%3A", ":"), "%3B", ";"))) AS ?stub)
  ?stub ?p ?o .
} ;
DELETE { ?s ?p ?stub }
INSERT { ?s ?p ?br }
WHERE {
  ?br dcterms:identifier ?key ; datacite:hasIdentifier ?id .
  ?id datacite:usesIdentifierScheme datacite:doi ; literal:hasLiteralValue ?v .
  BIND (IRI(CONCAT("{{BASE}}br/doi/",
        REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ENCODE_FOR_URI(STR(?v)),
        "%2F", "/"), "%28", "("), "%29", ")"), "%3A", ":"), "%3B", ";"))) AS ?stub)
  ?s ?p ?stub .
} ;

# (b) remaining stubs = works outside the corpus: typed + DOI identifier
INSERT {
  ?stub a fabio:Expression ;
        datacite:hasIdentifier ?id .
  ?id a datacite:Identifier ;
      datacite:usesIdentifierScheme datacite:doi ;
      literal:hasLiteralValue ?doi .
}
WHERE {
  { SELECT DISTINCT ?stub WHERE {
      { ?stub cito:cites ?x } UNION { ?x cito:cites ?stub }
      FILTER (STRSTARTS(STR(?stub), "{{BASE}}br/doi/"))
  } }
  BIND (STRAFTER(STR(?stub), "/br/doi/") AS ?enc)
  BIND (REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(?enc,
        "%2B", "+"), "%3C", "<"), "%3E", ">"), "%5B", "["), "%5D", "]"), "%23", "#"),
        "%20", " "), "%2C", ","), "%25", "%") AS ?doi)
  BIND (IRI(CONCAT("{{BASE}}id/doi/", ?enc)) AS ?id)
} ;

# (c) C4O global citation count for every corpus paper.
#     iter3: when the SciLEx note carries 'nb_citations' (with its 'source' API, e.g.
#     openalex), that global count is used; otherwise the count of citing works listed
#     in the note ('citing' DOIs), as in iter1-2.
INSERT {
  ?br c4o:hasGlobalCitationFrequency ?count .
  ?count a c4o:GlobalCitationCount ;
         c4o:hasGlobalCountValue ?value ;
         c4o:hasGlobalCountSource ?src .
  ?src a c4o:BibliographicInformationSource ;
       rdfs:label ?srcLabel .
}
WHERE {
  ?br dcterms:identifier ?key ; <urn:scilex:staging#note> ?note .
  FILTER (REGEX(?note, "'nb_citations': *[0-9]+"))
  BIND (xsd:integer(REPLACE(?note, "^.*'nb_citations': *([0-9]+).*$", "$1", "s")) AS ?value)
  BIND (IF(REGEX(?note, "'source': *'[A-Za-z0-9_]+'"),
           REPLACE(?note, "^.*'source': *'([A-Za-z0-9_]+)'.*$", "$1", "s"), "unknown") AS ?api)
  BIND (IRI(CONCAT("{{BASE}}source/", ?api)) AS ?src)
  BIND (CONCAT("Citation count reported by the ", ?api, " API through SciLEx (note field: nb_citations)") AS ?srcLabel)
  BIND (IRI(CONCAT(STR(?br), "/citation-count/1")) AS ?count)
} ;
INSERT DATA {
  <{{BASE}}source/scilex-citation-note>
      a c4o:BibliographicInformationSource ;
      rdfs:label "SciLEx citation enrichment (note field: citing/cited DOI lists)"@en .
} ;
INSERT {
  ?br c4o:hasGlobalCitationFrequency ?count .
  ?count a c4o:GlobalCitationCount ;
         c4o:hasGlobalCountValue ?value ;
         c4o:hasGlobalCountSource <{{BASE}}source/scilex-citation-note> .
}
WHERE {
  { SELECT ?br (COUNT(DISTINCT ?citing) AS ?n)
    WHERE { ?br dcterms:identifier ?key .
            FILTER NOT EXISTS { ?br c4o:hasGlobalCitationFrequency ?already }
            OPTIONAL { ?citing cito:cites ?br } }
    GROUP BY ?br }
  BIND (?n AS ?value)  # xsd:integer (value-compatible with the C4O nonNegativeInteger range)
  BIND (IRI(CONCAT(STR(?br), "/citation-count/1")) AS ?count)
} ;

# staging triples are not part of the output
DELETE WHERE { ?s <urn:scilex:staging#note> ?note }
