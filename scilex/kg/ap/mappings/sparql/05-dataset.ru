# 05 -- Dataset-level metadata (DCAT + PROV), as OCDM does for its own datasets.
# One dataset per collection; {{...}} filled from the collection profile
# (contract: mappings/ap_profile.py PLACEHOLDERS).
#
# iter4: minimal provenance (ORSD LR5, LR7, CFG1, CFG6, CFG7), so that SciLEx no longer
# adds these triples after the mapping:
#   * dcterms:creator / prov:wasAttributedTo the review owner ({{CREATOR}}, an ORCID iD;
#     no triple when empty);
#   * prov:wasGeneratedBy one mapping activity, associated with the software that ran it
#     ({{GENERATOR}}, a prov:SoftwareAgent with its version) and using this profile
#     version ({{PROFILE_VERSION_IRI}}) and, when given, the configuration in force,
#     identified by its hash only ({{CONFIG_HASH}}; never its content or secrets);
#   * dcterms:conformsTo the profile and its version.
# The source file IRI uses {{SOURCE_IRI}} (percent-encoded), its label {{SOURCE}} (text).

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
      dcterms:conformsTo <https://w3id.org/scilex/ap/lpwc> , <{{PROFILE_VERSION_IRI}}> ;
      prov:wasDerivedFrom <{{BASE}}source/{{SOURCE_IRI}}> ;
      prov:wasGeneratedBy <{{BASE}}activity/mapping> .

  <{{BASE}}source/{{SOURCE_IRI}}>
      a prov:Entity ;
      rdfs:label "{{SOURCE}} (Zotero BibLaTeX export)"@en .

  <{{BASE}}activity/mapping>
      a prov:Activity ;
      rdfs:label "Mapping of {{SOURCE}} to the scilex-lpwc-ap profile"@en ;
      prov:used <{{BASE}}source/{{SOURCE_IRI}}> , <{{PROFILE_VERSION_IRI}}> ;
      prov:wasAssociatedWith <{{BASE}}agent/generator> .

  <{{BASE}}agent/generator>
      a prov:SoftwareAgent ;
      rdfs:label "{{GENERATOR}}" .

  <{{PROFILE_VERSION_IRI}}>
      a prov:Entity ;
      rdfs:label "scilex-lpwc-ap application profile, version IRI"@en .
} ;

# the review owner, when the profile gives one
INSERT {
  <{{BASE}}> dcterms:creator ?creator ; prov:wasAttributedTo ?creator .
  <{{BASE}}activity/mapping> prov:wasAssociatedWith ?creator .
  ?creator a prov:Agent .
}
WHERE {
  BIND ("{{CREATOR}}" AS ?c)
  FILTER (?c != "")
  BIND (IRI(?c) AS ?creator)
} ;

# the configuration in force, by its hash only (CFG1, CFG7)
INSERT {
  <{{BASE}}activity/mapping> prov:used ?config .
  ?config a prov:Plan , prov:Entity ;
      rdfs:label "Configuration in force (identified by its hash; its content is not exported)"@en ;
      dcterms:identifier ?h .
}
WHERE {
  BIND ("{{CONFIG_HASH}}" AS ?h)
  FILTER (?h != "")
  BIND (IRI(CONCAT("{{BASE}}config/", ENCODE_FOR_URI(?h))) AS ?config)
}
