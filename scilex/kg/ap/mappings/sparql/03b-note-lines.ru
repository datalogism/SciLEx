# 03b -- `Key: value` lines of the note (iter4, A7; ORSD IR4, UCR11).
#
# Zotero can only hold some values in Extra, which its BibLaTeX export writes as
# `note`. SciLEx's push (scilex/Zotero/zotero_api.py) writes, after the citation dict:
#   Archive ID: <arXiv abs URL>     -> arXiv identifier (datacite:arxiv) of the paper
#   PDF URL: <url>                  -> a second embodiment br/<key>/re/pdf (application/pdf),
#                                      typed fabio:DigitalManifestation (iter5) so that shapes
#                                      can tell it from the bibliographic embodiment re/1
#   Papers with Code: <url>         -> owl:sameAs the Linked Papers With Code paper when it
#                                      is a paperswithcode.com/paper/<slug> URL;
#                                      rdfs:seeAlso otherwise (SciLEx falls back to the HF URL)
#   HF URL: <url>                   -> rdfs:seeAlso (older SciLEx pushes)
# and curated libraries hold
#   OpenAlex: W<digits>             -> rdfs:seeAlso <https://openalex.org/W...>
#
# Not mapped (documented in mappings/README.md): Zotero's own `Series Title:`,
# `Series:`, `Publication Title:`, `Version Number:`, `original-date:` lines.
#
# Zotero joins the lines with a space or a line break, so each value is read up to
# the next whitespace. The note itself is a staging triple (RML), deleted in 99.

PREFIX dcterms:  <http://purl.org/dc/terms/>
PREFIX rdfs:     <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:      <http://www.w3.org/2002/07/owl#>
PREFIX fabio:    <http://purl.org/spar/fabio/>
PREFIX frbr:     <http://purl.org/vocab/frbr/core#>
PREFIX datacite: <http://purl.org/spar/datacite/>
PREFIX literal:  <http://www.essepuntato.it/2010/06/literalreification/>

# Archive ID: http://arxiv.org/abs/2104.09617v1 (arXiv only; other archives are not mapped)
INSERT {
  ?br datacite:hasIdentifier ?id .
  ?id a datacite:Identifier ;
      datacite:usesIdentifierScheme datacite:arxiv ;
      literal:hasLiteralValue ?arxiv .
}
WHERE {
  ?br <urn:scilex:staging#note> ?note .
  FILTER (REGEX(?note, "(^|\\s)Archive ID: *(https?://(www\\.)?arxiv\\.org/abs/|arXiv:)[A-Za-z0-9./_-]+"))
  BIND (REPLACE(?note, "^(.*\\s)?Archive ID: *(https?://(www\\.)?arxiv\\.org/abs/|arXiv:)([A-Za-z0-9./_-]+).*$", "$4", "s") AS ?arxiv)
  BIND (IRI(CONCAT("{{BASE}}id/arxiv/", ?arxiv)) AS ?id)
} ;

# PDF URL: <url>
INSERT {
  ?br frbr:embodiment ?re .
  ?re a fabio:Manifestation, fabio:DigitalManifestation ;
      frbr:exemplar ?url ;
      dcterms:format "application/pdf" .
}
WHERE {
  ?br <urn:scilex:staging#note> ?note .
  FILTER (REGEX(?note, "(^|\\s)PDF URL: *https?://"))
  BIND (REPLACE(?note, "^(.*\\s)?PDF URL: *(https?://\\S+).*$", "$2", "s") AS ?u)
  FILTER (REGEX(?u, "^https?://[^<>\"{}|^`\\\\]+$"))
  BIND (IRI(?u) AS ?url)
  BIND (IRI(CONCAT(STR(?br), "/re/pdf")) AS ?re)
} ;

# Papers with Code: <url>  /  HF URL: <url>
INSERT { ?br ?link ?target }
WHERE {
  VALUES ?key { "Papers with Code" "HF URL" }
  ?br <urn:scilex:staging#note> ?note .
  FILTER (REGEX(?note, CONCAT("(^|\\s)", ?key, ": *https?://")))
  BIND (REPLACE(?note, CONCAT("^(.*\\s)?", ?key, ": *(https?://\\S+).*$"), "$2", "s") AS ?u)
  FILTER (REGEX(?u, "^https?://[^<>\"{}|^`\\\\]+$"))
  BIND (REGEX(?u, "^https?://(www\\.)?paperswithcode\\.com/paper/[^/?#]+/?$") AS ?pwc)
  BIND (IF(?pwc, owl:sameAs, rdfs:seeAlso) AS ?link)
  BIND (IF(?pwc, IRI(CONCAT("https://linkedpaperswithcode.com/paper/",
                     REPLACE(?u, "^https?://(www\\.)?paperswithcode\\.com/paper/([^/?#]+)/?$", "$2"))),
           IRI(?u)) AS ?target)
} ;

# OpenAlex: W4301270504
INSERT { ?br rdfs:seeAlso ?oa }
WHERE {
  ?br <urn:scilex:staging#note> ?note .
  FILTER (REGEX(?note, "(^|\\s)OpenAlex: *W[0-9]+"))
  BIND (IRI(CONCAT("https://openalex.org/", REPLACE(?note, "^(.*\\s)?OpenAlex: *(W[0-9]+).*$", "$2", "s"))) AS ?oa)
}
