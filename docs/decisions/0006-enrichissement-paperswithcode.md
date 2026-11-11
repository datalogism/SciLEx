# 0006 — Enrichissement via Papers with Code au lieu de HuggingFace (2026-10-28)

## Contexte
L'étape optionnelle `scilex-enrich` interrogeait HuggingFace (`/api/papers/search`,
`/api/papers/{id}`, `/api/arxiv/{id}/repos`, puis la recherche de modèles en repli) pour
ajouter `tags`, `hf_url` et `github_repo`. Papers with Code a été relancé sur
`paperswithcode.co` avec une API publique anonyme (`/api/v1`) qui renvoie, par article,
tâches, méthodes, benchmarks évalués, dépôts GitHub (drapeau officiel, étoiles), conférence.
C'est plus riche et plus ciblé pour une revue de littérature que les modèles HF qui *citent*
l'article.

## Décision
- **Source unique : Papers with Code** (`https://paperswithcode.co/api/v1`). HuggingFace est
  retiré de l'enrichissement (plus de repli « Models API »), la dépendance
  `huggingface-hub` est supprimée.
- **Recherche** : identifiant arXiv d'abord (DOI `10.48550/arXiv.*`, URL arxiv.org) via
  `GET /papers/arxiv/{id}?include_resources=true` ; sinon `GET /papers/search?q=<titre>` +
  appariement flou du titre (`TitleMatcher`, seuil 85), puis
  `GET /papers/{id}?include_resources=true`. Seules les données extraites sont mises en cache
  (SQLite, TTL 30 j), pas les réponses brutes (un article peut lister des centaines de dépôts).
- **Tags** (préfixes existants conservés pour BibTeX/RDF/Zotero) : `tasks` → `TASK:`,
  `methods` → `PTM:`/`ARCHI:`, `evaluated_benchmarks` → `DATASET:`,
  `introduced_frameworks` → `FRAMEWORK:`, étoiles du dépôt retenu → `GITHUB_STARS:`.
  `github_repo` = dépôt officiel, sinon le plus étoilé.
- **Colonne** `pwc_url` (`https://paperswithcode.co/paper/<arxiv_id|id>`) remplace `hf_url`.
  Les exports lisent `pwc_url`, avec repli sur `hf_url` pour les CSV agrégés existants.
  BibTeX : champ `pwcurl` ; RDF : `scilex:papersWithCodeUrl` (le mapping `hfurl` reste lu).
- **Configuration** : `enrichment.paperswithcode` (`true` ou
  `{enabled, fuzzy_match_threshold, cache_path, cache_ttl_days, workers}`, cache par défaut
  `output/pwc_cache.db`). `enrichment.huggingface` reste accepté, avec avertissement, et est
  traduit vers `paperswithcode` (`use_papers_api` ignoré) ; les deux à la fois = erreur.
  Dict legacy interne : `pwc_enrichment` ; `hf_enrichment` lu en repli.
- **Clés** : aucune (API anonyme). `HuggingFace.token` reste accepté dans `keys.yml` mais
  n'est plus utilisé ni proposé (exemples, GUI).
- **Modules** : `scilex/PapersWithCode/` (client, `title_matcher`, `tag_formatter`),
  `scilex/pipeline/enrichment_pwc.py`, `scilex/enrich_with_pwc.py`. La commande
  `scilex-enrich` garde son nom.

## Conséquences
- Les articles hors catalogue PwC (hors ML surtout) ne sont plus enrichis ; c'était déjà
  le cas avec HF Daily Papers.
- Les anciens CSV/`scilex.yml` restent lisibles sans action ; `scilex config migrate`
  écrit la nouvelle clé.
- Débit : 5 req/s côté client ; PwC renvoie `Retry-After` sur 429/503.
