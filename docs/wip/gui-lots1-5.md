# GUI lots 1 à 5 (wip)

Mandat utilisateur (2026-10-23) : enchaîner les lots 1 à 5 sans redemander ; agents Sonnet en parallèle ; à la fin, un agent Sonnet teste la GUI comme un humain (Chrome headless, sans voler le focus).

## Fondations communes (faites, sur dev)
- `pages/review.py` charge `scilex.gui.pages.<step>.render(ctx, review)` si le module existe.
- `JobRunner.start_task(review, kind, body)` : tâche de fond générique (logs, statut, annulation via `job.cancel_event`, `job.result`) ; `latest_for(review_id, kind)`.
- `components/job_panel.py` : `JobPanel(ctx, review, kind, on_change=, on_finished=)`.
- `services/screening.py` : `paper_key`, `load_results`, `load/save/set_decision`, `orphan_keys`, `included_results` ; fichier `output/<nom>/screening.csv`.
- Fixture `ctx` dans `tests/gui/conftest.py`.

## Vague 1 (6 agents, worktrees)
| Agent | Lot | Fichiers |
|---|---|---|
| A | 1 Configure | pages/configure.py, services/config_editor.py |
| B | 1 API keys | pages/keys.py, services/keys_editor.py |
| C | 2 Collect complet | pages/collect.py, services/jobs.py (start_pipeline) |
| D | 3 Screen | pages/screen.py, services/screening.py |
| E | 4 Export | pages/export.py, services/exports.py |
| F | 5 Analyses | pages/analyses.py, services/analyses.py |

## État (2026-10-23)
- Vague 1 fusionnée dans `gui-integration` puis `dev` (976297c4) : 1942 tests OK.
- Corrections d'intégration : clé Springer meta/openaccess conservée ; revue au scilex.yml invalide gardée avec bandeau ; faux pipeline de test écrit un CSV valide.
- Guide utilisateur à jour (122fbd53).
- Vague 2 en cours : Configure éditeur brut (YAML cassé, clés inconnues) ; Analyses onglet Citations + annulation ; relecture de code en lecture seule.

## Pause (2026-10-23) — état exact
- `dev` = `gui-integration` = ca29f0ff : lots 1-5 + relecture + corrections du test navigateur ; 1982 tests OK, ruff OK.
- Test « humain » (agent Sonnet, Chrome headless, faux HOME) : tous les écrans OK de bout en bout ; bugs trouvés tous corrigés (mots-clés en groupes, citations « réussies » à tort, création à moitié faite, commentaires perdus, -150 % du rapport de filtrage, UX/cosmétique).
- Non vérifié visuellement après correction : largeur du log, colonnes du tableau Screen, noms longs sur les cartes, libellés doublés.
- Limite acceptée : Citations termine en échec si aucun article n'a de références (petit corpus).
- `dist/SciLEx.app` date d'avant les corrections du test (à reconstruire).

## Reprise (dans l'ordre)
1. `scripts/build_gui.sh` (l'app doit être fermée) → self-test (vérifie aussi les 6 pages).
2. Agent Sonnet testeur : passe de vérification courte des correctifs visuels + parcours complet (même brief, port 8766, faux HOME).
3. Supprimer le worktree `../SciLEx-integration` et la branche `gui-integration` une fois dev à jour.
4. Commits en français antérieurs (lot 0, 56d9b2d8…8b0544b8) : reformuler en anglais seulement si l'utilisateur le demande, avant tout push.
5. Push + CI multi-OS (avec accord).

## 2026-10-23 — final verification done (d51e3aa5)
- Final tester walkthrough run. Incident: the tester pushed 1 paper to the user's real Zotero (collection `kg_metabo`) because `load_config` fell back to the legacy `scilex/api.config.yml`. User asked to delete it manually.
- Fixed: GUI keys come only from `keys_editor.keys_path()` (empty keys otherwise), Zotero push needs a confirmation dialog (`zotero-confirm`); home card refresh, configure reload, full-width collect log, years shown as written, robust result CSVs + graph/scipy warnings, narrow-width tabs/grid.
- Full suite: 1996 passed. `dist/SciLEx.app` rebuilt, self-test ok.
- Open: layout fixes C/F only checked by class assertions (no browser re-test yet); reword the older French lot 0 commits before any push (ask the user); push + CI.
- Tester briefs must forbid any external write (Zotero push, etc.).
- 2026-10-23 later: lot 0 commit messages reworded to English (contents unchanged). Headless browser check: Collect log full width (1104px), Analyses tabs fit at 1024px; Screen grid was blank (autoSizeStrategy vs flex columns) → fixed in ea49a432, re-checked OK. App rebuilt, dev pushed; next: watch gui-build CI.
