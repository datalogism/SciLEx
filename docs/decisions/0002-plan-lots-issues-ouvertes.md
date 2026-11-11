# 0002 — Plan de traitement des issues ouvertes par lots

Date : 2026-10-23 — Statut : accepté

## Contexte

21 issues ouvertes (toutes `enhancement`). La branche `feat/bibtex2rdf` (10 commits d'avance sur `dev`)
implémente déjà #25, #46, #50, #32, #43. `origin/main` a 1 commit d'avance (VPN + aggregation graph).
`feature/biorxiv` a 2 commits d'avance.

## Décisions transverses

- Ordre : Lot 0 → A → B → C → D.
- Livraison : une branche + une PR par lot vers `dev`, avec `Closes #N`.
- LLM : OpenRouter (API compatible OpenAI), modèle dans `scilex.config.yml`, clé dans `api.config.yml`.

## Lot 0 — Intégration

- Fusionner `feat/bibtex2rdf` dans `dev` (worktree, tests), synchroniser `origin/main`.
- Ferme #25, #46, #50, #32, #43.

## Lot A — Qualité des données

- #47 : `canonical_citation_count`, priorité Semantic Scholar > OpenAlex > CrossRef > valeur collectée ;
  log des écarts au-delà d'un seuil configurable.
- #36 : récupération de DOI via CrossRef (titre + 1er auteur, fuzzy ≥ 90 %) pour **tous** les papiers sans DOI, opt-in.
- #44 : enrichissement opt-in `oa_type` (Unpaywall), sans impact sur le score.
- #45 : enrichissement opt-in `first_author_hindex` / `last_author_hindex` (SS `/author/batch`), sans impact sur le score.
- #3 : classement des venues via CORE (conférences) + SCImago SJR (revues), CSV embarqués + script de mise à jour.
  Pas d'Impact Factor (propriétaire).

## Lot B — Pipeline et ergonomie

- #33 : export du score de `ranking.py` — tag Zotero `scilex:score:N` (arrondi), champ `relevance_score` en BibTeX et RDF.
- #31 : clé `since: YYYY-MM-DD` (+ option `--since`), filtre natif par API sinon post-filtre, fusion sans doublons.
- #49 : `prisma_report.md` avec diagramme Mermaid à chaque exécution.
- #48 : `scilex-init --template <domaine>` (bioinformatics, machine-learning, clinical-medicine,
  computer-science, social-sciences) + `profile save`.
- #6 : une clé ou une liste de clés par API dans `api.config.yml`, round-robin, bascule sur 429/401.

## Lot C — IA et recherche

- #42 : `llm_relevance_score` (0–1) après le filtre mots-clés, seuil d'exclusion opt-in,
  estimation du coût affichée avant exécution.
- #18 + #4 : mode « seed papers » — DOI ou BibTeX en entrée → SS Recommendations API + snowball (#50) → filtres habituels.
- #35 : export Turtle du graphe de citations via citation.doi.org dans `output/{collection}`.

## Lot D — Nouvelles API

- #16 : fusionner `feature/biorxiv` ; fermer le reste (couvert par OpenAlex + PubMed, ChemRxiv sans API).
- #30 : note de faisabilité (AIDA, OpenCitations Index) ; ORKG et OpenAIRE déjà couverts.

## Conséquences

Lot C dépend du Lot 0 (snowball, graph_analysis). #33 et #3 touchent tous deux `ranking.py` : à traiter
dans cet ordre (A avant B). Toute nouvelle fonction réseau est opt-in et testée avec des appels HTTP mockés.
