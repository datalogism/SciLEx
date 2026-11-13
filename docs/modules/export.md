# ⑧ Export

<img src="../_static/modules/export.png" alt="Export module" height="80">

Export is the last step. Choose the papers — only those marked *included* in
[③ Screen](screen.md), or all of them — then a format. File exports go to the review's
`exports/` folder with the scope and a timestamp in their name; the path is shown at the
end with a button to reveal it, and previous exports are listed.

| Sub-module | What it writes | Command line |
|---|---|---|
| <a href="#bibtex"><img src="../_static/modules/sub/export-bibtex.png" height="30" alt="BibTeX"></a> | `.bib` with PDF links | `scilex-export-bibtex` |
| <a href="#csv"><img src="../_static/modules/sub/export-csv.png" height="30" alt="CSV"></a> | `;`-separated table with decisions | — |
| <a href="#rdf-turtle"><img src="../_static/modules/sub/export-turtle.png" height="30" alt="RDF/Turtle"></a> | SciLEx's BIBO vocabulary | `scilex-export-turtle` |
| <a href="#zotero-push"><img src="../_static/modules/sub/export-zotero.png" height="30" alt="Zotero push"></a> | Items in the review's Zotero group | `scilex-push-zotero` |
| <a href="#knowledge-graph"><img src="../_static/modules/sub/export-kg.png" height="30" alt="Knowledge graph"></a> | scilex-lpwc-ap graph, SHACL-checked | `scilex-build-kg` |

## BibTeX

One entry per paper with the core fields, a direct PDF link in `file` when one is
known, identifiers, the APIs that found it, and the Papers with Code fields. See the
[BibTeX reference](../reference/bibtex-export.md).

## CSV

The results table, `;`-separated, with the screening decision and note of each paper.

## RDF/Turtle

The papers in SciLEx's own BIBO-based vocabulary, with citation links when known.

## Zotero push

Pushes the papers to the review's [Zotero group](zotero.md#zotero-group) (its
collection, or a collection named after the review); duplicates are skipped. Disabled
until the Zotero key is set in [API keys](workspace.md#api-keys). The push asks for
confirmation with the number of papers and the target. Once papers are linked, later
changes travel both ways with the [sync](zotero.md#sync).

## Knowledge graph

Exports every paper of the review's Zotero source as BibLaTeX (tags with the
annotations, Extra with the citation lists) and maps it with the
[scilex-lpwc-ap](https://codeberg.org/cringwald/scilex-lpwc-ap) application profile
(OpenCitations/SPAR + Linked Papers With Code):

- the coding dimensions come from the review's `annotation_grid.csv` (deduced from the
  `DIMENSION:value` tags when there is none), plus SciLEx's own tags (`Collect_KW*`,
  `QUALI_SCORE`, `REL_SCORE`, `CITAT`, `HavePDF`…). Optional grid columns declare more
  (see [the grid declaration](#grid-declaration));
- sub-collections become sub-corpora (`void:subset`);
- your ORCID iD is the creator; the base IRI is
  `https://w3id.org/scilex/data/<review-slug>/` at the first export, then kept in
  `review_state.yml` (`kg_base`): renaming the review does not change it;
- agreement copies are left out. Discarded papers are left out too, until the profile
  maps the bundle's exclusions; they are then kept and flagged;
- no API key ever reaches the graph: the values of your keys file and key-like texts
  are looked for, and the export warns if one is found;
- the graph is checked against the profile's SHACL shapes.

### Survey bundle

Besides the bibliography, the export writes `kg/bundle/survey.json`: what the review
records and Zotero does not. It holds the configuration and criteria versions, the grid,
the collection roles, the members, the screening decisions (with who decided), the
exclusions and their causes, the assignments, the paper types and who set them, the
agreement studies, the journal, the annotation history, the paper log, the venues,
scores, metrics and enrichment values. Its `parts` list says, for each part, whether it
is present, absent (step never run), empty or withheld. The profile maps the parts it
knows (iteration 8: the venues, which names the journals known only by their ISSN).

**Disclosure** chooses what the bundle shows:

| Level | Shows | For |
|---|---|---|
| Public (default) | members named only with their consent (else `agent/<n>`); no screening note; no annotator's own codes; no event parameters | a file you share or publish |
| Team | names, notes, each annotator's codes of the agreement studies | the review team |
| Full | also the parameters of every journal event | yourself, a backup |

A member agrees to be named in ④ Annotate → Annotators (**Named in public dumps**).

### Grid declaration

Optional columns of `annotation_grid.csv` declare the values of each dimension (profile
iteration 6):

| Column | Content |
|---|---|
| `type` | `binary`, `closed`, `magnitude`, `integer` or `open` |
| `values` | the values of a `closed` dimension: `a, b, c` (else the `Allowed values` column) |
| `broader` | value hierarchy: `ner > ie; re > ie` |
| `implies` | rules: `dataset-created > dataset; …` (a paper with the left value must have the right ones) |
| `other_to` | for a `binary` dimension, the dimension its other values go to |
| `lpwc` | LPWC role: `task`, `dataset`, `model` or `method` (default: from the name, `SAT_TASK` → `task`) |

Written to `output/<name>/kg/`: `<name>.ttl`, the `.bib` it came from,
`bundle/survey.json` and `<name>.shacl.ttl/.txt`. A knowledge graph can start a new
review (**New review → From a knowledge graph**, see [Workspace](workspace.md#reviews)).

```bash
scilex-build-kg                      # from the review folder
scilex-build-kg --bib export.bib     # map a BibLaTeX file instead of exporting from Zotero
scilex-build-kg --orcid 0000-0002-1825-0097 --no-validate --output-dir DIR
scilex-build-kg --disclosure team    # public (default), team or full
```

### The application profile

SciLEx ships a pinned copy of the profile in `scilex/kg/ap/` (`VERSION.json` says which
commit). Maintainers refresh it with `python -m scilex.kg.sync_profile` (latest release,
else newest tag, else the default branch; `--check` only compares; `--local DIR`
installs from a local checkout), review the diff, and run `pytest tests/test_kg.py`.

From iteration 4 on, the profile ships its mapping interface
(`mappings/ap_profile.py`): SciLEx writes the review's *collection profile* (its grid,
creator, configuration hash, survey bundle), and the profile's own code merges it with
the profile's defaults and fills every template placeholder. The dataset description,
creator and sub-corpora then come from the mapping itself. Iteration 3 profiles are
templates SciLEx fills; for iteration 1 profiles, SciLEx rewrites the sample review's
values instead. Either way it stops with an error if a profile version no longer has the
shape it expects. Status, metric and agreement terms not yet in the profile are
proposed in the [provenance proposal](../kg/provenance-proposal.md).
