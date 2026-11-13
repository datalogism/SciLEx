# 06 -- iter7: name the journals known only by their ISSN (ORSD VR2, VR8).
#
# rml/survey-venues.rml.ttl stages, per paper, the venue name SciLEx collected
# (<urn:scilex:staging#venueName>, survey bundle part `venues`). A journal with no title takes
# the name its papers carry; when they disagree, the most frequent name, then the smallest.
# The name is marked as coming from the survey bundle (dcterms:source), not from the
# bibliography. Without a bundle there are no staging triples and nothing changes.

PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX fabio:   <http://purl.org/spar/fabio/>
PREFIX frbr:    <http://purl.org/vocab/frbr/core#>

INSERT { ?j dcterms:title ?name ; dcterms:source ?bundle }
WHERE {
  {
    SELECT ?j (MIN(?nm) AS ?name) WHERE {
      { SELECT ?j (MAX(?n) AS ?top) WHERE {
          { SELECT ?j ?nm2 (COUNT(DISTINCT ?br2) AS ?n) WHERE {
              ?br2 frbr:partOf ?j ; <urn:scilex:staging#venueName> ?nm2 .
              ?j a fabio:Journal .
              FILTER NOT EXISTS { ?j dcterms:title ?t }
            } GROUP BY ?j ?nm2 }
        } GROUP BY ?j }
      { SELECT ?j ?nm (COUNT(DISTINCT ?br) AS ?c) WHERE {
          ?br frbr:partOf ?j ; <urn:scilex:staging#venueName> ?nm .
          ?j a fabio:Journal .
          FILTER NOT EXISTS { ?j dcterms:title ?t2 }
        } GROUP BY ?j ?nm }
      FILTER (?c = ?top)
    } GROUP BY ?j
  }
  BIND (<{{BASE}}survey> AS ?bundle)
}
