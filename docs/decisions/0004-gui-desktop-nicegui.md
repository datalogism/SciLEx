# 0004 — GUI desktop : NiceGUI natif + PyInstaller (2026-10-23)

## Contexte
SciLEx s'utilise en ligne de commande, plus une interface web Streamlit + FastAPI
(`scilex/webapi/`) qui ne couvre que collecte, agrégation, filtrage et export. Objectif : que des
chercheurs **non développeurs** mènent une revue complète (configurer, collecter, trier,
exporter, analyser) sans terminal ni `uv`, sur macOS, Windows et Linux, via un installeur.
Mainteneur unique, en Python. Spec : `docs/superpowers/specs/2026-10-23-gui-desktop-design.md`.

## Décision
- **NiceGUI en mode natif** (fenêtre pywebview), dans `scilex/gui/`, commande `scilex-gui`,
  dépendances dans l'extra optionnel `gui` (la CLI ne les exige pas).
- **Couche mince** : `pages/` affiche, `services/` porte la logique et n'appelle que les
  fonctions publiques du pipeline (`run_collection`, `run_aggregation`, `SciLExConfig`,
  `init_templates`). Le pipeline n'est pas modifié pour la GUI.
- **Mêmes fichiers que la CLI** : une revue = un dossier avec `scilex.yml` ; clés dans
  `~/.config/scilex/keys.yml`. La liste des revues connues est dans
  `gui_reviews.yml` du dossier de configuration utilisateur (`platformdirs`).
- **`output_dir` résolu par rapport au dossier de la revue**, jamais via `chdir` ni
  `$SCILEX_CONFIG` (globaux au processus).
- **Un seul job actif dans toute l'app** : la capture de logs accepte les threads anonymes du
  collecteur, ce qui n'est correct que pour un job. Briques partagées avec l'API web
  (statuts, transitions, capture de logs) dans `scilex/pipeline/jobs.py`.
- **Packaging PyInstaller** (`packaging/scilex-gui.spec`), mode `onedir`, construit par
  GitHub Actions sur chaque OS (`.github/workflows/gui-build.yml`), puis
  `scilex-gui --self-test` exécuté sur le binaire produit. Fichiers de données embarqués par
  **liste explicite** ; un test interdit tout fichier de configuration locale ou de clés.
- **Pas de signature ni de notarisation en v1** : instructions d'ouverture documentées.
- **Streamlit conservé** jusqu'à parité fonctionnelle de la GUI desktop, retiré ensuite
  (décision à prendre à ce moment-là).

## Alternatives écartées
- **PySide6 (Qt)** : packaging éprouvé, aspect natif, mais beaucoup plus de code par écran
  (modèles de tableau, signaux, `QThread`), graphiques et graphes à ajouter, pas de
  réutilisation de FastAPI.
- **Tauri + front JS + Python en sidecar** : interface soignée, mais trois chaînes d'outils
  (Rust, JS, Python) et deux processus à coordonner, trop coûteux pour un mainteneur seul.
- **Interface terminal (Textual)** : ne vise pas le public non développeur.

## Conséquences
- Le point d'entrée appelle `multiprocessing.freeze_support()` en premier et ne relance
  l'app que sous `__name__ == "__main__"` (pas `__mp_main__`).
- L'annulation arrête la collecte à la requête suivante ; l'agrégation n'est pas
  interruptible (le job se termine « annulé » à sa fin).
- Les tests de pages utilisent `nicegui.testing.user_simulation` avec des marqueurs
  (`.mark(...)`), sans navigateur ni fenêtre.
- Linux : pywebview tourne sur Qt WebEngine (`pywebview[qt]`, embarqué dans le build, ~380 Mo
  compressés) ; GTK exigerait des liaisons Python système impossibles à embarquer. Le build
  installe les bibliothèques système de Qt, sinon PyInstaller omet ses plugins (fenêtre
  impossible). Au démarrage, un processus enfant (`--probe-native`) vérifie que la fenêtre peut
  s'ouvrir ; sinon l'app s'ouvre dans le navigateur, avec un sélecteur de dossier dans la page.
  Archive `.tar.gz` plutôt qu'une AppImage.
