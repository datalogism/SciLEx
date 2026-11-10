# Proposal: history of a review in the scilex-lpwc-ap profile

Status: draft for the next iteration of
[scilex-lpwc-ap](https://codeberg.org/cringwald/scilex-lpwc-ap) (iteration 1 has a
single `dcat:Dataset` per review and no history). It answers: *when was the Zotero
collection created, what did each export contain, and how did the annotation evolve?*

## What the sources know

| Fact | Available from | Notes |
|---|---|---|
| Paper added / modified in Zotero | Zotero API `dateAdded`, `dateModified` per item | not in the BibLaTeX export: read from the JSON API |
| Library state | Zotero `Last-Modified-Version` (library version number) | identifies exactly what an export read |
| Collection creation | **not recorded by Zotero** | approximated by the earliest `dateAdded` of its papers, or SciLEx's first snapshot |
| When a tag (code) was added | **not recorded by Zotero** | reconstructed by comparing successive snapshots |
| Who annotated | Zotero `meta.createdByUser` / last modifier only | the ORCID of the SciLEx user who exported |
| Profile and mapping used | `scilex/kg/ap/VERSION.json` | `owl:versionIRI` + commit |

So the history must come from **snapshots**: SciLEx already records one
(`annotation_history.jsonl`) at each import, Annotate report and knowledge-graph export.

## Model

Reuses DCAT 3 (versions, series), PROV-O (who / when / what was used) and SKOS (the
coding scheme the profile already has). New terms stay in `sxv:`.

```
<review>                 a dcat:DatasetSeries        the review over time
  ↑ dcat:inSeries
<review>/v/<timestamp>   a dcat:Dataset              one knowledge-graph export
  prov:wasGeneratedBy    <review>/v/<ts>/build       a prov:Activity
                           prov:wasAssociatedWith <https://orcid.org/…>
                           prov:used <zotero source> (sxv:zoteroLibraryVersion 1234)
                           prov:used <https://w3id.org/scilex/ap/lpwc/0.1.0>
  prov:wasRevisionOf     <review>/v/<previous>
  sxv:annotationState    <review>/v/<ts>/state       a sxv:AnnotationState
                           sxv:paperCount 210 ; sxv:annotatedPaperCount 154 ;
                           sxv:pendingPaperCount 31 ; sxv:codeCount 2876 ;
                           sxv:dimensionState [ sxv:dimension <coding/TASK> ;
                                                sxv:annotatedPaperCount 150 ]
<coding/TASK/ner>        prov:generatedAtTime  first snapshot where the code appears
<br/<key>>               dcterms:created / dcterms:modified  (Zotero dateAdded / dateModified)
<review>/subcorpus/<c>   dcterms:created  earliest dateAdded of its papers (approximation)
```

Why these choices:

- **Series + versions** (DCAT 3) rather than one dataset rewritten: each export stays
  citable, and `prov:wasRevisionOf` gives the timeline without a new vocabulary.
- **Counts as a small `sxv:AnnotationState` node** rather than RDF Data Cube: three
  numbers per snapshot and per dimension do not need `qb:` structure definitions; a
  later iteration can map them to `qb:Observation` if a CQ needs slicing.
- **First appearance of a code** on the concept (`prov:generatedAtTime`), computed by
  SciLEx from the snapshots: this is the "annotation level over time" at concept
  granularity, and it prepares AR3 (codes as `oa:Annotation` with annotator and time).

## Competency questions it enables

- *How many papers were annotated at each export?* — `sxv:annotationState` per version.
- *Which dimensions progressed between two exports?* — compare `sxv:dimensionState`.
- *When did the code `TASK:NER` first appear?* — `prov:generatedAtTime` of the concept.
- *Who produced the version used in the paper?* — `prov:wasAssociatedWith` (ORCID).
- *Which Zotero state does a version reflect?* — `sxv:zoteroLibraryVersion`.

## Ontology module (draft for `ontology/modules/30-history.ttl`)

```turtle
@prefix sxv:     <https://w3id.org/scilex/vocab#> .
@prefix owl:     <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:     <http://www.w3.org/2001/XMLSchema#> .
@prefix prov:    <http://www.w3.org/ns/prov#> .
@prefix dcat:    <http://www.w3.org/ns/dcat#> .
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .

sxv:AnnotationState a owl:Class ;
    rdfs:subClassOf prov:Entity ;
    rdfs:label "annotation state"@en ;
    rdfs:comment "How far the coding of a review had gone when a version was produced."@en .

sxv:DimensionState a owl:Class ;
    rdfs:label "dimension state"@en ;
    rdfs:comment "Number of papers coded on one dimension (skos:ConceptScheme) in a state."@en .

sxv:annotationState a owl:ObjectProperty , owl:FunctionalProperty ;
    rdfs:domain dcat:Dataset ; rdfs:range sxv:AnnotationState .
sxv:dimensionState a owl:ObjectProperty ;
    rdfs:domain sxv:AnnotationState ; rdfs:range sxv:DimensionState .
sxv:dimension a owl:ObjectProperty , owl:FunctionalProperty ;
    rdfs:domain sxv:DimensionState ; rdfs:range skos:ConceptScheme .

sxv:paperCount a owl:DatatypeProperty , owl:FunctionalProperty ; rdfs:range xsd:nonNegativeInteger .
sxv:annotatedPaperCount a owl:DatatypeProperty , owl:FunctionalProperty ;
    rdfs:range xsd:nonNegativeInteger ;
    rdfs:comment "Papers with at least one DIMENSION:value code (placeholders excluded)."@en .
sxv:pendingPaperCount a owl:DatatypeProperty , owl:FunctionalProperty ;
    rdfs:range xsd:nonNegativeInteger ;
    rdfs:comment "Papers with at least one DIMENSION:? placeholder left."@en .
sxv:codeCount a owl:DatatypeProperty , owl:FunctionalProperty ; rdfs:range xsd:nonNegativeInteger .

sxv:zoteroLibraryVersion a owl:DatatypeProperty ;
    rdfs:range xsd:nonNegativeInteger ;
    rdfs:comment "Zotero Last-Modified-Version of the library read by an activity."@en .
```

## SHACL (general shapes)

```turtle
sxv:AnnotationStateShape a sh:NodeShape ;
    sh:targetClass sxv:AnnotationState ;
    sh:property [ sh:path sxv:paperCount ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:nonNegativeInteger ] ;
    sh:property [ sh:path sxv:annotatedPaperCount ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:sparql [ sh:message "More annotated papers than papers" ;
                sh:select """SELECT $this WHERE { $this sxv:paperCount ?n ; sxv:annotatedPaperCount ?a .
                                                 FILTER (?a > ?n) }""" ] .

sxv:VersionShape a sh:NodeShape ;
    sh:targetSubjectsOf dcat:inSeries ;
    sh:property [ sh:path prov:wasGeneratedBy ; sh:minCount 1 ] ;
    sh:property [ sh:path ( prov:wasGeneratedBy prov:wasAssociatedWith ) ;
                  sh:minCount 1 ; sh:pattern "^https://orcid.org/" ] .
```

## What SciLEx would do once the profile has it

1. Mint `<review>/v/<timestamp>` at each export; read the previous version from
   `annotation_history.jsonl` for `prov:wasRevisionOf`.
2. Write the activity (ORCID from `user.yml`, Zotero library version from the export
   response header, profile version IRI from `VERSION.json`).
3. Emit the annotation state of the export (already computed for the Overview).
4. Compute each code's first appearance from the snapshot history (needs the codes per
   snapshot: SciLEx would store them, not only the counts).
5. Read `dateAdded` / `dateModified` from the Zotero JSON API for the papers.

Open points for the profile: is a version IRI under the review's base acceptable (vs.
`w3id.org/scilex/data/<review>/<version>/…` for every resource)? Should codes become
`oa:Annotation` (AR3) in the same iteration, which would carry their own time?

## TODO: the workflow journal as PROV-O

The desktop app now records every action on a review in `workflow.jsonl` (see
`scilex/gui/services/journal.py`): one event per line with `at`, `activity`, `agent`
(ORCID iD IRI), `used`, `generated`, `params`, `status`, `message`, and `inferred` for
events reconstructed from older files. This is the data the model above needs. Not
exported yet: the pinned profile (`scilex/kg/ap`, iteration 3) has no history module,
and the knowledge graph must stay valid against its shapes. Once `30-history.ttl`
exists, the export would add, per event:

```
<review>/activity/<n>  a prov:Activity ;
    sxv:activityType "<activity>" ;           # or a SKOS concept per activity
    prov:endedAtTime "<at>"^^xsd:dateTime ;
    prov:wasAssociatedWith <agent> ;          # omitted when empty
    prov:used <zotero library IRI> , <profile version IRI> ;
    prov:generated <review>/v/<timestamp> ;   # for export-kg events
    sxv:inferred true .                       # reconstructed events
```

`rename` and `adopt-output` stay local (file layout, not research provenance); job
events keep only completed ones with their `history_key`.

## Annotation workflow and citation metrics (to add to the profile)

SciLEx now writes, as Zotero tags, the annotation workflow of each paper
(`ANNOT:<id>` assigned, `ANNOT_VALID_BY:<id>` validated against the grid,
`DELETED_BY:<who>` discarded, `AGREEMENT_COPY:<key>` an annotator's copy in an
agreement study) and its citation metrics (`CITATIONS:10^n`, `REFERENCES:10^n`,
`CITATIONS_PER_YEAR:10^n`, `CITED_IN_CORPUS:10^n`, `PAGERANK:top5%`, `QUALITY:80`,
`VENUE_RANK:A*`). Until the profile has terms for them, the knowledge-graph export
treats them as automation tags (dropped from the codes; discarded papers and
copies are left out of the graph). Candidate terms:

- `sxv:assignedTo` / `sxv:validatedBy` (range `foaf:Agent`, ORCID IRI when known) on
  the paper's coding, with `prov:generatedAtTime` from the journal;
- the agreement study as a `prov:Activity` with one `sxv:AgreementMeasure` per
  dimension (`sxv:dimension`, `sxv:krippendorffAlpha` xsd:decimal,
  `sxv:distance "MASI"`, `sxv:paperCount`);
- metrics as observations on the paper (`sxv:citationCount`, `sxv:referenceCount`,
  `sxv:citationsPerYear`, `sxv:inCorpusCitationCount`, `sxv:pageRank`) attached to
  the citation snapshot they were computed from (`prov:wasDerivedFrom`
  `zotero_citations.json`, with its read date).
