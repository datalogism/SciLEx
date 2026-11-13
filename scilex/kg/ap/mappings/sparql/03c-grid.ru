# 03c -- iter6: the grid declaration of the collection profile, and one annotation per code.
#
# The collection profile declares, per dimension (mappings/collection-profile.schema.json):
#   values   {type: binary | closed | magnitude | integer | open, list, other_to}  (ORSD UCR4)
#   broader  value -> broader values (hierarchy, skos:broader)                     (UCR20)
#   implies  value -> values a paper coded with it must also have (sxv:implies)   (UCR20, D38)
# mappings/ap_profile.py turns them into the VALUES blocks below ({{GRID_*}}); a profile
# without declarations leaves them empty, and this file then only writes the annotations.
#
# Steps, in order:
#   (a) split: the values of a binary dimension that are not 0 / 1 / placeholders move to the
#       dimension named by other_to, and the paper is also coded 1 (UCD: LINEARIZEDGRAPH_BIN
#       holds formats such as "p(s,o)" in place of 1 -> LINEARIZATION);
#   (b) value type of each declared scheme (sxv:valueType);
#   (c) typed values: rdf:value xsd:boolean (binary 0 / 1), xsd:integer (counts) or
#       xsd:double (orders of magnitude 10^k, key "1e<k>");
#   (d) values outside the declaration -> sxv:OutOfGridValue (general shape out-of-grid-value);
#   (e) skos:broader and sxv:implies between the concepts the rules name, when both exist;
#   (f) AR3: one oa:Annotation per (paper, code): target the paper, body the concept,
#       motivation oa:classifying (oa:tagging for free keywords, TOPIC). The annotator and the
#       date are not in the BibLaTeX export; they come with the survey bundle (iter5, SR8).
#       dcterms:subject is kept as the shortcut the CQs use.
#
# Labels are not there yet (sparql/04 derives them from skos:notation), so this file works on
# IRIs and notations only. Placeholder keys: unknown / not-specified / none (value_key).

PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd:     <http://www.w3.org/2001/XMLSchema#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
PREFIX oa:      <http://www.w3.org/ns/oa#>
PREFIX sxv:     <https://w3id.org/scilex/vocab#>

# (a) split: move the concept and its links, then code the paper 1
DELETE { ?c ?p ?o . ?s ?q ?c }
INSERT {
  ?t a skos:Concept ; skos:inScheme ?target ; skos:notation ?n2 .
  ?target a skos:ConceptScheme ; dcterms:type ?origin .
  ?s ?q ?t .
}
WHERE {
  VALUES (?scheme ?target) {
{{GRID_SPLIT}}
  }
  ?c skos:inScheme ?scheme ; skos:notation ?n .
  BIND (STRAFTER(STR(?c), CONCAT(STR(?scheme), "/")) AS ?key)
  FILTER (?key NOT IN ("0", "1", "unknown", "not-specified", "none"))
  BIND (IRI(CONCAT(STR(?target), "/", ?key)) AS ?t)
  BIND (CONCAT(STRAFTER(STR(?target), "/coding/"), ":", STRAFTER(?n, ":")) AS ?n2)
  OPTIONAL { ?scheme dcterms:type ?origin }
  ?c ?p ?o .
  OPTIONAL { ?s ?q ?c }
} ;
INSERT {
  ?br dcterms:subject ?one .
  ?one a skos:Concept ; skos:inScheme ?scheme ; skos:notation ?n1 .
}
WHERE {
  VALUES (?scheme ?target) {
{{GRID_SPLIT}}
  }
  ?br dcterms:subject ?t .
  ?t skos:inScheme ?target .
  BIND (IRI(CONCAT(STR(?scheme), "/1")) AS ?one)
  BIND (CONCAT(STRAFTER(STR(?scheme), "/coding/"), ":1") AS ?n1)
} ;

# (b) value types
INSERT { ?scheme sxv:valueType ?vt }
WHERE {
  VALUES (?scheme ?vt) {
{{GRID_VALUE_TYPES}}
  }
  FILTER EXISTS { ?anyValue skos:inScheme ?scheme }  # schemes are typed later, in sparql/04 (b)
} ;

# (c) typed values
INSERT { ?c rdf:value ?v }
WHERE {
  ?scheme sxv:valueType ?vt .
  ?c skos:inScheme ?scheme .
  BIND (STRAFTER(STR(?c), CONCAT(STR(?scheme), "/")) AS ?key)
  BIND (IF(?vt = sxv:BinaryValues && ?key IN ("0", "1"), STRDT(IF(?key = "1", "true", "false"), xsd:boolean),
        IF(?vt IN (sxv:MagnitudeValues, sxv:IntegerValues) && REGEX(?key, "^[0-9]+$"), STRDT(?key, xsd:integer),
        IF(?vt = sxv:MagnitudeValues && REGEX(?key, "^1e[0-9]+$"), STRDT(?key, xsd:double), ?unbound))) AS ?v)
  FILTER (BOUND(?v))
} ;

# (d) values outside the declaration
INSERT { ?c a sxv:OutOfGridValue }
WHERE {
  ?scheme sxv:valueType ?vt .
  FILTER (?vt != sxv:OpenValues)
  ?c skos:inScheme ?scheme .
  BIND (STRAFTER(STR(?c), CONCAT(STR(?scheme), "/")) AS ?key)
  FILTER (?key NOT IN ("unknown", "not-specified", "none"))
  FILTER NOT EXISTS { ?c rdf:value ?typed }
  FILTER NOT EXISTS {
    VALUES (?scheme ?key) {
{{GRID_ALLOWED}}
    }
  }
} ;

# (e) hierarchy and implication rules
INSERT { ?n skos:broader ?b }
WHERE {
  VALUES (?n ?b) {
{{GRID_BROADER}}
  }
  ?n a skos:Concept . ?b a skos:Concept .
} ;
INSERT { ?n sxv:implies ?r }
WHERE {
  VALUES (?n ?r) {
{{GRID_IMPLIES}}
  }
  ?n a skos:Concept . ?r a skos:Concept .
} ;

# (f) AR3: one annotation per code
INSERT {
  ?an a oa:Annotation ;
      oa:hasTarget ?br ;
      oa:hasBody ?c ;
      oa:motivatedBy ?motivation .
}
WHERE {
  ?br dcterms:subject ?c .
  ?c a skos:Concept ; skos:inScheme ?scheme .
  BIND (IRI(CONCAT(STR(?br), "/an/", STRAFTER(STR(?c), "/coding/"))) AS ?an)
  BIND (IF(STRENDS(STR(?scheme), "/coding/TOPIC"), oa:tagging, oa:classifying) AS ?motivation)
}
