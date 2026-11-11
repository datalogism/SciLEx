# Nouvelles clés de config — Lot A

Toutes dans `quality_filters` (scilex.advanced.yml) pour l'instant ; section suggérée du futur `scilex.yml` entre parenthèses.

| Clé | Type | Défaut | Rôle | Section |
|---|---|---|---|---|
| `canonical_citation_discrepancy_threshold` | float | 0.5 | Écart relatif entre sources de citations au-delà duquel un WARNING est loggé (#47) | citations |
| `recover_missing_dois` | bool | false | Opt-in : DOI manquants via CrossRef titre+1er auteur (#36) | enrichment |
| `doi_recovery_min_similarity` | float | 0.90 | Similarité de titre minimale (0-1) pour accepter un DOI (#36) | enrichment |
| `enrich_unpaywall` | bool | false | Opt-in : colonne `oa_type` via Unpaywall (#44) | enrichment |
| `unpaywall_email` | str | "" | Email exigé par Unpaywall ; repli sur `api_config.Unpaywall.email` ; désactivé si absent (#44) | enrichment |
| `enrich_author_hindex` | bool | false | Opt-in : `first_author_hindex`/`last_author_hindex` via Semantic Scholar (#45) | enrichment |
| `use_venue_ranking` | bool | false | Opt-in : colonne `venue_rank` (CORE/SJR) et mélange 50/50 avec le score de type dans `ranking.py` (#3) | ranking |

Nouvelles colonnes : `canonical_citation_count` (toujours calculée après citations), `oa_type`, `first_author_hindex`, `last_author_hindex`, `venue_rank`.
Clé API optionnelle : `api_config.Unpaywall.email`.

> Note d'intégration (orchestrateur) : ces clés ne figurent PAS dans `get_default_quality_filters()` ni
> dans `QUALITY_FILTER_SCHEMA`, pour préserver l'invariant legacy ↔ `scilex/settings` (tests de scilex-90).
> Elles sont lues via `quality_filters.get(<clé>, DEFAULT_<CLÉ>)`. À intégrer au schéma lors de C2.
