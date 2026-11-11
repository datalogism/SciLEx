# 05 -- Dataset-level metadata (DCAT + PROV), as OCDM does for its own datasets.
# iter3: one dataset per collection; {{...}} filled from mappings/collections/<slug>.json.

PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX dcat:    <http://www.w3.org/ns/dcat#>
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>

INSERT DATA {
  <{{BASE}}>
      a dcat:Dataset ;
      dcterms:title "{{TITLE}}"@en ;
      dcterms:description "{{DESCRIPTION}} Mapped to the scilex-lpwc-ap application profile (OCDM/SPAR + Linked Papers With Code)."@en ;
      rdfs:label "{{USE_CASE}}: {{SLUG}}" ;
      dcterms:conformsTo <https://w3id.org/scilex/ap/lpwc> ;
      prov:wasDerivedFrom <{{BASE}}source/{{SOURCE}}> .

  <{{BASE}}source/{{SOURCE}}>
      a prov:Entity ;
      rdfs:label "{{SOURCE}} (Zotero BibLaTeX export)"@en .
}
