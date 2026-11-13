# 07 -- iter8: venue chain (ORSD VR4, VR5, VR9).
#
# RML now writes, from `eventtitle`:
#   the conference series   lpwc:conference  conference/<series>          (lpwcp:hasConference)
#   the conference edition  bibo:Conference  conference/<series>/<year>   (bibo:presentedAt)
# with dcterms:isPartOf edition -> series, and the place and year on the edition.
# Here:
#   (a) one name per series: spellings that give the same series key ("EMNLP", "Emnlp") keep
#       the smallest; the others stay as skos:altLabel;
#   (b) the proceedings of a paper are presented at the paper's edition (bibo:presentedAt),
#       when the paper has both a booktitle container and an eventtitle;
#   (c) book series exported as journals (VR9): a fabio:Journal with an ISSN of the reference
#       table mappings/alignments/book-series-issn.json (placeholder KNOWN_SERIES: LNCS, CEUR-WS, CCIS...)
#       is retyped fabio:BookSeries, and named from the table when it has no title.

PREFIX rdf:      <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX dcterms:  <http://purl.org/dc/terms/>
PREFIX foaf:     <http://xmlns.com/foaf/0.1/>
PREFIX skos:     <http://www.w3.org/2004/02/skos/core#>
PREFIX fabio:    <http://purl.org/spar/fabio/>
PREFIX frbr:     <http://purl.org/vocab/frbr/core#>
PREFIX datacite: <http://purl.org/spar/datacite/>
PREFIX bibo:     <http://purl.org/ontology/bibo/>
PREFIX lpwc:     <https://linkedpaperswithcode.com/class/>

PREFIX rdfs:     <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd:      <http://www.w3.org/2001/XMLSchema#>

# (0) literals RML cannot write (morph-kgc 2.10 crashes on FnO literals): the edition's year from
#     its IRI (conference/<series>/<year>), and the series name from its editions' eventtitles,
#     normalised like the FnO function conference_series_name (functions/scilex_udfs.py)
INSERT { ?e dcterms:date ?year }
WHERE {
  ?e a bibo:Conference .
  BIND (STRDT(REPLACE(STR(?e), "^.*/", ""), xsd:gYear) AS ?year)
} ;
INSERT { ?s foaf:name ?name }
WHERE {
  ?s a lpwc:conference ; <urn:scilex:staging#eventtitle> ?l .   # staged by RML, deleted in 99
  BIND (IF(REGEX(?l, "^[A-Za-z][\\w&.\\-]*\\s*('\\d{2}|(19|20)\\d{2})?\\s*:"), STRBEFORE(?l, ":"), ?l) AS ?t0)
  BIND (REPLACE(?t0, "^proceedings of( the)?\\s+", "", "i") AS ?t1)
  BIND (REPLACE(?t1, "\\b(19|20)\\d{2}\\b", " ") AS ?t2)
  BIND (REPLACE(?t2, "'\\d{2}\\b", " ") AS ?t3)
  BIND (REPLACE(?t3, "\\b\\d+(st|nd|rd|th)\\b", " ", "i") AS ?t4)
  BIND (REPLACE(REPLACE(?t4, "-\\d{2}\\b", " "), "(\\s+\\d+)+\\s*$", "") AS ?t5)
  BIND (REPLACE(REPLACE(?t5, "\\s+", " "), "^[\\s,:-]+|[\\s,:-]+$", "") AS ?name)
  FILTER (?name != "")
} ;

# (a) one name per series
DELETE { ?s foaf:name ?n }
INSERT { ?s skos:altLabel ?n }
WHERE {
  { SELECT ?s (MIN(?x) AS ?keep) WHERE { ?s a lpwc:conference ; foaf:name ?x } GROUP BY ?s }
  ?s foaf:name ?n .
  FILTER (?n != ?keep)
} ;

# (b) proceedings presented at the edition
INSERT { ?proc bibo:presentedAt ?ed }
WHERE {
  ?br frbr:partOf ?proc ; bibo:presentedAt ?ed .
  ?proc a fabio:AcademicProceedings .
} ;

# (c) book series exported as journals
DELETE { ?j a fabio:Journal }
INSERT { ?j a fabio:BookSeries }
WHERE {
  VALUES (?issn ?name) {
{{KNOWN_SERIES}}
  }
  ?j a fabio:Journal ; datacite:hasIdentifier ?id .
  FILTER (STRENDS(STR(?id), CONCAT("/id/issn/", ?issn)))
} ;
INSERT { ?j dcterms:title ?name }
WHERE {
  VALUES (?issn ?name) {
{{KNOWN_SERIES}}
  }
  ?j a fabio:BookSeries ; datacite:hasIdentifier ?id .
  FILTER (STRENDS(STR(?id), CONCAT("/id/issn/", ?issn)))
  FILTER NOT EXISTS { ?j dcterms:title ?t }
}
