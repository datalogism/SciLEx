# 01 -- Literal clean-up: typed publication dates, page split, DOI normalisation.
# (Literal-valued derivations live here because morph-kgc 2.10 cannot emit
#  literal FnO results -- see rml/scilex-bib.rml.ttl header.)

PREFIX xsd:      <http://www.w3.org/2001/XMLSchema#>
PREFIX prism:    <http://prismstandard.org/namespaces/basic/2.0/>
PREFIX datacite: <http://purl.org/spar/datacite/>
PREFIX fabio:    <http://purl.org/spar/fabio/>
PREFIX literal:  <http://www.essepuntato.it/2010/06/literalreification/>

# Dates: "2022-10-25" -> xsd:date, "2023-05" -> xsd:gYearMonth, "2020" -> xsd:gYear
DELETE { ?s prism:publicationDate ?d }
INSERT { ?s prism:publicationDate ?typed }
WHERE {
  ?s prism:publicationDate ?d .
  FILTER (isLiteral(?d) && DATATYPE(?d) = xsd:string)
  BIND (STR(?d) AS ?v)
  BIND (IF(REGEX(?v, "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), STRDT(?v, xsd:date),
        IF(REGEX(?v, "^[0-9]{4}-[0-9]{2}$"),          STRDT(?v, xsd:gYearMonth),
        IF(REGEX(?v, "^[0-9]{4}$"),                   STRDT(?v, xsd:gYear), ?d))) AS ?typed)
} ;

# Pages: "8472--8487" -> start 8472 / end 8487 ; "102563" (article number) -> start only
INSERT { ?re prism:startingPage ?start }
WHERE {
  ?re prism:pageRange ?r .
  BIND (REPLACE(STR(?r), "^\\s*([^-–]+?)\\s*([-–].*)?$", "$1") AS ?start)
  FILTER (?start != "" && UCASE(?start) != "NA")
} ;
INSERT { ?re prism:endingPage ?end }
WHERE {
  ?re prism:pageRange ?r .
  FILTER (REGEX(STR(?r), "[-–]"))
  BIND (REPLACE(STR(?r), "^.*[-–]+\\s*(\\S+)\\s*$", "$1") AS ?end)
  FILTER (?end != "")
} ;

# DOI literal values: lower-case, strip resolver prefixes ("https://doi.org/", "doi:")
DELETE { ?id literal:hasLiteralValue ?raw }
INSERT { ?id literal:hasLiteralValue ?norm }
WHERE {
  ?id datacite:usesIdentifierScheme datacite:doi ;
      literal:hasLiteralValue ?raw .
  BIND (REPLACE(REPLACE(LCASE(STR(?raw)), "^(https?://)?(dx\\.)?doi\\.org/", ""), "^doi:", "") AS ?norm)
  FILTER (?norm != STR(?raw))
}
;

# iter3: identifiers minted from IRIs only (ISSNs found in `series`): add the identifier
# node (OCDM id) with its scheme and value, taken from the IRI id/issn/<value>.
INSERT {
  ?id a datacite:Identifier ;
      datacite:usesIdentifierScheme datacite:issn ;
      literal:hasLiteralValue ?v .
}
WHERE {
  ?br datacite:hasIdentifier ?id .
  FILTER (CONTAINS(STR(?id), "/id/issn/"))
  FILTER NOT EXISTS { ?id literal:hasLiteralValue ?any }
  BIND (STRAFTER(STR(?id), "/id/issn/") AS ?v)
} ;

# iter2: ISSN / ISBN identify the container (journal, proceedings, book) the item
# is part of, not the item itself: move them there when there is a container.
DELETE { ?br datacite:hasIdentifier ?id }
INSERT { ?venue datacite:hasIdentifier ?id }
WHERE {
  ?br datacite:hasIdentifier ?id ; <http://purl.org/vocab/frbr/core#partOf> ?venue .
  ?id datacite:usesIdentifierScheme ?scheme .
  VALUES ?scheme { datacite:issn datacite:isbn }
} ;

# iter3: a journal article whose only venue information is an ISSN (raw SciLEx
# exports have no journaltitle, ORSD UCR11 / VR2) is part of a journal identified by
# that ISSN. The journal has no title: the raw export does not give one.
INSERT {
  ?j a fabio:Journal ; datacite:hasIdentifier ?id .
  ?br <http://purl.org/vocab/frbr/core#partOf> ?j .
}
WHERE {
  { SELECT ?br (MIN(?v) AS ?issn) WHERE {
      ?br a fabio:JournalArticle ; datacite:hasIdentifier ?i .
      ?i datacite:usesIdentifierScheme datacite:issn ; literal:hasLiteralValue ?v .
      FILTER NOT EXISTS { ?br <http://purl.org/vocab/frbr/core#partOf> ?venue }
    } GROUP BY ?br }
  BIND (IRI(CONCAT("{{BASE}}br/venue/journal/issn-", ?issn)) AS ?j)
  ?br datacite:hasIdentifier ?id .
  ?id datacite:usesIdentifierScheme datacite:issn .
} ;
DELETE { ?br datacite:hasIdentifier ?id }
WHERE {
  ?br a fabio:JournalArticle ; <http://purl.org/vocab/frbr/core#partOf> ?j ; datacite:hasIdentifier ?id .
  ?j a fabio:Journal ; datacite:hasIdentifier ?id .
}
