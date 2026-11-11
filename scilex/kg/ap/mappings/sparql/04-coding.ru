# 04 -- Review coding scheme: SKOS labels + lifting into Linked Papers With Code.
#
# RML gives each coding concept (coding/<DIM>/<key>) its raw tags as skos:notation
# ("TASK:NER", "TASK:Ner"). Here:
#   (a) skos:altLabel = value part of every raw tag; skos:prefLabel = MIN(altLabel)
#   (b) concept schemes typed
#   (c) LPWC lifting: TASK -> lpwcp:hasTask, DATASET -> lpwcp:usesDataset,
#       PTM / MODEL -> lpwcp:hasModel, ARCHI -> lpwcp:hasMethod,
#       DATASET_CREATED -> lpwcp:introducedBy on the matching DATASET concept.
#       Placeholder values (unknown / not-specified / none) are not lifted.

PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
PREFIX foaf:    <http://xmlns.com/foaf/0.1/>
PREFIX lpwc:    <https://linkedpaperswithcode.com/class/>
PREFIX lpwcp:   <https://linkedpaperswithcode.com/property/>

# (a) labels
INSERT { ?c skos:altLabel ?alt }
WHERE {
  ?c a skos:Concept ; skos:notation ?n .
  BIND (IF(CONTAINS(?n, ":"), STRAFTER(?n, ":"),
        IF(REGEX(?n, "^[A-Za-z_]+/"), STRAFTER(?n, "/"), ?n)) AS ?raw)
  BIND (IF(?raw = "", "?", ?raw) AS ?alt)
} ;
INSERT { ?c skos:prefLabel ?pref }
WHERE {
  { SELECT ?c (MIN(?alt) AS ?pref) WHERE { ?c a skos:Concept ; skos:altLabel ?alt } GROUP BY ?c }
} ;
DELETE { ?c skos:altLabel ?pref }
WHERE { ?c skos:prefLabel ?pref ; skos:altLabel ?pref } ;

# (b) schemes
INSERT { ?s a skos:ConceptScheme }
WHERE { ?c skos:inScheme ?s } ;

# (c) LPWC lifting
INSERT { ?br ?lpwcProp ?c . ?c a ?lpwcClass ; foaf:name ?label . ?br a lpwc:paper }
WHERE {
  VALUES (?scheme ?lpwcProp ?lpwcClass) {
    (<{{BASE}}coding/TASK>    lpwcp:hasTask     lpwc:task)
    (<{{BASE}}coding/DATASET> lpwcp:usesDataset lpwc:dataset)
    (<{{BASE}}coding/PTM>     lpwcp:hasModel    lpwc:model)
    (<{{BASE}}coding/MODEL>   lpwcp:hasModel    lpwc:model)
    (<{{BASE}}coding/ARCHI>   lpwcp:hasMethod   lpwc:method)
  }
  ?br dcterms:subject ?c .
  ?c skos:inScheme ?scheme ; skos:prefLabel ?label .
  FILTER (!REGEX(STR(?c), "/(unknown|not-specified|none)$"))
} ;

INSERT {
  ?d a skos:Concept , lpwc:dataset ;
     skos:inScheme <{{BASE}}coding/DATASET> ;
     lpwcp:introducedBy ?br .
  ?created skos:exactMatch ?d .
}
WHERE {
  ?br dcterms:subject ?created .
  ?created skos:inScheme <{{BASE}}coding/DATASET_CREATED> .
  BIND (IRI(REPLACE(STR(?created), "/DATASET_CREATED/", "/DATASET/")) AS ?d)
} ;
INSERT { ?d skos:prefLabel ?l ; foaf:name ?l }
WHERE {
  ?created skos:exactMatch ?d ; skos:prefLabel ?l .
  FILTER NOT EXISTS { ?d skos:prefLabel ?any }
} ;
# iter2: a DATASET concept that exists only because of a DATASET_CREATED tag keeps
# the raw spelling(s) of that tag (X-DigCheck run 1: 14 concepts without skos:notation)
INSERT { ?d skos:notation ?n }
WHERE {
  ?created skos:exactMatch ?d ; skos:notation ?n .
  ?d skos:inScheme <{{BASE}}coding/DATASET> .
  FILTER NOT EXISTS { ?d skos:notation ?any }
} ;

# PTM and MODEL code the same kind of thing: align equal keys
INSERT { ?a skos:exactMatch ?b }
WHERE {
  ?a skos:inScheme <{{BASE}}coding/PTM> .
  ?b skos:inScheme <{{BASE}}coding/MODEL> .
  FILTER (STRAFTER(STR(?a), "/coding/PTM/") = STRAFTER(STR(?b), "/coding/MODEL/"))
}
