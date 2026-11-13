"""Refresh the copy of the scilex-lpwc-ap application profile shipped with SciLEx.

The knowledge-graph builder (:mod:`scilex.kg.build`) runs the profile's own
mapping (RML + FnO functions + SPARQL UPDATE), so SciLEx carries a pinned copy
of it in ``scilex/kg/ap/``. This maintainer tool replaces that copy with the
latest version published on Codeberg and records where it came from in
``scilex/kg/ap/VERSION.json``.

"Latest" is, in order: the latest release, else the newest tag, else the head
of the default branch. Inside that commit the profile is read from ``final/``
when it holds an ontology, else from the highest ``iterations/iterN``.

Usage::

    python -m scilex.kg.sync_profile            # latest version
    python -m scilex.kg.sync_profile --ref v0.2.0
    python -m scilex.kg.sync_profile --check    # only report whether a newer one exists
    python -m scilex.kg.sync_profile --local ../scilex-lpwc-ap   # from a local checkout

Review the diff of ``scilex/kg/ap/`` before committing it: the FnO functions are
Python code that runs during a build.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scilex.kg.profile import PROFILE_DIR, VERSION_FILENAME, read_version

logger = logging.getLogger(__name__)

REPOSITORY = "cringwald/scilex-lpwc-ap"
API = f"https://codeberg.org/api/v1/repos/{REPOSITORY}"
RAW = f"https://codeberg.org/{REPOSITORY}/raw/commit"
TIMEOUT = 30

# (pattern relative to the profile root, destination folder in scilex/kg/ap)
PROFILE_FILES: tuple[tuple[str, str], ...] = (
    (r"ontology/[^/]+\.ttl", "ontology"),
    (r"mappings/rml/[^/]+\.rml\.ttl", "mappings/rml"),
    (r"mappings/functions/[^/]+\.py", "mappings/functions"),
    (r"mappings/sparql/[^/]+\.ru", "mappings/sparql"),
    (r"shapes/(manual/)?general/[^/]+\.ttl", "shapes"),
    # iteration 4+: the mapping interface (placeholder contract, effective profile),
    # the reference profiles a collection profile extends, the global reference tables
    # and the JSON Schemas of the collection profile and of the survey bundle.
    (r"mappings/ap_profile\.py", "mappings"),
    (r"mappings/collections/_[^/]+\.json", "mappings/collections"),
    (r"mappings/alignments/[^/]+\.json", "mappings/alignments"),
    (r"mappings/[^/]+\.schema\.json", "mappings"),
)
REQUIRED_FOLDERS = ("ontology", "mappings/rml", "mappings/functions", "mappings/sparql")


@dataclass(frozen=True)
class RemoteVersion:
    """A version of the profile on Codeberg."""

    ref: str  # release tag, tag or branch name
    kind: str  # "release", "tag" or "branch"
    commit: str


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


_SESSION = _session()


def _get(url: str, **params) -> requests.Response:
    response = _SESSION.get(url, params=params or None, timeout=TIMEOUT)
    response.raise_for_status()
    return response


def _commit_of(ref: str) -> str:
    commits = _get(f"{API}/commits", sha=ref, limit=1).json()
    if not commits:
        raise LookupError(f"No commit found for {ref!r}")
    return commits[0]["sha"]


def latest_version(ref: str | None = None) -> RemoteVersion:
    """Return the version to install: ``ref`` when given, else the latest one."""
    if ref:
        return RemoteVersion(ref=ref, kind="ref", commit=_commit_of(ref))
    try:
        release = _get(f"{API}/releases/latest").json()
        tag = release["tag_name"]
        return RemoteVersion(ref=tag, kind="release", commit=_commit_of(tag))
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 404:
            raise
    tags = _get(f"{API}/tags", limit=50).json()
    if tags:
        newest = max(tags, key=lambda t: t["commit"].get("created", ""))
        return RemoteVersion(
            ref=newest["name"], kind="tag", commit=newest["commit"]["sha"]
        )
    branch = _get(API).json()["default_branch"]
    return RemoteVersion(ref=branch, kind="branch", commit=_commit_of(branch))


def profile_root(paths: list[str]) -> str:
    """Return the folder holding the profile inside the repository tree."""
    if any(re.fullmatch(r"final/ontology/[^/]+\.ttl", p) for p in paths):
        return "final"
    iterations = {
        int(m.group(1))
        for p in paths
        if (m := re.match(r"iterations/iter(\d+)/ontology/[^/]+\.ttl$", p))
    }
    if not iterations:
        raise LookupError("No ontology found in final/ or iterations/iterN/")
    return f"iterations/iter{max(iterations)}"


def select_files(paths: list[str], root: str) -> dict[str, str]:
    """Return ``{repository path: destination path}`` of the files to copy."""
    selected: dict[str, str] = {}
    for path in paths:
        if not path.startswith(root + "/"):
            continue
        relative = path[len(root) + 1 :]
        for pattern, folder in PROFILE_FILES:
            if re.fullmatch(pattern, relative):
                selected[path] = f"{folder}/{relative.rsplit('/', 1)[-1]}"
    missing = [
        f
        for f in REQUIRED_FOLDERS
        if not any(d.startswith(f + "/") for d in selected.values())
    ]
    if missing:
        raise LookupError(f"The profile in {root}/ has no {', '.join(missing)}")
    return selected


def _ontology_version(ttl: str) -> tuple[str, str]:
    info = re.search(r'owl:versionInfo\s+"([^"]*)"', ttl)
    iri = re.search(r"owl:versionIRI\s+<([^>]*)>", ttl)
    return (info.group(1) if info else ""), (iri.group(1) if iri else "")


def install(version: RemoteVersion, target: Path = PROFILE_DIR) -> dict:
    """Download ``version`` into ``target`` (replaced atomically) and return its metadata."""
    tree = _get(
        f"{API}/git/trees/{version.commit}", recursive="true", per_page=10000
    ).json()
    if tree.get("truncated"):
        raise RuntimeError("The repository tree listing is truncated")
    paths = [e["path"] for e in tree["tree"] if e["type"] == "blob"]
    root = profile_root(paths)
    files = select_files(paths, root)

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "ap"
        for source, destination in sorted(files.items()):
            out = staging / destination
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(_get(f"{RAW}/{version.commit}/{source}").content)
            logger.info("%s -> %s", source, destination)
        ontology = next((staging / "ontology").glob("*.ttl"))
        version_info, version_iri = _ontology_version(
            ontology.read_text(encoding="utf-8")
        )
        metadata = {
            "repository": f"https://codeberg.org/{REPOSITORY}",
            "ref": version.ref,
            "ref_kind": version.kind,
            "commit": version.commit,
            "profile_root": root,
            "version_info": version_info,
            "version_iri": version_iri,
            "license": "CC-BY-4.0",
            "fetched": dt.date.today().isoformat(),
            "files": sorted(files.values()),
        }
        (staging / VERSION_FILENAME).write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(staging, target)
    return metadata


def _git(checkout: Path, *args: str) -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "-C", str(checkout), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def install_local(checkout: Path, target: Path = PROFILE_DIR) -> dict:
    """Install the profile from a local checkout (its working tree, unpushed work included)."""
    checkout = Path(checkout).expanduser().resolve()
    paths = [
        p.relative_to(checkout).as_posix()
        for p in checkout.rglob("*")
        if p.is_file() and ".git" not in p.parts
    ]
    root = profile_root(paths)
    files = select_files(paths, root)
    commit = _git(checkout, "rev-parse", "HEAD")
    dirty = bool(_git(checkout, "status", "--porcelain", "--", root))
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "ap"
        for source, destination in sorted(files.items()):
            out = staging / destination
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(checkout / source, out)
            logger.info("%s -> %s", source, destination)
        ontology = next((staging / "ontology").glob("*.ttl"))
        version_info, version_iri = _ontology_version(
            ontology.read_text(encoding="utf-8")
        )
        metadata = {
            "repository": f"https://codeberg.org/{REPOSITORY}",
            "ref": f"local:{checkout.name}",
            "ref_kind": "local checkout" + (" (uncommitted changes)" if dirty else ""),
            "commit": commit + ("+dirty" if dirty else ""),
            "profile_root": root,
            "version_info": version_info,
            "version_iri": version_iri,
            "license": "CC-BY-4.0",
            "fetched": dt.date.today().isoformat(),
            "files": sorted(files.values()),
        }
        (staging / VERSION_FILENAME).write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(staging, target)
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--ref", help="tag, branch or commit to install (default: latest)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only report whether a newer version exists",
    )
    parser.add_argument(
        "--local",
        type=Path,
        metavar="DIR",
        help="install from a local checkout of the profile (unpushed iterations included)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    current = read_version()
    if args.local:
        metadata = install_local(args.local)
        print(
            f"installed {metadata['ref']} ({metadata['commit'][:16]}) from "
            f"{metadata['profile_root']}/ (ontology {metadata['version_info']}, "
            f"{len(metadata['files'])} files) into {PROFILE_DIR}"
        )
        return 0
    remote = latest_version(args.ref)
    up_to_date = current.get("commit") == remote.commit
    print(
        f"installed: {current.get('ref', 'none')} ({current.get('commit', '')[:10]})\n"
        f"remote:    {remote.ref} [{remote.kind}] ({remote.commit[:10]})"
    )
    if args.check:
        print("up to date" if up_to_date else "a newer version is available")
        return 0 if up_to_date else 1
    if up_to_date:
        print("already installed")
        return 0
    metadata = install(remote)
    print(
        f"installed {metadata['ref']} from {metadata['profile_root']}/ "
        f"(ontology {metadata['version_info']}, {len(metadata['files'])} files) into {PROFILE_DIR}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
