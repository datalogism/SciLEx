# Command-line reference

Every command runs from the folder holding the review's `scilex.yml` and accepts
`--config PATH` and `--keys PATH`. `python -m scilex <command>` is the module entry point
for `collect`, `aggregate`, `status`, `enrich`, `export-bibtex`, `push-zotero`, `init`
and `config`.

| Command | Module | What it does |
|---|---|---|
| `scilex init` / `scilex-init [--template NAME]` | [Workspace](../modules/workspace.md) | write a `scilex.yml` (templates: computer-science, machine-learning, bioinformatics, clinical-medicine, social-sciences) |
| `scilex config check` | [① Configure](../modules/configure.md) | validate `scilex.yml` and `keys.yml` |
| `scilex config show` | ① Configure | effective values and where each comes from |
| `scilex config migrate [--write] [--from DIR]` | ① Configure | convert the old three-file configuration |
| `scilex-collect [--resume NAME] [--since DATE]` | [② Collect](../modules/collect.md#collection) | query the APIs |
| `python -m scilex status` | ② Collect | completeness of a collection |
| `scilex-aggregate [--skip-citations] [--workers N] [--collection NAME --use-current-config]` | [② Collect](../modules/collect.md#aggregation) | deduplicate, filter, rank |
| `scilex-enrich` | [⑥ Enrich](../modules/enrich.md#papers-with-code) | Papers with Code metadata |
| `scilex-enrich-citations` | [⑥ Enrich](../modules/enrich.md#citations) | citation data of an aggregated file |
| `scilex-snowball [--separate-file]` | [⑤ Extend](../modules/extend.md#snowballing) | snowball sampling on the citation network |
| `scilex-seed --dois … / --doi-file F / --bibtex F` | [⑤ Extend](../modules/extend.md#snowballing) | start from seed papers |
| `scilex-suggest-keywords` | [⑤ Extend](../modules/extend.md#keyword-suggestions) | keywords from the paper clusters |
| `scilex-report` | [⑦ Analyses](../modules/analyses.md#charts) | charts of the aggregated papers |
| `scilex-analyze` | [⑦ Analyses](../modules/analyses.md#graph) | citation graphs and communities |
| `scilex-summarize` | [⑦ Analyses](../modules/analyses.md#summaries) | community reports |
| `python -m scilex.report_annotations` | [④ Annotate](../modules/annotate.md#annotation-report) | annotation tags of a Zotero library |
| `scilex-export-bibtex` | [⑧ Export](../modules/export.md#bibtex) | BibTeX file |
| `scilex-export-turtle` | [⑧ Export](../modules/export.md#rdf-turtle) | RDF/Turtle |
| `scilex-push-zotero` | [⑧ Export](../modules/export.md#zotero-push) | push to a Zotero collection |
| `scilex-build-kg [--bib F] [--orcid ID] [--base-iri IRI] [--output-dir DIR] [--no-validate]` | [⑧ Export](../modules/export.md#knowledge-graph) | knowledge graph with scilex-lpwc-ap |
| `python -m scilex.kg.sync_profile [--check] [--local DIR]` | ⑧ Export | refresh the pinned application profile |
| `scilex-gui [--browser] [--port N] [--no-open] [--self-test]` | [Desktop app](../user-guides/gui.md) | start the desktop application |

Run any command with `--help` for all its options.
