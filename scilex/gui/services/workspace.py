"""Reviews known to the desktop app: list, create, open, forget.

A review is a working folder holding a ``scilex.yml``, exactly as for the
CLI. The app only remembers the list of folders in a small registry file
stored in the per-OS user configuration directory.

**Stable results folder.** The CLI writes a collection to
``<output_dir>/<name>``, so renaming a review used to leave its results
behind in the old folder. The app records the folder a review uses in
``review_state.yml`` (review folder) the first time it reads the review, and
keeps using it after a rename: results never move. ``scilex.yml`` is
unchanged, so the CLI keeps its own rule. A review read for the first time
whose ``<output_dir>/<name>`` holds no results adopts a sibling folder that
does, when that folder carries a name the review had (its folder name, or an
earlier name from its journal).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from scilex.config import SciLExConfig
from scilex.init_templates import apply_template, skeleton_text
from scilex.settings.loader import CONFIG_FILENAME, load_settings

logger = logging.getLogger(__name__)

RESULTS_FILENAME = "aggregated_results.csv"
REGISTRY_FILENAME = "gui_reviews.yml"
STATE_FILENAME = "review_state.yml"


def default_registry_path() -> Path:
    """Return the registry file in the per-OS user configuration directory."""
    from platformdirs import user_config_path

    return user_config_path("scilex") / REGISTRY_FILENAME


@dataclass(frozen=True)
class Review:
    """A literature review: a folder with its ``scilex.yml`` and its outputs."""

    folder: Path
    name: str
    output_root: Path
    # Set when scilex.yml exists but cannot be loaded: the review stays listed
    # so the user can fix it in the Configure screen instead of losing it.
    error: str | None = field(default=None, compare=False)
    # Results folder recorded in review_state.yml (None: output_root / name).
    collection_folder: Path | None = None

    @property
    def id(self) -> str:
        """Short stable identifier derived from the folder (used in URLs)."""
        return hashlib.sha1(str(self.folder).encode()).hexdigest()[:10]

    @property
    def config_path(self) -> Path:
        """Path of the review's ``scilex.yml``."""
        return self.folder / CONFIG_FILENAME

    @property
    def collection_dir(self) -> Path:
        """Directory where the pipeline writes this review's collection.

        The recorded folder (see the module docstring), else ``output_root / name``.
        """
        return self.collection_folder or self.output_root / self.name

    @property
    def results_path(self) -> Path:
        """Aggregated results file written by the aggregation step."""
        return self.collection_dir / RESULTS_FILENAME

    @property
    def has_results(self) -> bool:
        """True once the aggregation step has produced its results file."""
        return self.results_path.is_file()


def reviews_home() -> Path:
    """Default parent folder of the reviews: ``~/SciLEx``."""
    return Path.home() / "SciLEx"


def resolve_folder(folder: str | Path) -> Path:
    """Return ``folder`` as an absolute path; relative paths start at ``~/SciLEx``.

    The app's working directory is meaningless for the user (``/`` for a
    macOS app bundle, read-only), so it is never used.
    """
    path = Path(folder).expanduser()
    if not path.is_absolute():
        path = reviews_home() / path
    return path.resolve()


def _load_settings_without_keys(config_path: Path):
    """Load ``scilex.yml`` even when the keys file is missing.

    Keys are only needed to run jobs; opening a review must not depend on
    them (e.g. ``$SCILEX_KEYS`` pointing to a file that does not exist).
    """
    try:
        return load_settings(config_path=config_path).settings
    except FileNotFoundError:
        if not config_path.is_file():
            raise
    with tempfile.TemporaryDirectory() as tmp:
        empty_keys = Path(tmp) / "keys.yml"
        empty_keys.write_text("{}\n", encoding="utf-8")
        return load_settings(config_path=config_path, keys_path=empty_keys).settings


def _raw_review_name(folder: Path) -> str:
    """Return the ``name:`` of a possibly invalid scilex.yml, else the folder name."""
    try:
        data = yaml.safe_load((folder / CONFIG_FILENAME).read_text(encoding="utf-8"))
        name = data.get("name") if isinstance(data, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        pass
    return folder.name


def load_state(folder: Path) -> dict:
    """``review_state.yml`` of a review (empty when missing or unreadable)."""
    try:
        data = yaml.safe_load(
            (Path(folder) / STATE_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(folder: Path, state: dict) -> None:
    """Write ``review_state.yml`` atomically (errors are logged, not raised)."""
    path = Path(folder) / STATE_FILENAME
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(
            "# Written by the SciLEx desktop app: the results folder of this review\n"
            "# (kept when the review is renamed) and the names it has had.\n"
            + yaml.safe_dump(state, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        logger.warning("Cannot save %s", path, exc_info=True)
        with contextlib.suppress(OSError):
            tmp.unlink()


def _stored(folder: Path, path: Path) -> str:
    """``path`` relative to the review folder when inside it (posix), else absolute."""
    try:
        return path.relative_to(folder).as_posix()
    except ValueError:
        return str(path)


def _resolve_stored(folder: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else folder / path).resolve()


def known_names(folder: Path, state: dict | None = None) -> list[str]:
    """Names the review has had: recorded ones, earlier names in its journal, its folder."""
    from scilex.gui.services import journal

    state = load_state(folder) if state is None else state
    names = [str(n) for n in state.get("names") or []]
    for event in journal.load(folder):
        if event.get("activity") == "rename":
            names.extend(
                str(event.get("params", {}).get(k) or "") for k in ("from", "to")
            )
    names.append(Path(folder).name)
    return list(dict.fromkeys(n for n in names if n))


def results_candidates(
    folder: Path, output_root: Path, exclude: Path | None = None
) -> list[Path]:
    """Folders of ``output_root`` holding results and named after the review."""
    names = set(known_names(folder))
    try:
        children = sorted(output_root.iterdir())
    except OSError:
        return []
    return [
        child
        for child in children
        if child.name in names
        and (child / RESULTS_FILENAME).is_file()
        and (exclude is None or child.resolve() != exclude.resolve())
    ]


def adopt_folder(folder: Path, collection_folder: Path, reason: str) -> None:
    """Make ``collection_folder`` the review's results folder (recorded + journal)."""
    from scilex.gui.services import journal

    folder = Path(folder)
    state = load_state(folder)
    previous = state.get("output_folder")
    state["output_folder"] = _stored(folder, collection_folder)
    save_state(folder, state)
    journal.append(
        folder,
        "adopt-output",
        params={"from": previous, "to": state["output_folder"], "reason": reason},
        generated={"output_folder": state["output_folder"]},
        message=f"Results folder: {state['output_folder']} ({reason}).",
    )


def _collection_folder(folder: Path, name: str, output_root: Path) -> Path:
    """The review's results folder; records it (and renames) in review_state.yml."""
    from scilex.gui.services import journal

    state = load_state(folder)
    default = (output_root / name).resolve()
    changed = False
    recorded = state.get("output_folder")
    if recorded:
        collection = _resolve_stored(folder, str(recorded))
    else:
        collection = default
        if not (default / RESULTS_FILENAME).is_file():
            candidates = results_candidates(folder, output_root, exclude=default)
            if len(candidates) == 1:
                collection = candidates[0].resolve()
                journal.append(
                    folder,
                    "adopt-output",
                    params={
                        "from": _stored(folder, default),
                        "to": _stored(folder, collection),
                    },
                    generated={"output_folder": _stored(folder, collection)},
                    message=(
                        f"{_stored(folder, default)} holds no results; "
                        f"{_stored(folder, collection)}, named after the review, does."
                    ),
                )
        state["output_folder"] = _stored(folder, collection)
        changed = True
    previous_name = state.get("name")
    if previous_name and previous_name != name:
        journal.append(
            folder,
            "rename",
            params={"from": previous_name, "to": name},
            generated={"output_folder": state["output_folder"]},
            message=f"Renamed from {previous_name} to {name}; results stay in "
            f"{state['output_folder']}.",
        )
    if previous_name != name:
        state["name"] = name
        state["names"] = list(dict.fromkeys([*(state.get("names") or []), name]))
        changed = True
    if changed:
        save_state(folder, state)
    return collection


def read_review(folder: Path) -> Review:
    """Validate ``folder/scilex.yml`` and describe the review.

    ``output_dir`` is resolved against the review folder, never against the
    current working directory of the app.

    Raises:
        FileNotFoundError: If the folder has no ``scilex.yml``.
        SettingsError: If the configuration is invalid.
    """
    folder = resolve_folder(folder)
    config_path = folder / CONFIG_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(f"No {CONFIG_FILENAME} in {folder}")
    settings = _load_settings_without_keys(config_path)
    output_root = Path(settings.output_dir).expanduser()
    if not output_root.is_absolute():
        output_root = folder / output_root
    output_root = output_root.resolve()
    collection = _collection_folder(folder, settings.name, output_root)
    return Review(
        folder=folder,
        name=settings.name,
        output_root=output_root,
        collection_folder=None
        if collection == output_root / settings.name
        else collection,
    )


class Workspace:
    """Registry of the reviews known to the app."""

    def __init__(self, registry_path: Path | None = None):
        """Create a workspace backed by ``registry_path`` (per-OS default if None)."""
        self.registry_path = registry_path or default_registry_path()

    def _load_folders(self) -> list[Path]:
        if not self.registry_path.is_file():
            return []
        try:
            data = yaml.safe_load(self.registry_path.read_text(encoding="utf-8")) or {}
            return [Path(folder) for folder in data.get("reviews", [])]
        except (yaml.YAMLError, AttributeError, TypeError, UnicodeDecodeError) as exc:
            corrupt = self.registry_path.with_name(self.registry_path.name + ".corrupt")
            logger.warning(
                "Review registry %s is unreadable (%s); kept a copy as %s",
                self.registry_path,
                exc,
                corrupt,
            )
            with contextlib.suppress(OSError):
                shutil.copyfile(self.registry_path, corrupt)
            return []

    def _save_folders(self, folders: list[Path]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"reviews": [str(folder) for folder in folders]}
        tmp = self.registry_path.with_name(self.registry_path.name + ".tmp")
        try:
            tmp.write_text(yaml.safe_dump(data), encoding="utf-8")
            os.replace(tmp, self.registry_path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

    def list_reviews(self) -> list[Review]:
        """Return the known reviews.

        Folders that vanished are skipped; a review whose ``scilex.yml`` is
        invalid is returned with ``error`` set (named after its folder).
        """
        reviews = []
        for folder in self._load_folders():
            try:
                reviews.append(read_review(folder))
            except OSError as exc:
                logger.warning("Skipping review %s: %s", folder, exc)
            except (ValueError, yaml.YAMLError) as exc:
                logger.warning("Invalid configuration in %s: %s", folder, exc)
                reviews.append(
                    Review(
                        folder=folder,
                        name=_raw_review_name(folder),
                        output_root=folder / "output",
                        error=str(exc),
                    )
                )
        return reviews

    def get(self, review_id: str) -> Review | None:
        """Return the known review with this id, or None."""
        return next((r for r in self.list_reviews() if r.id == review_id), None)

    def open_review(self, folder: Path) -> Review:
        """Register an existing review folder.

        Raises:
            FileNotFoundError: If the folder has no ``scilex.yml``.
            SettingsError: If the configuration is invalid.
        """
        review = read_review(folder)
        folders = self._load_folders()
        if review.folder not in folders:
            self._save_folders([*folders, review.folder])
        return review

    def create_review(
        self, folder: Path, name: str, template: str | None = None
    ) -> Review:
        """Write a new ``scilex.yml`` in ``folder`` and register it.

        Args:
            folder: Working folder (created if needed).
            name: Review name (the collection is written to ``output/<name>``).
            template: Optional template or profile name (see ``scilex-init``).

        Raises:
            FileExistsError: If the folder already holds a ``scilex.yml``.
            SettingsError: If the resulting configuration is invalid.
        """
        config_path = resolve_folder(folder) / CONFIG_FILENAME
        if config_path.exists():
            raise FileExistsError(f"{config_path} already exists")
        try:
            return self._write_and_open(config_path, name, template)
        except BaseException:
            # Roll back the file this call wrote so a retry does not hit
            # "already exists" on a review that was never registered.
            with contextlib.suppress(OSError):
                config_path.unlink()
            raise

    def _write_and_open(
        self, config_path: Path, name: str, template: str | None
    ) -> Review:
        if template:
            apply_template(template, config_path)
            # Replace only the name line so the template's comments survive.
            text = config_path.read_text(encoding="utf-8")
            text = re.sub(
                r"^name:.*$", f"name: {json.dumps(name)}", text, count=1, flags=re.M
            )
            config_path.write_text(text, encoding="utf-8")
        else:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(skeleton_text(name), encoding="utf-8")
        review = self.open_review(config_path.parent)
        from scilex.gui.services import journal

        journal.append(
            review.folder,
            "created",
            params={"origin": journal.EMPTY, "name": name, "template": template},
            generated={"output_folder": _stored(review.folder, review.collection_dir)},
        )
        return review

    def forget_review(self, folder: Path) -> None:
        """Remove a folder from the registry (its files are left untouched)."""
        folder = resolve_folder(folder)
        self._save_folders([f for f in self._load_folders() if f != folder])

    @staticmethod
    def load_config(review: Review, keys_path: Path | None = None) -> SciLExConfig:
        """Load the pipeline configuration of ``review``.

        ``output_dir`` is rewritten as an absolute path so the pipeline writes
        into the review folder whatever the app's working directory.
        """
        from scilex.gui.services import keys_editor

        # Keys come only from the files the API keys screens show (global
        # keys, then the review's own overrides, plus the SCILEX_<API>_<FIELD>
        # variables): never the legacy api.config.yml.
        chosen = keys_path if keys_path is not None else keys_editor.keys_path()
        review_keys = keys_editor.review_keys_path(review.folder)
        if keys_path is None and review_keys.is_file():
            with tempfile.TemporaryDirectory() as tmp:
                merged = Path(tmp) / "keys.yml"
                merged.write_text(
                    yaml.safe_dump(keys_editor.effective_keys(review.folder)),
                    encoding="utf-8",
                )
                config = SciLExConfig.from_files(
                    config_path=review.config_path, keys_path=merged
                )
        elif Path(chosen).is_file():
            config = SciLExConfig.from_files(
                config_path=review.config_path, keys_path=chosen
            )
        else:
            with tempfile.TemporaryDirectory() as tmp:
                empty_keys = Path(tmp) / "keys.yml"
                empty_keys.write_text("{}\n", encoding="utf-8")
                config = SciLExConfig.from_files(
                    config_path=review.config_path, keys_path=empty_keys
                )
        config.main["output_dir"] = str(review.output_root)
        if review.collection_folder is not None:
            # A renamed review keeps its results folder: point the pipeline at it.
            config.main["output_dir"] = str(review.collection_folder.parent)
            config.main["collect_name"] = review.collection_folder.name
        return config
