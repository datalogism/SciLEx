# GUI desktop SciLEx — design

Date : 2026-10-23 · Statut : validé (brainstorming) · Prochaine étape : plan d'implémentation du lot 0

## Objectif

Une application de bureau installable (double-clic) qui permet à des chercheurs **non développeurs** de mener une revue de littérature complète avec SciLEx, sans terminal ni `uv` : configurer, collecter, trier, exporter, analyser.

Public : chercheurs non développeurs. Plateformes : macOS, Windows, Linux.

## Décisions

| Sujet | Décision |
|---|---|
| Forme | Application de bureau native (pas web, pas TUI) |
| Pile | NiceGUI en mode natif (fenêtre pywebview), packagée avec PyInstaller |
| Distribution | Installeurs macOS (`.app`/`.dmg`), Windows (`.exe`), Linux (AppImage), construits par GitHub Actions (une machine par OS, PyInstaller ne cross-compile pas) |
| Signature | Aucune en v1 ; instructions d'ouverture documentées (clic droit → Ouvrir sur macOS, « Informations complémentaires » sur SmartScreen) |
| Enrichissement HuggingFace | Inclus : il passe par `huggingface-hub` (client HTTP léger), sans `torch` ni `transformers` (vérifié dans `pyproject.toml` et les imports) |
| Navigation | Accueil « Mes revues », puis barre latérale des étapes du pipeline dans une revue |
| Interface Streamlit existante | Conservée jusqu'à parité fonctionnelle, retirée ensuite (décision séparée) |
| Fichiers | Les mêmes que la CLI : `scilex.yml` par revue, `~/.config/scilex/keys.yml` ; on passe librement de la CLI à l'app |

Alternatives écartées : PySide6 (beaucoup plus de code par écran, graphes et graphiques à ajouter, pas de réutilisation de FastAPI) ; Tauri + front JS + Python sidecar (trois chaînes d'outils pour un seul mainteneur).

## Architecture

```
SciLEx.app / .exe / .AppImage (PyInstaller)
  fenêtre native (pywebview) ⇄ NiceGUI / FastAPI (dans le même processus, localhost)

  scilex/gui/
    app.py          point d'entrée `scilex-gui` ; multiprocessing.freeze_support() en tout premier ; option --self-test
    pages/          un module par écran ; affichage uniquement
    components/     barre latérale des étapes, formulaires générés depuis pydantic, tableau d'articles, panneau de job
    services/       logique sans dépendance à l'UI, testable sans fenêtre
      workspace.py  lister / créer / ouvrir des revues (dossier + scilex.yml) ; registre des revues connues
      jobs.py       JobRunner : threads, progression, annulation, capture des logs (extrait de webapi/scilex_api.py)
      screening.py  décisions de tri et notes
    state.py        revue courante, job actif

  pipeline existant inchangé : settings/, pipeline/orchestrator.py, citations/, export_to_bibtex.py, Zotero/, rdf/, …
```

Règles :
- `pages/` n'appelle que `services/` et les fonctions publiques existantes (`run_collection(progress_callback, cancel_event)`, `run_aggregation`, `resolve_legacy_configs`, modèles de `settings/schema.py`). Aucune modification du pipeline n'est nécessaire pour la progression.
- Registre des revues connues : un fichier YAML dans le dossier de configuration utilisateur propre à l'OS (`platformdirs`).
- Dépendances dans un extra optionnel `gui` (`nicegui`, `pywebview`, `platformdirs`) ; la CLI ne les exige pas.

## Écrans et flux de données

| Écran | Rôle | Lit / écrit |
|---|---|---|
| Accueil « Mes revues » | Cartes (nom, nombre d'articles, % trié, job en cours) ; « Nouvelle revue » (choix du dossier + modèle via `init_templates`) ; « Ouvrir un dossier existant » | registre, `scilex.yml` |
| ① Configurer | Sections Recherche, Filtres, Citations, Classement, Tri LLM ; formulaires générés depuis les modèles pydantic ; validation en direct ; badge d'origine par valeur (défaut / preset / fichier) | `scilex.yml` (seules les valeurs différentes des défauts sont écrites) |
| 🔑 Clés API | Un champ par API, lien « obtenir une clé », bouton de test | `~/.config/scilex/keys.yml` |
| ② Collecter | Bouton Lancer ; progression par API puis phases d'agrégation ; panneau de logs ; Annuler ; options « sans citations » et `--since` | `output/<nom>/…`, `aggregated_results.csv` |
| ③ Trier | Tableau AG Grid (titre, année, venue, score, citations) ; panneau de détail (résumé, lien DOI) ; Inclure / Exclure / Peut-être + note ; raccourcis I/E/M et ↑↓ ; filtre par décision | `screening.csv` |
| ④ Exporter | BibTeX, CSV, Turtle, push Zotero ; « inclus seulement » ou « tout » | fichiers d'export, Zotero |
| ⑤ Analyses | Sous-pages : rapport et graphiques, snowball, graphe de co-auteurs, résumés, suggestions de mots-clés | sorties existantes de chaque commande |

Décisions de tri : fichier séparé `output/<nom>/screening.csv` avec les colonnes `paper_key, decision, note, updated_at`. `paper_key` = DOI normalisé, sinon titre normalisé + année. Une ré-agrégation n'efface jamais les décisions ; les décisions dont l'article a disparu sont affichées comme orphelines.

Activation progressive : une étape est grisée tant que la précédente n'a pas produit ses fichiers (pas de `aggregated_results.csv` → Trier, Exporter et Analyses désactivés, avec la raison affichée).

## Gestion des erreurs

- Configuration invalide : erreur pydantic affichée sur le champ concerné ; Lancer bloqué tant que la validation échoue.
- Clé manquante ou API en panne : disjoncteur et pool de clés existants inchangés ; statut par API (réussie / partielle / échouée + raison) ; la collecte continue avec les autres API.
- Plantage d'un job : statut « échoué », log complet consultable et copiable, application toujours utilisable ; une collecte interrompue propose « Reprendre » (`--resume`).
- Un seul job à la fois par revue (règle existante `_collection_has_active_job`).
- Erreur inattendue : gestionnaire global, dialogue avec « Copier le diagnostic » (version, OS, traceback) ; logs dans le dossier de logs propre à l'OS.

## Tests

- `services/` : pytest classique, fonctions du pipeline mockées, pas d'appel réseau (convention de `tests/`).
- Pages : fixture `User` de NiceGUI (tests simulés sans navigateur) sur le parcours critique : créer une revue → configurer → lancer (mocké) → trier → exporter.
- Packaging : workflow GitHub Actions, matrice macOS / Windows / Ubuntu ; construction du bundle puis exécution de l'exécutable en `--self-test` (imports, modèles `templates/*.yml` trouvés, multiprocessing fonctionnel, sortie propre, sans affichage).

## Découpage en lots

Chaque lot a son propre cycle spec → plan → implémentation.

| Lot | Contenu |
|---|---|
| 0. Fondation | Squelette `scilex/gui/`, point d'entrée et extra `gui` ; fenêtre, accueil, barre latérale avec pages vides ; `services/jobs.py` extrait et testé ; écran Collecter minimal branché dessus ; spec PyInstaller, `--self-test`, workflow CI produisant les 3 artefacts ; ADR « GUI desktop NiceGUI » |
| 1. Configurer | Éditeur `scilex.yml` et clés `keys.yml` |
| 2. Lancer | Collecte, agrégation et citations avec suivi complet |
| 3. Trier | Tableau, décisions, notes, `screening.csv` |
| 4. Exporter | BibTeX, CSV, Turtle, Zotero |
| 5. Analyses | Rapport, snowball, graphes, résumés, suggestions de mots-clés, enrichissement HF |

v1 = lots 0 à 4. Le lot 5 se livre analyse par analyse.

Le packaging est dans le lot 0 volontairement : les pièges de PyInstaller (fichiers de données absents, imports cachés, multiprocessing qui relance l'application) apparaissent seulement sur le bundle et coûtent bien moins cher à corriger sur une application vide.

## Hors périmètre v1

Signature et notarisation des installeurs, mise à jour automatique, usage multi-utilisateur ou serveur.
