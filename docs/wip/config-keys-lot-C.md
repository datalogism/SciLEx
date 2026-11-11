# Clés de configuration du Lot C

## api.config.yml (fichier local, non versionné)
```yaml
openrouter:
  api_key: "sk-or-..."   # ou variable d'env OPENROUTER_API_KEY
```

## scilex.config.yml : bloc `llm_screening` (#42, opt-in)
| Clé | Défaut | Rôle |
|-----|--------|------|
| enabled | false | active l'étape (après filtres qualité, avant citations) |
| topic | "" | description du sujet de recherche (obligatoire si enabled) |
| model | openai/gpt-4o-mini | modèle OpenRouter |
| threshold | null | exclut les papiers dont llm_relevance_score < seuil |
| max_papers | 500 | plafond de papiers (non cachés) envoyés au LLM |
| workers | 4 | concurrence |
| price_input_per_m / price_output_per_m | 0.15 / 0.60 | USD par million de tokens, pour l'estimation |

Cache : `output/<collect>/llm_relevance_cache.json`.

## scilex-seed (#18, #4)
Aucune nouvelle clé de config. Utilise `SemanticScholar.api_key` (api.config.yml), `quality_filters`,
`collect_name` (sortie `output/<collect_name>_seed/`, ou `--collect-name`), `aggregate_file`,
`keywords`/`bonus_keywords` (seulement avec `--keyword-filter`).
Options CLI : `--dois`, `--doi-file`, `--bibtex`, `--limit`, `--snowball`, `--keyword-filter`, `--collect-name`.

## scilex-export-turtle --citation-graph (#35)
Aucune clé de config. Options CLI : `--citation-graph`, `--no-doi-metadata`. Utilise `SemanticScholar.api_key`
et `CrossRef.mailto` (api.config.yml). Sortie `output/<collect>/citation_graph.ttl`; caches `citations_cache.json`
et `doi_turtle_cache.json`. Note : la négociation de contenu doi.org (`Accept: text/turtle`) ne renvoie que les
métadonnées du DOI, pas ses citations ; les arêtes `bibo:cites` viennent de reference_fetcher.
