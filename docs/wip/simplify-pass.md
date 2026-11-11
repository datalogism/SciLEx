# /simplify — passe qualité sur tout `scilex/`

Démarré : 2026-10-23 (session scilex-86). Revue en lecture seule faite (4 angles : réutilisation,
simplification, efficacité, altitude) sur `dev` @ f759b795.

## État
- [x] Revue (4 agents), constats dédupliqués ci-dessous
- [x] S1 helpers (`94db50d8`) + lots crawlers / pipeline / sorties-webapi appliqués et fusionnés dans dev
  (1688 tests, ruff propre). Couvre S1, S3 (hors rate-limit), S4 (hors HF, getquality), S5 (hors config, code mort testé).
- [x] `quality_scores` vectorisé dans `crawlers/aggregate.py` (51aa4910) ; branchement dans orchestrator fait par scilex-90 (lot run_aggregation).
- [x] Sans objet : chargeur YAML unique (fait par C2, `settings/resolve.py`) ; rate-limit déjà injecté (vague 2).
- [x] HF en pool de threads (afc6ca08) : `EnrichmentOptions.workers` (défaut 4), ordre et stats sur le thread principal ; ×4 sur latence simulée.
- [x] Décisions utilisateur (oui/oui) : champ `PipelineRequest.filter_config` retiré (classe `FilterConfig` gardée, utilisée par `/filter`) ; fonctions seulement testées supprimées (cache par DOI, `getCrossRefCitation`, `filter_by_abstract_quality`, `get_all_stats`/`reset_all`, `cleanup_expired`). Chantier terminé.
- Volontairement gardés (changeraient les sorties) : `export_to_bibtex.extract_year` (4 chiffres quelconques),
  split auteurs Zotero (garde les vides), `report_charts.load_data`, année webapi en float,
  `_MISSING_MARKERS` d'abstract_enrichment ("N/A", "MISSING"), alternance de regex d'abstract_validation.
- Changements de bord assumés : préfixes `doi:`/`dx.doi.org` désormais retirés partout ; années 18xx acceptées
  et entiers hors 1800–2099 rejetés par le pré-filtre d'année ; `\b` autour de l'année dans doi_recovery.

Hors périmètre ici (déjà suivi dans full-code-review.md) : gabarits 18 clés d'`aggregate.py`,
pagination ×3, PubMed/PMC, dédup legacy, `run_aggregation`, `run_enrichment`, chargeur CSV agrégé.

## Lots proposés (ordre d'application)

### S1 — Helpers partagés dans `constants.py` (racine de S2–S4)
- `normalize_doi` est la seule implémentation : remplacer `aggregate.clean_doi`, `abstract_enrichment._clean_doi`,
  la chaîne `.replace` d'`aggregate_parallel` (~l.445), les slices `[16:]/[15:]` de `pipeline/enrichment.py:39`.
  Ajouter `doi_to_url()` (Zotero `_doi_to_url`, enrichment, `web_interface` ~l.991).
  ⚠ `clean_doi` garde la casse : vérifier l'impact sur la dédup (ADR 0001 §4 assume déjà la minuscule).
- `extract_year(value) -> int | None` : remplace `_year_from_date`, `report_charts._extract_year` (regex 18xx divergente),
  `export_to_bibtex.extract_year`, `pd.to_datetime(...).dt.year` répété en webapi.
- `parse_archive_apis(value)` (promouvoir la version d'`aggregate_parallel` ~l.692) : ~10 copies `split(";")`+`*`.
- `split_semicolon_field(value)` : auteurs/mots-clés (bibtex, Zotero, quality_validation, aggregate_parallel).
- Marqueurs manquants : remplacer les ensembles locaux (`report_charts`, `aggregate_parallel:71`, `itemtype_filter:85`,
  `abstract_enrichment._MISSING_MARKERS`) par `is_missing` ; étendre `is_missing` une fois si "N/A"/"MISSING" existent vraiment.

### S2 — Normaliser à la frontière des convertisseurs (altitude)
- `finalize_record(record, api)` appliqué une fois dans le dispatcher `FORMAT_CONVERTERS` : archive, DOI, date, itemType.
  Coordonner avec la vague 2 (convertisseurs `aggregate.py`) — peut déjà y être.
- Filtre d'année : filtrer après conversion sur `date` normalisée → supprime `_RAW_YEAR_FIELDS`/`_extract_raw_year`.
- `abstract_enrichment._extract_doi/_abstract_field` : travailler sur l'enregistrement converti.

### S3 — Polymorphisme des collecteurs
- `base._get_recovery_actions` : hook `auth_failure_hints()` surchargé par elsevier/ieee/springer.
- `collector_collection` : passer `api_config[api]` à chaque collecteur (fin du constructeur 4 args Elsevier),
  `is_placeholder()` partagé, `INVALID_TOKENS` hors boucle.
- `queryCompositor` : une seule passe (`setdefault`), `semantic_scholar_mode` lu par le collecteur SS.
- Rate limit / `api.config.yml` lu une fois (injecté ou `lru_cache`) au lieu d'une lecture YAML par collecteur.
- Getters Java-style (`get_url`, `get_api_name`, `get_dataDir`…) → attributs ; `Filter_param` en `@dataclass` ;
  `_state_snapshot()` (base `runCollect` + `openalex.py`).
- `_sanitize_error_message` → `sanitize_secrets` direct.

### S4 — Efficacité pipeline (vectorisation)
- Filtre texte : minuscules une fois par enregistrement et une fois par liste de mots-clés
  (`text_filter` → `keyword_validation.check_keyword_in_text*`) ; ×K normalisations aujourd'hui.
- `ranking.calculate_relevance_score` : sortir poids/mots-clés de l'apply ligne à ligne, vectoriser.
- `pipeline/enrichment.py` : fusionner fallbacks SS/OpenAlex en `_fill_unset(df, target, source, label)` vectorisé ;
  URL depuis DOI via masque.
- `getquality` (orchestrator ~l.386) : réutiliser `_compute_dedup_quality` vectorisé.
- `iterrows` → masques/`itertuples` : `quality_validation.filter_by_quality`, `keyword_validation`, `duplicate_tracking` ×3.
- `abstract_validation` : regex précompilées en alternance unique.
- HF : `enrich_with_hf` séquentiel → pool de threads borné par `_throttle` (vérifier thread-safety ; plus gros gain en temps réel).

### S5 — Config & code mort
- Un seul chargeur YAML (`SciLExConfig`) : `crawlers/utils.load_all_configs`, `export_to_bibtex.load_config`,
  `webapi` ×2, `vpn/rotator`, `orchestrator:225`.
- Supprimer (vérifier par grep au moment d'appliquer) : `text_filter.keyword_matches_in_abstract`,
  `webapi FilterConfig` + champ `filter_config` (⚠ forme de l'API — ADR 0001 §3, décision utilisateur),
  `_process_batch_worker`, `Filter_param.get_dict_param`, `set_state`, params `check_language`/`expected_language`,
  `adaptive_rate_limiter.extra_delay`, dossiers vides (`graph_analysis`, `snowball`, `summarize`, `keyword_suggestions`).
  À trancher (seulement testés) : `filter_by_abstract_quality`, `get_cached_citation`/`cache_citation`,
  `getCrossRefCitation`, `circuit_breaker.get_all_stats/reset_all`, `hf_client.cleanup_expired`.
- `_process_batch` : tuple `*rest` → paramètres nommés (`partial`).
- `web_interface` : helper `select_collection()` (onglets 2/3/4), cache du `read_csv` par `(path, mtime)`.
- `abstract_validation` : stats via `Counter` ; `AbstractQualityScore.quality_score` dérivable (optionnel).

### Différés / à décider
- Webapi qui réorchestre collect→aggregate→enrich (`run_collection_task`) et `/export` qui n'appelle pas
  `export_to_bibtex` : dépend de `run_enrichment` (vague 2).
- Déplacer la logique BibTeX/Zotero hors des CLI (`scilex/export/`) : à arbitrer avec le lot B de scilex-d8 (#33).
- `parallel_process_papers` en threads pour du CPU (GIL) : à mesurer avant de simplifier.
- Fusion des retry/Retry-After (base, Zotero, citations_tools, abstract_enrichment) : comportements différents, partiel.
