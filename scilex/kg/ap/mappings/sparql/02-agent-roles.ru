# 02 -- Ordered agent roles (OCDM): link each role to the next one of the same
# list (ar/<key>/<field>/<n>  oco:hasNext  ar/<key>/<field>/<n+1>).

PREFIX oco: <https://w3id.org/oc/ontology/>
PREFIX pro: <http://purl.org/spar/pro/>
PREFIX sxv: <https://w3id.org/scilex/vocab#>

INSERT { ?a oco:hasNext ?b }
WHERE {
  ?br pro:isDocumentContextFor ?a , ?b .
  ?a sxv:position ?p .
  ?b sxv:position ?q .
  FILTER (?q = ?p + 1)
  # same list = same IRI up to the position segment (author vs editor vs bookauthor)
  FILTER (REPLACE(STR(?a), "/[0-9]+$", "") = REPLACE(STR(?b), "/[0-9]+$", ""))
}
;

# iter2: the publisher role's IRI only depends on the citation key, so RML mints it
# even for entries without a publisher. Remove roles held by nobody (and the
# links to them). Found by X-DigCheck in iter1 (63 roles without pro:isHeldBy).
DELETE { ?r ?p ?o . ?br pro:isDocumentContextFor ?r }
WHERE {
  ?r a pro:RoleInTime ; ?p ?o .
  FILTER NOT EXISTS { ?r pro:isHeldBy ?agent }
  OPTIONAL { ?br pro:isDocumentContextFor ?r }
}
