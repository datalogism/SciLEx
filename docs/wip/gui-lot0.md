# WIP — GUI desktop, lot 0 (fondation)

Plan : `docs/superpowers/plans/2026-10-23-gui-lot0-foundation.md`
Branche : `feat/gui-desktop`, worktree `.claude/worktrees/gui-desktop`

## État

- [x] Étape 1 — squelette, extras `gui` (nicegui 3.18, pywebview 6.2, platformdirs) et `build` (pyinstaller 6.22)
- [x] Étape 2 — services/workspace.py
- [x] Étape 3 — services/jobs.py
- [x] Étape 4 — coquille NiceGUI
- [x] Étape 5 — --self-test
- [x] Étape 6 — packaging PyInstaller
- [x] Étape 7 — CI
- [x] Étape 8 — docs, ADR 0004

## Notes

- Tests de pages : `nicegui.testing.user_simulation(root=…)` + `@pytest.mark.anyio` (plugin anyio déjà installé via httpx ; pas de pytest-asyncio).
- Création de revue : `init_templates.apply_template()` / `skeleton_text()` suffisent, pas d'extraction.

- Étape 3 : les briques partagées (états, capture de logs) sont dans `scilex/pipeline/jobs.py` (et non dans `scilex.gui`) pour que l'API web ne dépende pas de la GUI ; `webapi/scilex_api.py` garde des adaptateurs dict.
- Tests de pages : utiliser des marqueurs (`.mark(...)` + `user.find(marker=...)`) ; la recherche par contenu de NiceGUI est large et clique l'élément d'id le plus bas.
- `app.py` : garde `__name__ == "__main__"` seulement (pas `__mp_main__`, sinon chaque processus enfant relancerait l'app).
- Annulation : la collecte s'arrête à la requête suivante ; l'agrégation n'est pas interruptible (le job finit « annulé » après).

- Étape 6 : 1er build → self-test a détecté `rdflib` absent (aucune page ne l'importe encore) ; corrigé par `collect_submodules("scilex")` (hors `scilex.webapi`, dont la page Streamlit s'exécute à l'import) + `rdflib.plugins`. Bundle macOS : 275 Mo, self-test OK, lancement réel OK (HTTP 200, 0 erreur de log).
- Étape 7 : Linux livré en `.tar.gz` (pas d'AppImage) en attendant le choix du moteur pywebview (GTK ou Qt).

## Points ouverts (pour la suite)

- Workflow CI `gui-build.yml` jamais exécuté : nécessite un push de la branche (à faire avec l'accord de l'utilisateur).
- Vérification visuelle de la fenêtre native par l'utilisateur.
- Linux : moteur pywebview à choisir (GTK système ou `pywebview[qt]`), puis AppImage.
- Icône de l'application (le logo actuel est une bannière 600×150).
- Annulation pendant l'agrégation non interruptible.

## Prochaine étape

Fusion `--ff-only` dans `dev` après validation de l'utilisateur ; puis spec du lot 1 (Configurer + clés).

## Test « comme un humain » (Chrome headless, 2026-10-23)
Parcours complet OK : accueil → nouvelle revue « Test » → collecte OpenAlex réelle → ③ Screen → retour accueil (« Results available »).
Corrigé : chemin relatif depuis `/` (56d9b2d8), barre latérale figée après collecte (a873caa4), infobulles empilées sur Run (b57b012f).
Reste : rebuild de dist/SciLEx.app (quitter l'app avant).
