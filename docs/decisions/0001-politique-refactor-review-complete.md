# 0001 — Politique du refactor issu de la review complète (2026-10-23)

## Contexte
Review complète du package `scilex` (6 zones). `origin/main` contenait un commit
(0910a0cc, VPN + rapport d'agrégation) absent de `dev`, touchant les mêmes fichiers.

## Décision
1. **Intégrer d'abord `origin/main` dans `dev`**, en portant ses fonctionnalités dans
   l'architecture 3 couches de `dev` (logique dans `scilex/pipeline/`, CLI minces), qui fait foi.
2. **Corriger les bugs avérés**, chacun avec un test qui échouait avant.
3. **Ne pas changer les formats de sortie** sans nécessité : colonnes et ordre du CSV agrégé,
   séparateur `;`, vocabulaire `rights` hétérogène, colonne `extra` (repr Python),
   arborescence `output/<collect>/<API>/<idx>/page_N`, endpoints et payloads de l'API web,
   flags CLI, noms publics importés par les tests ou `webapi`.
4. Changements de comportement **assumés** car ce sont des corrections :
   - DOI normalisés (préfixe doi.org retiré, minuscules) pour cache, CrossRef et dédup ;
   - les échecs (timeout/erreur) de citations ne sont plus mis en cache ;
   - `github_repo` n'est plus inventé à partir de l'identifiant HF ;
   - échappement BibTeX en une passe (fin du double échappement) ;
   - noms de collection validés côté API web (anti traversée de chemin), écoute sur 127.0.0.1 par défaut.
5. Hors périmètre (à décider plus tard) : persistance des jobs web, enregistrement d'ORKG/OpenAIRE
   dans la collecte, migration OpenCitations v2, normalisation du vocabulaire `rights`.

## Conséquences
Tests verts à chaque lot, fusion `--ff-only` dans `dev`. Les constats détaillés et l'avancement
sont dans `docs/wip/full-code-review.md`.
