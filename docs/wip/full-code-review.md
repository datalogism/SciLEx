# Review + refactor complet du package `scilex`

Démarré : 2026-10-23. Branche : `dev`. Base : 972 tests verts, 1 skip. Politique : ADR 0001.

## Prochaine étape
Vague 2 terminée. Go donné à la session `scilex-d8` (lots A-D, ADR 0002) ; refonte config (ADR 0003) :
C1 `scilex/settings/` fusionné (8269b2ee, écarts notés dans l'ADR 0003), C2 (câblage CLI/config.py/exemples/doc) après les lots de scilex-d8.
Ensuite : découpage de `run_aggregation`, `run_enrichment` en cœur, CLAUDE.md, review finale.
Agents : Sonnet désormais (demande utilisateur).

## Piège
Les worktrees d'agents (`isolation: worktree`) partent d'`origin/main`, pas de `dev` :
chaque brief commence par `git reset --hard dev`.

## Constats principaux (review du 2026-10-23)
### Bugs
- BibTeX : `escape_bibtex` double-échappe (`%`, `&`, `~` cassés) ; url/keywords/authors non échappés ; suffixe de clé > 26 collisions invalide ; `format_pages` ignore les tirets Unicode.
- Citations : `--no-cache` utilise quand même un cache par défaut non initialisé ; échecs OpenCitations mis en cache 30 j ; retries tenacity jamais déclenchés ; DOI non normalisés (casse, préfixe) ; checkpoint chargé à chaque run (`resume_from=False is not None`) ; checkpoint « dernier index » qui saute des papiers.
- Pipeline : mots-clés à casse mixte jamais trouvés dans l'abstract (mode 1 groupe) ; fallbacks de citations inopérants (init `""`) ; validation d'abstract faite 2 fois avec 2 définitions ; `is_valid(list)` lève ; merge config `quality_filters: null` plante, deep-merge non récursif.
- Agrégation : DOI non nettoyés pour PubMed/PMC ; erreurs de convertisseurs avalées en debug ; nombreux `row["x"]` non gardés ; `txt_filters=False` renvoie un DataFrame vide ; archive gagnante mal déduite en double fusion DOI+titre.
- Collecte : `rate_limits` de la config jamais lus (mauvais chemin) ; Springer compte double ; requête crashée marquée complète ; buffer de pages perdu sur exception ; clés API loguées en debug ; erreurs PubMed avalées => troncature silencieuse.
- HF : `bert` capture roberta/scibert… ; `github_repo` inventé ; rate-limit appliqué aussi aux hits de cache.
- Zotero : échecs partiels comptés comme succès ; `ZoteroAPI("", "", "")` lève ; token d'écriture régénéré aux retries (doublons) ; collections non paginées (>100).
- Web : traversée de chemin via `collect_name` (sauf DELETE) ; logs de jobs mélangés (handler sur root) ; jobs concurrents écrasent `scilex.config.yml` ; transitions d'état non synchronisées ; clés API renvoyées au navigateur ; CORS `*` + bind 0.0.0.0.
### Duplication / code mort
- `aggregate_collect.py` n'est pas mince : moteur de citations (~750 l.) à déplacer dans `citations/fetcher.py`.
- 13 gabarits de 18 clés copiés dans `aggregate.py` ; boucle de pagination copiée 3 fois ; PubMed/PMC quasi identiques.
- Chargeur CSV agrégé triplé ; listes d'API triplées côté web ; dédup legacy O(n²) mort ; `run_job_collects`, `post_item`, etc. morts.
- CLAUDE.md : `scilex-init`, export Turtle, `scilex/rdf/`, `citations/fetcher.py` n'existent pas.

## Lots
- Vague 1 (depuis dev, fichiers disjoints de la fusion) : V1-A BibTeX · V1-B citations (cache/tools) · V1-C HuggingFace · V1-D API web.
- Vague 2 (après fusion) : convertisseurs `aggregate.py` · `aggregate_parallel` · collecteurs/base · moteur de citations + pipeline · Zotero/push + chargeur partagé · doc CLAUDE.md.

## État
- [x] Lint autofix (adab616b)
- [x] Review (6 zones)
- [x] Fusion origin/main (b363563b) — fonctionnalités portées dans `scilex/pipeline/`
- [x] Vague 1 : BibTeX, citations (cache/tools), HuggingFace, API web — 1151 tests
- [x] Vague 2 : convertisseurs, dédup, collecteurs, citations/fetcher, pipeline/config, Zotero/io — 1329 tests, ruff propre
- [x] Config C1 (`scilex/settings/`) fusionné
- [x] Config C2 fusionné (b910a1a7, 1737 tests) : resolve.py point unique, --config/--keys sur 14 CLI, scilex init/config, VPN, webapi
- [x] Lot docs/README fusionné (ce84d309, fb6b78ea) ; CLAUDE.md local mis à jour (gitignoré)
- [x] run_enrichment (17094a5d) ; scilex-86 parallélise _enrich_rows
- [x] Découpe run_aggregation (eabf1772) + correctifs bypass/rapport vide (888fa63f, 80eea6d6) ; HF parallèle par scilex-86
- [x] Revue finale : 10 défauts vérifiés (traces brutes sur config invalide, bool→int, --threshold ignoré, env CrossRef/Unpaywall/openrouter, dict vide efface preset, migrate invalide, validations tardives, advanced fusionné sur snapshot, VPN figé, env ignorée côté web)
- [x] Corrections des 10 défauts fusionnées (9c43feb2, 1836 tests) ; vérifié à la main : erreurs lisibles, suggestions, code 1

## État : chantier terminé. Décisions utilisateur (2026-10-23) : clés web créées dans ~/.config/scilex/keys.yml (fait) ; seuils de citations restent fixés dans le code ; workers HF exposés (fait) ; pas de push.
- Ouvert (choix) : webapi crée encore scilex/api.config.yml si ~/.config/scilex/keys.yml absent ; seuils CitationFilterConfig non configurables
