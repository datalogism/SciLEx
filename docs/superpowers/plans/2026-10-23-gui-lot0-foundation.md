# Plan d'implémentation — GUI desktop, lot 0 (fondation)

Spec : `docs/superpowers/specs/2026-10-23-gui-desktop-design.md`
Branche : `feat/gui-desktop` (worktree dédié, fusion `--ff-only` dans `dev`)
Note de suivi : `docs/wip/gui-lot0.md` (état, prochaine étape, points ouverts), mise à jour à chaque commit `wip:`.

## But du lot

À la fin du lot 0 : `uv run scilex-gui` ouvre une fenêtre native avec l'accueil « Mes revues » et la barre latérale des étapes ; on peut créer ou ouvrir une revue et lancer une collecte + agrégation avec progression et annulation ; la CI produit un exécutable macOS, Windows et Linux qui passe `--self-test`.

Hors lot 0 : formulaires de configuration (lot 1), suivi détaillé par API (lot 2), tri (lot 3), export (lot 4), analyses (lot 5).

## Contraintes relevées dans le code

1. **`output_dir` est relatif au répertoire courant** (`settings/loader.py:464` le transmet tel quel). L'app ne doit pas faire `chdir` (global au processus) : `services/` résout `output_dir` en chemin absolu par rapport au dossier de la revue avant d'appeler le pipeline.
2. **Pas de mutation de `SCILEX_CONFIG`** (variable d'environnement globale, comme le fait `webapi/scilex_api.py:405`) : charger avec `SciLExConfig.from_files(config_path=<revue>/scilex.yml, keys_path=...)`.
3. **Capture des logs** : `JobThreadFilter` accepte tous les threads `Thread-N`, ce qui n'est correct qu'avec un seul job à la fois. Lot 0 : **un seul job actif dans toute l'app** (pas seulement par revue), refus explicite sinon. Lever cette limite relèvera du lot 2.
4. **multiprocessing** (`run_collection.py`, `crawlers/aggregate_parallel.py`) : `multiprocessing.freeze_support()` en première instruction du point d'entrée, sinon chaque worker relance l'application dans le bundle.
5. **Fichiers de données à embarquer, liste explicite** : `scilex/templates/`, `scilex/rdf/queries/`, `scilex/data/venue_rankings/`, `scilex/tagging/`. Ne jamais inclure `scilex/api.config.yml`, `scilex/scilex.config.yml`, `scilex/scilex.advanced.yml` (fichiers locaux ignorés par git, peuvent contenir des clés).
6. **Dépendances lourdes inutiles à l'app** : `streamlit` est une dépendance principale ; l'exclure du bundle (`excludes` PyInstaller) pour réduire la taille.
7. `httpx<0.28.0` est épinglé : vérifier que la résolution avec `nicegui` passe (étape 1).

## Étapes

Chaque étape se termine par tests verts, `uvx ruff format` + `uvx ruff check --fix` sur les fichiers modifiés, et un commit (`git commit -m … -- <chemins>`).

### Étape 1 — Squelette et dépendances

Fichiers :
- `pyproject.toml` : extra `gui = ["nicegui>=…", "pywebview>=…", "platformdirs>=…"]` ; extra `build = ["pyinstaller>=…"]` ; script `scilex-gui = "scilex.gui.app:main"`.
- `scilex/gui/__init__.py`, `app.py` (vide sauf `main()` qui lève `NotImplementedError`), `state.py`, `pages/__init__.py`, `components/__init__.py`, `services/__init__.py`, `services/workspace.py`, `services/jobs.py` (signatures + docstrings, corps `NotImplementedError`).
- `tests/gui/` avec tests marqués `skip` décrivant le comportement attendu.
- `docs/wip/gui-lot0.md`.

Vérification : `uv sync --extra gui --extra dev` résout ; `uv run python -c "import nicegui, webview, platformdirs"` ; suite de tests existante verte.
Commit : `wip(gui): squelette scilex/gui et extra gui`.

### Étape 2 — `services/workspace.py`

API :
```python
@dataclass(frozen=True)
class Review:
    folder: Path          # dossier de travail contenant scilex.yml
    name: str             # champ `name` de scilex.yml
    output_root: Path     # output_dir résolu en absolu par rapport à folder
    collection_dir: Path  # output_root / name
    has_results: bool     # collection_dir / "aggregated_results.csv" existe

class Workspace:
    def __init__(self, registry_path: Path | None = None): ...  # défaut : platformdirs.user_config_path("scilex") / "gui_reviews.yml"
    def list_reviews(self) -> list[Review]: ...       # ignore (et signale) les dossiers disparus
    def open_review(self, folder: Path) -> Review: ... # exige scilex.yml valide, ajoute au registre
    def create_review(self, folder: Path, name: str, template: str | None = None) -> Review: ...  # via scilex.init_templates
    def forget_review(self, folder: Path) -> None: ...
    def load_config(self, review: Review, keys_path: Path | None = None) -> SciLExConfig: ...  # output_dir réécrit en absolu
```
Réutiliser `scilex.init_templates` pour la création (lire son API publique avant ; si elle n'expose qu'un `main()` CLI, extraire une fonction `write_config(path, name, template)` testée, sans changer le comportement CLI).

Tests (`tests/gui/test_workspace.py`, `tmp_path`, aucun réseau) : création puis réouverture ; registre persistant entre deux instances ; dossier supprimé ignoré ; `scilex.yml` invalide → `SettingsError` remontée ; `output_dir` relatif résolu par rapport au dossier de la revue et non au répertoire courant (test avec `monkeypatch.chdir`).
Commit : `feat(gui): services.workspace (registre des revues)`.

### Étape 3 — `services/jobs.py`

Extraire de `webapi/scilex_api.py` la logique de job, sans dépendance FastAPI :
```python
class JobStatus(StrEnum): PENDING, RUNNING, CANCELLING, COMPLETED, FAILED, CANCELLED

@dataclass
class Job:
    id: str; review_folder: Path; status: JobStatus; phase: str; progress: int; message: str
    logs: list[str]; api_stats: dict; error: str | None

class JobRunner:
    def start_pipeline(self, review: Review, config: SciLExConfig, *, skip_citations: bool = False) -> Job: ...
    def cancel(self, job_id: str) -> None: ...
    def get(self, job_id: str) -> Job | None: ...
    def active_job(self) -> Job | None: ...
```
- Déplacer `JobLogHandler`, `JobThreadFilter`, `_set_status` (transitions), `_cancel_if_requested` dans `services/jobs.py` ; `webapi/scilex_api.py` les importe depuis là (pas de duplication, comportement web inchangé).
- `start_pipeline` lance un `threading.Thread` qui appelle `orchestrator.run_collection(config, progress_callback, cancel_event)` puis `run_aggregation(config, AggregationOptions(skip_citations=…), progress_callback)` ; mêmes plages de progression que l'API web (collecte 20–70, agrégation 75–85).
- Refus (`JobConflictError`) si un job est déjà actif (contrainte 3).

Tests (`tests/gui/test_jobs.py`, `run_collection` et `run_aggregation` mockés) : succès complet → `COMPLETED`, progression croissante ; exception dans l'agrégation → `FAILED` avec message ; annulation pendant la collecte → `CANCELLED`, agrégation non appelée ; deuxième `start_pipeline` → `JobConflictError` ; logs capturés. Plus : tests existants de l'API web (`tests/` webapi) toujours verts après déplacement.
Commit : `refactor(webapi): logique de job déplacée dans scilex.gui.services.jobs` puis `feat(gui): JobRunner`.

### Étape 4 — Coquille NiceGUI

Fichiers :
- `app.py` : `main()` → `multiprocessing.freeze_support()` ; parse `--self-test`, `--browser` (dev : ouvrir dans le navigateur au lieu de la fenêtre native, utile pour déboguer) ; `ui.run(native=True, reload=False, title="SciLEx", window_size=(1280, 800))`.
- `components/stepper.py` : barre latérale ① Configurer ② Collecter ③ Trier ④ Exporter ⑤ Analyses + 🔑 Clés API + 📁 Mes revues ; étapes grisées selon `Review.has_results`, avec info-bulle donnant la raison.
- `pages/home.py` : cartes des revues (nom, dossier, « résultats disponibles » ou non), boutons « Nouvelle revue » (dialogue : dossier, nom, modèle) et « Ouvrir un dossier ».
- `pages/review.py` : mise en page revue (barre latérale + zone de contenu) ; pages Configurer, Trier, Exporter, Analyses, Clés = écran « bientôt disponible » nommant le lot.
- `pages/collect.py` : bouton Lancer, case « sans citations », barre de progression, phase, message, 50 dernières lignes de log, bouton Annuler ; rafraîchi par `ui.timer(0.5, …)` qui lit `Job`.
- Gestionnaire global d'exceptions : dialogue avec « Copier le diagnostic » (version SciLEx, OS, traceback) ; logs fichier dans `platformdirs.user_log_path("scilex")`.
- Sélection de dossier : `app.native.main_window.create_file_dialog(webview.FOLDER_DIALOG)` en mode natif, champ texte en mode `--browser`.

Tests (`tests/gui/test_pages.py`, fixture `User` de NiceGUI, `pytest_plugins = ["nicegui.testing.user_plugin"]`) : accueil vide → message d'invite ; création d'une revue → carte affichée ; ouverture → barre latérale, Trier grisé ; Lancer (JobRunner mocké) → progression puis « terminé », Trier activé.
Vérification manuelle : `uv run scilex-gui` sur macOS, fenêtre ouverte en arrière-plan sans voler le focus si possible ; une vraie petite collecte (1 API gratuite, 1 année, mots-clés étroits).
Commits : `feat(gui): coquille, accueil et barre latérale`, `feat(gui): écran Collecter minimal`.

### Étape 5 — `--self-test`

`scilex-gui --self-test` sans ouvrir de fenêtre, code de sortie 0 si tout passe, 1 sinon, rapport sur stdout :
- import de `nicegui`, `webview`, `scilex.pipeline.orchestrator`, `scilex.crawlers.aggregate_parallel`, `rdflib` ;
- présence de chaque fichier de données (contrainte 5) via `importlib.resources` ;
- `ProcessPoolExecutor(max_workers=2)` exécutant une fonction triviale (vérifie `freeze_support` dans le bundle) ;
- création d'une revue dans un dossier temporaire et `load_config` (sans réseau).

Test : `tests/gui/test_self_test.py` appelle la fonction en processus.
Commit : `feat(gui): mode --self-test`.

### Étape 6 — Packaging PyInstaller

- `packaging/scilex-gui.spec` : point d'entrée `scilex/gui/app.py` ; `datas` = liste explicite de la contrainte 5 + `collect_data_files("nicegui")` ; `hiddenimports` nécessaires (à compléter d'après les échecs du self-test) ; `excludes = ["streamlit", "tkinter", "pytest"]` ; `windowed=True` ; icône `packaging/icons/scilex.{icns,ico,png}` (dérivée de `img/` si un logo existe, sinon icône simple).
- Garde-fou : un test (`tests/gui/test_packaging_spec.py`) lit la spec et échoue si un fichier `*.config.yml`, `api.config*` ou `keys.yml` figure dans `datas`.
- Script local `scripts/build_gui.sh` : `uv run --extra gui --extra build pyinstaller packaging/scilex-gui.spec --noconfirm` puis `dist/SciLEx/... --self-test`.
- macOS : `.app` puis `.dmg` (`hdiutil create`) ; Windows : dossier `onedir` zippé (installeur Inno Setup plus tard) ; Linux : AppImage via `appimagetool`.

Vérification : build local macOS, `--self-test` OK, taille du bundle notée dans la note wip.
Commit : `build(gui): spec PyInstaller et script de build`.

### Étape 7 — CI

`.github/workflows/gui-build.yml` : déclenché sur push de tags `gui-v*`, sur `workflow_dispatch`, et sur les pull requests touchant `scilex/gui/**` ou `packaging/**` ; matrice `macos-latest`, `windows-latest`, `ubuntu-22.04` (glibc ancienne pour la compatibilité AppImage) ; étapes : checkout, setup-uv, `uv sync --extra gui --extra build`, dépendances système Linux de pywebview (GTK/WebKit2) uniquement pour le self-test, build, `--self-test` (sous `xvfb-run` sur Linux), upload des artefacts. Les tests `tests/gui/` rejoignent le workflow `tests.yml` existant (installer l'extra `gui`).
Commit : `ci(gui): build et self-test multi-OS`.

### Étape 8 — Documentation et ADR

- `docs/decisions/0004-gui-desktop-nicegui.md` : contexte (public non développeur, 3 OS), décision (NiceGUI natif + PyInstaller, pas de signature en v1, Streamlit conservé jusqu'à parité), alternatives écartées (PySide6, Tauri), conséquences (un seul job actif en lot 0, `output_dir` résolu par l'app).
- `docs/user-guides/gui.md` : installation (y compris ouverture d'une app non signée sur macOS et Windows), premier lancement.
- `CLAUDE.md` : section `scilex/gui/` dans l'architecture, commande `scilex-gui`.
- Note wip passée à « lot 0 terminé », avec la liste des points ouverts pour le lot 1.
Commit : `docs(gui): ADR 0004, guide utilisateur, CLAUDE.md`.

## Critères de fin du lot 0

- [ ] `uv run scilex-gui` : accueil, création et ouverture d'une revue, barre latérale avec étapes grisées correctement.
- [ ] Une collecte + agrégation réelle (petite) lancée depuis l'app produit `aggregated_results.csv` dans le dossier de la revue, identique à `scilex-collect && scilex-aggregate --config <revue>/scilex.yml` sur la même configuration.
- [ ] Annulation fonctionnelle pendant la collecte.
- [ ] Tests `tests/gui/` verts ; suite existante verte (y compris API web après déplacement de la logique de job).
- [ ] Artefacts CI pour les 3 OS, chacun passant `--self-test`.
- [ ] Aucun fichier de configuration locale ni clé dans les bundles (test garde-fou vert).
- [ ] ADR 0004, guide utilisateur, `CLAUDE.md` à jour ; fusion `--ff-only` dans `dev`.

## Répartition

Étapes 1, 2, 3 et 5 : bien spécifiées, confiables à des agents `sonnet` en worktree (une étape par agent, séquentielles car dépendantes). Étapes 4, 6 et 7 : itératives (rendu, packaging qui casse), à mener par l'orchestrateur ou avec validation visuelle. Étape 8 : orchestrateur.

## Coordination

La session scilex-d8 a prévu des lots touchant `ranking.py`, `citations/`, `config_defaults.py`, `run_collection.py`, l'export Zotero/BibTeX et les collectors. Le lot 0 ne touche que `scilex/gui/`, `packaging/`, `pyproject.toml`, `.github/workflows/`, `scilex/webapi/scilex_api.py` (étape 3) et `scilex/init_templates.py` (étape 2, si extraction nécessaire) : prévenir scilex-d8 avant les étapes 2 et 3, et rebaser sur `dev` avant fusion.
