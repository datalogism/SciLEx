# Boucle juge GUI — 2026-10-29

Mandat : boucle juge → corrections sur la GUI seule, au moins 10 itérations, arrêt quand le juge
ne trouve plus rien de majeur. Tout en local (aucun push), commits sur `dev`.

Majeur = bug, perte de données, utilisateur bloqué, ou résultat scientifiquement faux. Le reste est mineur.

## Méthode
- Juge = agent neuf à chaque itération ; il lance l'appli réelle (`scilex-gui --browser --no-open --port 8765`)
  avec un HOME isolé (registre neuf, pas de keys.yml) et une copie de `~/Memory` comme revue de démo,
  et la pilote avec Playwright headless (`uvx --from playwright python`).
- Script de lancement : `<scratchpad>/judge/start_gui.sh` (redémarre sur le code courant).

## Itérations
(voir ci-dessous, une section par itération : remarques majeures, corrections, commits)

### Itération 1 — 1 majeur, 12 mineurs
- M1 squelette blank `years: [2024, 2026]` (saute 2025) → plage `2024-2026` (a102a8ef)
- m8 « Create » n'ouvrait pas la revue (dialogue supprimé dans son propre handler ; la simulation NiceGUI ne le voit pas) → suppression différée (a102a8ef)
- m1 « Delete and run » + annulation laissait l'ancien CSV agrégé → déplacé dans `previous_results/` ; m2 reprise compte les requêtes partielles (f4198784)
- m10 avertissement collecte partielle sous Last results ; log vide masqué ; Screen (hauteur, Score, aide raccourcis) ; aides m3/m5 ; message d'annulation m4 (45a2368c)
- Écartés : m12 (Papers with Code relancé, ADR 0006) ; m9 barre « Completed » non reproduite (100 % au code) ; m11 Arxiv 0 papier à revérifier
- Hors GUI, préexistant : `tests/test_webapi_year_column.py` échoue à la collecte (lit le vrai keys.yml)

### Itération 2 — 1 majeur, 10 mineurs
- M1 collecte sans aucun article (clé refusée, réseau coupé) affichée « Completed » → échec avec cause par API, bouton API keys, Queries = requêtes finies (b0c9a1e0). Vérifié avec un proxy injoignable.
- m1/m2 Configure : avertissements mots-clés d'exemple, max ≤ 0, années < 1900 ; m5 accessibilité : anneau de focus (box-shadow, `.no-outline` de Quasar gagne sur outline), couleurs primary/warning AA, lang, titre d'onglet par écran
- Reportés : m4 multi-onglets (compteurs périmés), m6 BibTeX `series` = ISSN et URI Turtle example.org (hors GUI), m7 décisions de Screen absentes du PRISMA, m8 résumé Citations, m9 labels non liés

### Itération 3 — 0 majeur (arrêt anticipé), 12 mineurs
- Vérifiés OK : hors ligne → Failed, reprise après annulation, Arxiv 0 = vrai zéro, éditeur YAML, fichiers corrompus.
- Corrigés (6976369f) : erreurs de fichiers abîmés lisibles (nom + remède), message unique sur Configure cassé,
  Screen (note perdue signalée, « showing N of T », raccourcis après le filtre), barre rouge sur Failed.

## État : boucle terminée (le juge 3 ne trouve plus rien de majeur)
Restent (mineurs, à reprendre si besoin) :
- Snowball : candidats en DOI bruts, « (5) » non expliqué ; Keywords : clusters singletons listés, termes déjà dans la recherche ;
  PwC dry run sans détail ; Graph : libellés de champs tronqués, étiquettes de nœuds superposées ; Charts : « Collect_KW1/2 »,
  décisions de Screen ignorées.
- Screen : orphelins en clé brute, Forget sans confirmation ; boutons sous le pli à 1024×700 ; compteurs périmés dans un 2e onglet.
- PRISMA sans les décisions de Screen ; BibTeX `series` = ISSN ; URI Turtle example.org (hors GUI) ; labels flottants non liés.
