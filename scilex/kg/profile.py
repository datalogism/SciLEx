"""The pinned copy of the scilex-lpwc-ap application profile, and its adaptation to one review.

The profile's mapping is written for one collection: its paper IRIs, its input
file and its coding grid are literal values in the RML file, the FnO functions
and the SPARQL UPDATE files. :func:`prepare_mapping` writes a copy of the
mapping for another review by rewriting exactly those values, and fails when
the upstream files no longer have the shape it expects (a new profile version
that SciLEx must be adapted to), rather than producing a graph that silently
mixes two reviews.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_DIR = Path(__file__).with_name("ap")
VERSION_FILENAME = "VERSION.json"
DATA_NAMESPACE = "https://w3id.org/scilex/data/"
PROFILE_IRI = "https://w3id.org/scilex/ap/lpwc"

_BASE_IN_UDFS = re.compile(r'^BASE\s*=\s*"([^"]+)"', re.M)
_RML_SOURCE = re.compile(r'(rml:source\s+)"([^"]+)"')
_MAPPING_NS = re.compile(r"(https://w3id\.org/scilex/mapping/)[^#>\s]+#")
_SLUG = re.compile(r"[^0-9a-z]+")

# Coding dimensions the profile lifts into Linked Papers With Code (sparql/04),
# with the LPWC property and class they become. A review grid names them with a
# prefix (``SAT_TASK``); :func:`lpwc_roles` matches on the last part.
LPWC_LIFTING: dict[str, tuple[str, str]] = {
    "TASK": ("hasTask", "task"),
    "DATASET": ("usesDataset", "dataset"),
    "PTM": ("hasModel", "model"),
    "MODEL": ("hasModel", "model"),
    "ARCHI": ("hasMethod", "method"),
}


class ProfileError(RuntimeError):
    """The pinned profile is missing or has a shape SciLEx cannot adapt."""


@dataclass(frozen=True)
class PreparedMapping:
    """A review-specific copy of the profile's mapping, ready to run."""

    folder: Path
    rml: list[Path]
    udfs: Path
    sparql: list[Path]
    base_iri: str
    # Environment the FnO functions need while the mapping runs (SCILEX_PROFILE, iter3+).
    env: dict = field(default_factory=dict)
    templated: bool = False  # the profile's mapping has {{...}} placeholders (iter3+)
    # the profile describes the dataset, its creator and sub-corpora itself (iter4+)
    contract: bool = False


def read_version(folder: Path = PROFILE_DIR) -> dict:
    """Return the metadata of the pinned profile (empty when there is none)."""
    path = folder / VERSION_FILENAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def ontology_path(folder: Path = PROFILE_DIR) -> Path:
    """Return the profile's ontology file."""
    found = sorted((folder / "ontology").glob("*.ttl"))
    if not found:
        raise ProfileError(f"No ontology in {folder / 'ontology'}")
    return found[0]


def shapes_paths(folder: Path = PROFILE_DIR) -> list[Path]:
    """Return the profile's general SHACL shapes files (valid for any review)."""
    return sorted((folder / "shapes").glob("*.ttl"))


def slugify(text: str) -> str:
    """Return an IRI-safe slug (``"My RE review"`` -> ``"my-re-review"``)."""
    return _SLUG.sub("-", text.lower()).strip("-") or "review"


def default_base_iri(review_name: str) -> str:
    """Return the base IRI of a review's graph."""
    return f"{DATA_NAMESPACE}{slugify(review_name)}/"


def lpwc_roles(dimensions: list[str]) -> dict[str, tuple[str, str]]:
    """Return ``{dimension: (LPWC property, LPWC class)}`` for the liftable dimensions.

    ``TASK`` and ``SAT_TASK`` both lift to ``lpwcp:hasTask``. Dimensions the
    profile already lifts itself (exact names) are left out.
    """
    roles = {}
    for dim in dimensions:
        if dim in LPWC_LIFTING:
            continue
        last = dim.split("_", 1)[1] if "_" in dim else dim
        if last in LPWC_LIFTING:
            roles[dim] = LPWC_LIFTING[last]
    return roles


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def prepare_mapping(
    workdir: Path,
    *,
    base_iri: str,
    source_json: Path,
    source_name: str,
    dimensions: list[str] | None = None,
    profile_dir: Path = PROFILE_DIR,
    title: str = "",
    description: str = "",
    contract: dict | None = None,
) -> PreparedMapping:
    """Write into ``workdir`` a copy of the profile's mapping for one review.

    Three profile generations are supported:

    - **contract** (iteration 4+): the profile ships its mapping interface,
      ``mappings/ap_profile.py``. SciLEx writes the review's collection profile
      (:func:`collection_profile_v4`), and the profile's own code merges it into
      the effective profile and fills every placeholder (ORSD A2): SciLEx never
      rebuilds the placeholder values. ``contract`` passes the keys only this
      generation reads: ``creator``, ``generator``, ``config_hash``, ``survey``
      (path of the survey bundle) and ``grid`` (the grid declaration, see
      :func:`grid_declaration`).
    - **templates** (iteration 3): the RML / SPARQL files hold ``{{BASE}}``,
      ``{{JSON}}``, ``{{TITLE}}``... placeholders and the FnO functions read a
      *collection profile* (``SCILEX_PROFILE``). SciLEx fills the placeholders and
      writes the review's collection profile (:func:`collection_profile`).
    - **single collection** (iteration 1): the values of the sample review are
      literals; SciLEx rewrites them.

    Args:
        workdir: Empty folder that receives the adapted files.
        base_iri: Base IRI of the review's graph (ends with ``/``). With templates it
            must be ``https://w3id.org/scilex/data/<slug>/`` (the functions derive
            it from the slug).
        source_json: The review's generic JSON (see :mod:`scilex.kg.bib2json`).
        source_name: File name of the review's BibLaTeX export (for provenance).
        dimensions: The review's coding dimensions (its annotation grid).
            None keeps the profile's own list (iteration 1) or deduces them from
            the tags (templates).
        profile_dir: Folder of the pinned profile.
        title: Dataset title (templates).
        description: Dataset description (templates).

    Raises:
        ProfileError: If the profile is missing or no longer has the expected shape.
    """
    if not base_iri.endswith("/"):
        raise ValueError(f"The base IRI must end with '/': {base_iri}")
    mappings = profile_dir / "mappings"
    rml_files = sorted((mappings / "rml").glob("*.rml.ttl"))
    udf_files = sorted((mappings / "functions").glob("*.py"))
    ru_files = sorted((mappings / "sparql").glob("*.ru"))
    if not rml_files or len(udf_files) != 1 or not ru_files:
        raise ProfileError(
            f"The pinned profile in {profile_dir} is incomplete "
            "(run: python -m scilex.kg.sync_profile)"
        )
    if (mappings / CONTRACT_FILENAME).is_file():
        return _prepare_contract(
            workdir,
            profile_dir=profile_dir,
            base_iri=base_iri,
            source_json=source_json,
            source_name=source_name,
            dimensions=dimensions,
            title=title,
            description=description,
            **(contract or {}),
        )
    if any(PLACEHOLDER_MARK in _read(f) for f in rml_files):
        return _prepare_templates(
            workdir,
            rml_files=rml_files,
            udf_file=udf_files[0],
            ru_files=ru_files,
            base_iri=base_iri,
            source_json=source_json,
            source_name=source_name,
            dimensions=dimensions,
            title=title,
            description=description,
        )

    udfs_text = _read(udf_files[0])
    match = _BASE_IN_UDFS.search(udfs_text)
    if not match:
        raise ProfileError(f'No BASE = "..." in {udf_files[0].name}')
    upstream_base = match.group(1)
    # What must not survive the rewrite ("" when the review reuses the profile's own base).
    leftover = "" if upstream_base == base_iri else upstream_base

    sources = {s for f in rml_files for _, s in _RML_SOURCE.findall(_read(f))}
    if not sources:
        raise ProfileError("No rml:source in the RML mapping")
    upstream_bibs = {Path(s).stem + ".bib" for s in sources}

    def rewrite(text: str) -> str:
        text = text.replace(upstream_base, base_iri)
        for bib in upstream_bibs:
            text = text.replace(bib, source_name)
        return text

    slug = base_iri.rstrip("/").rsplit("/", 1)[-1]
    json_ref = source_json.resolve().as_posix()
    out_rml, out_ru = [], []
    for folder in ("rml", "functions", "sparql"):
        (workdir / folder).mkdir(parents=True, exist_ok=True)

    for path in rml_files:
        text = rewrite(_read(path))
        text = _RML_SOURCE.sub(lambda m: f'{m.group(1)}"{json_ref}"', text)
        text = _MAPPING_NS.sub(lambda m: f"{m.group(1)}{slug}#", text)
        out_rml.append(_write(workdir / "rml" / path.name, text, leftover))

    udfs = rewrite(udfs_text)
    udfs += "\n\n# --- Set by SciLEx (scilex.kg.profile.prepare_mapping) for this review ---\n"
    udfs += f"BASE = {base_iri!r}\n"
    if dimensions is not None:
        udfs += f"DIMENSIONS = {sorted(set(dimensions))!r}\n"
        udfs += "DIMENSIONS = set(DIMENSIONS)\n"
    # morph-kgc opens the functions file with the locale encoding (cp1252 on Windows).
    out_udfs = _write(
        workdir / "functions" / udf_files[0].name, ascii_source(udfs), leftover
    )

    for path in ru_files:
        out_ru.append(
            _write(workdir / "sparql" / path.name, rewrite(_read(path)), leftover)
        )

    roles = lpwc_roles(dimensions or [])
    if roles:
        out_ru.append(
            _write(
                workdir / "sparql" / "90-scilex-grid-lifting.ru",
                lifting_update(base_iri, roles),
                "",
            )
        )
    return PreparedMapping(workdir, out_rml, out_udfs, out_ru, base_iri)


# --- Template profiles (iteration 3+) -----------------------------------------

PLACEHOLDER_MARK = "{{BASE}}"
_PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")
# Tags SciLEx writes when pushing to Zotero, declared in every collection profile
# SciLEx generates (as the profile's own t84-tools profile does for raw SciLEx data).
SCILEX_DIMENSIONS = ("QUALI_SCORE", "REL_SCORE", "CITAT")
SCILEX_DIMENSION_PATTERNS = (r"COLLECT_KW\d+",)
SCILEX_PRESENCE_TAGS = ("HavePDF", "HaveHF", "HavePWC", "HaveGithub", "SciLexCollected")


def is_templated(profile_dir: Path = PROFILE_DIR) -> bool:
    """True when the pinned profile's mapping uses ``{{...}}`` placeholders (iter3+)."""
    return any(
        PLACEHOLDER_MARK in _read(p)
        for p in (profile_dir / "mappings" / "rml").glob("*.rml.ttl")
    )


def deduce_dimensions(source_json: Path) -> list[str]:
    """Return the ``DIMENSION`` prefixes of the ``DIMENSION:value`` keywords of a review."""
    data = json.loads(Path(source_json).read_text(encoding="utf-8"))
    found = set()
    for row in data.get("lists", []):
        if row.get("field") != "keywords":
            continue
        dim, sep, _ = str(row["value"]).partition(":")
        dim = re.sub(r"\s+", "_", dim.strip()).upper()
        if sep and re.fullmatch(r"[A-Z][A-Z0-9_]*", dim):
            found.add(dim)
    return sorted(found)


def collection_profile(
    slug: str,
    *,
    source_name: str,
    title: str,
    description: str,
    dimensions: list[str],
) -> dict:
    """The collection profile (``mappings/collections/<slug>.json`` format) of a review."""
    return {
        "slug": slug,
        "use_case": "SciLEx",
        "source": source_name,
        "title": title,
        "description": description,
        "tags": {
            "dimensions": sorted(set(dimensions) | set(SCILEX_DIMENSIONS)),
            "dimension_patterns": list(SCILEX_DIMENSION_PATTERNS),
            "dimension_aliases": {},
            "slash_form": False,
            "plain": {"PRESENCE": list(SCILEX_PRESENCE_TAGS)},
        },
    }


def _sparql_text(text: str) -> str:
    """Escape a value placed between double quotes in Turtle / SPARQL."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _prepare_templates(
    workdir: Path,
    *,
    rml_files: list[Path],
    udf_file: Path,
    ru_files: list[Path],
    base_iri: str,
    source_json: Path,
    source_name: str,
    dimensions: list[str] | None,
    title: str,
    description: str,
) -> PreparedMapping:
    from urllib.parse import quote

    slug = base_iri.rstrip("/").rsplit("/", 1)[-1]
    if base_iri != f"{DATA_NAMESPACE}{slug}/":
        raise ProfileError(
            f"This profile version derives the base IRI from the review slug: use "
            f"{DATA_NAMESPACE}<slug>/ (got {base_iri})."
        )
    for folder in ("rml", "functions", "sparql"):
        (workdir / folder).mkdir(parents=True, exist_ok=True)
    source = quote(source_name, safe="._-")  # used inside an IRI too
    if dimensions is None:
        dimensions = deduce_dimensions(source_json)
    profile = collection_profile(
        slug,
        source_name=source,
        title=title or slug,
        description=description or f"SciLEx review {slug}.",
        dimensions=dimensions,
    )
    profile_path = workdir / f"{slug}.collection.json"
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    values = {
        "BASE": base_iri,
        "JSON": source_json.resolve().as_posix(),
        "SLUG": slug,
        "TITLE": _sparql_text(profile["title"]),
        "DESCRIPTION": _sparql_text(profile["description"]),
        "SOURCE": source,
        "USE_CASE": profile["use_case"],
    }

    def fill(text: str, name: str) -> str:
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        left = _PLACEHOLDER.findall(text)
        if left:
            raise ProfileError(f"{name}: unknown placeholder(s) {sorted(set(left))}")
        return text

    out_rml = [
        _write(workdir / "rml" / p.name, fill(_read(p), p.name), "") for p in rml_files
    ]
    out_ru = [
        _write(workdir / "sparql" / p.name, fill(_read(p), p.name), "")
        for p in ru_files
    ]
    # morph-kgc opens the functions file with the locale encoding (cp1252 on Windows).
    out_udfs = _write(
        workdir / "functions" / udf_file.name, ascii_source(_read(udf_file)), ""
    )
    roles = lpwc_roles(dimensions)
    if roles:
        out_ru.append(
            _write(
                workdir / "sparql" / "90-scilex-grid-lifting.ru",
                lifting_update(base_iri, roles),
                "",
            )
        )
    return PreparedMapping(
        workdir,
        out_rml,
        out_udfs,
        out_ru,
        base_iri,
        env={"SCILEX_PROFILE": str(profile_path.resolve())},
        templated=True,
    )


# --- Contract profiles (iteration 4+) ----------------------------------------

CONTRACT_FILENAME = "ap_profile.py"
# Grid columns read by grid_declaration (SX-22). All optional.
GRID_TYPE_COLUMN = "type"
GRID_VALUES_COLUMN = "values"
GRID_BROADER_COLUMN = "broader"
GRID_IMPLIES_COLUMN = "implies"
GRID_OTHER_TO_COLUMN = "other_to"
GRID_LPWC_COLUMN = "lpwc"
VALUE_TYPES = ("binary", "closed", "magnitude", "integer", "open")


def maps_part(part: str, profile_dir: Path = PROFILE_DIR) -> bool:
    """True when the pinned profile maps the survey bundle's ``part`` (``$.part[*]``)."""
    needle = f"$.{part}[*]"
    return any(
        needle in _read(p) for p in (profile_dir / "mappings" / "rml").glob("*.rml.ttl")
    )


def contract_module(profile_dir: Path = PROFILE_DIR):
    """Load the profile's mapping interface (``mappings/ap_profile.py``), or None.

    The module is the profile's code, pinned with it and reviewed with the
    rest of ``scilex/kg/ap`` (standard library only).
    """
    import importlib.util
    import sys

    path = profile_dir / "mappings" / CONTRACT_FILENAME
    if not path.is_file():
        return None
    name = f"scilex_kg_ap_profile_{abs(hash(path.resolve()))}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _split_list(text: str) -> list[str]:
    return [v.strip() for v in re.split(r"[,|·]", text) if v.strip()]


def _rules(text: str, where: str) -> dict[str, list[str]]:
    """``"ner > ie; re > ie, nlp"`` -> ``{"ner": ["ie"], "re": ["ie", "nlp"]}``."""
    rules: dict[str, list[str]] = {}
    for part in (p.strip() for p in text.split(";")):
        if not part:
            continue
        left, sep, right = part.partition(">")
        if not sep or not left.strip() or not _split_list(right):
            raise ProfileError(f"{where}: '{part}' is not 'value > value, value'")
        rules.setdefault(left.strip(), []).extend(_split_list(right))
    return rules


def grid_declaration(grid) -> dict[str, dict]:
    """The grid declaration of a review (profile iteration 6, SX-22).

    Reads the optional columns of ``annotation_grid.csv``:

    - ``type``: ``binary``, ``closed``, ``magnitude``, ``integer`` or ``open``;
    - ``values``: the values of a closed dimension (``a, b, c``); else the
      grid's ``Allowed values`` column or the ``Values: ...`` end of its detail;
    - ``broader``: value hierarchy, ``narrow > broad, broad; narrow2 > broad``;
    - ``implies``: implication rules, ``value > required, required; ...``;
    - ``other_to``: for a binary dimension, the dimension of its other values;
    - ``lpwc``: LPWC role (``task``, ``dataset``, ``model``, ``method``).

    Returns:
        ``{dimension: {"values": {...}, "broader": {...}, "implies": {...}, "question": ...}}``
        with only the keys the grid gives. A grid without these columns gives
        bare dimensions, as before iteration 6.

    Raises:
        ProfileError: If a cell cannot be read.
    """
    from scilex.tagging.grid import (
        DETAIL_COLUMN,
        TAG_COLUMN,
        dimension_values,
        normalize_grid,
    )

    grid = normalize_grid(grid)
    out: dict[str, dict] = {}
    for _, row in grid.iterrows():
        name = str(row[TAG_COLUMN])
        cell = {c: str(row.get(c, "") or "").strip() for c in grid.columns}
        entry: dict = {}
        if cell.get(DETAIL_COLUMN):
            entry["question"] = cell[DETAIL_COLUMN]
        kind = cell.get(GRID_TYPE_COLUMN, "").lower()
        if kind:
            if kind not in VALUE_TYPES:
                raise ProfileError(
                    f"{name}: unknown value type '{kind}' (one of {', '.join(VALUE_TYPES)})"
                )
            values: dict = {"type": kind}
            if kind == "closed":
                listed = _split_list(cell.get(GRID_VALUES_COLUMN, "")) or (
                    dimension_values(grid, name)
                )
                if not listed:
                    raise ProfileError(
                        f"{name}: a closed dimension needs its values ('values' column)"
                    )
                values["list"] = listed
            if cell.get(GRID_OTHER_TO_COLUMN):
                if kind != "binary":
                    raise ProfileError(f"{name}: 'other_to' is for binary dimensions")
                values["other_to"] = cell[GRID_OTHER_TO_COLUMN].upper()
            entry["values"] = values
        for column in (GRID_BROADER_COLUMN, GRID_IMPLIES_COLUMN):
            if cell.get(column):
                entry[column] = _rules(cell[column], f"{name} {column}")
        if cell.get(GRID_LPWC_COLUMN):
            entry["lpwc"] = cell[GRID_LPWC_COLUMN].lower()
        out[name] = entry
    return out


def collection_profile_v4(
    slug: str,
    *,
    base_iri: str,
    source_name: str,
    title: str,
    description: str,
    dimensions: list[str],
    grid: dict[str, dict] | None = None,
    creator: str = "",
    generator: str = "",
    config_hash: str = "",
    survey: str = "",
) -> dict:
    """The collection profile (schemaVersion 1, profile iteration 4+) of a review.

    It extends the profile's ``_scilex-defaults`` (the tags SciLEx writes itself),
    so it declares only the review's own grid. A grid dimension whose last part
    names an LPWC role (``SAT_TASK``, ``DATASET``) is lifted into LPWC.
    """
    grid = grid or {}
    declared = []
    for name in sorted(set(dimensions) | set(grid)):
        entry = {"name": name, "origin": "grid"}
        extra = dict(grid.get(name, {}))
        last = name.split("_", 1)[1] if "_" in name else name
        if "lpwc" not in extra and last in LPWC_LIFTING:
            extra["lpwc"] = LPWC_LIFTING[last][1]
        entry.update(extra)
        declared.append(entry)
    profile = {
        "schemaVersion": 1,
        "slug": slug,
        "base": base_iri,
        "use_case": "SciLEx",
        "source": source_name,
        "title": title,
        "description": description,
        "extends": ["_scilex-defaults"],
        "tags": {
            "dimensions": declared,
            "dimension_patterns": [],
            "dimension_aliases": {},
            "slash_form": False,
            "plain": {},
        },
    }
    for key, value in (
        ("creator", creator),
        ("generator", generator),
        ("config_hash", config_hash),
        ("survey", survey),
    ):
        if value:
            profile[key] = value
    return profile


def _prepare_contract(
    workdir: Path,
    *,
    profile_dir: Path,
    base_iri: str,
    source_json: Path,
    source_name: str,
    dimensions: list[str] | None,
    title: str,
    description: str,
    creator: str = "",
    generator: str = "",
    config_hash: str = "",
    survey: Path | str | None = None,
    grid: dict[str, dict] | None = None,
) -> PreparedMapping:
    api = contract_module(profile_dir)
    mappings = profile_dir / "mappings"
    slug = slugify(base_iri.rstrip("/").rsplit("/", 1)[-1])
    for folder in ("rml", "functions", "sparql"):
        (workdir / folder).mkdir(parents=True, exist_ok=True)
    if dimensions is None:
        dimensions = deduce_dimensions(source_json)
    survey_path = Path(survey).resolve() if survey else None
    raw = collection_profile_v4(
        slug,
        base_iri=base_iri,
        source_name=source_name,
        title=title or slug,
        description=description or f"SciLEx review {slug}.",
        dimensions=dimensions,
        grid=grid,
        creator=creator,
        generator=generator,
        config_hash=config_hash,
        survey=survey_path.name if survey_path else "",
    )
    raw_path = workdir / f"{slug}.json"
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        effective = api.load_profile(raw_path, search=[mappings / "collections"])
        effective_path = api.write_effective_profile(
            effective, workdir / f"{slug}.effective.json"
        )
        values = api.placeholder_values(effective, source_json.resolve().as_posix())
        # The profile reads the bundle from its own raw_data/ folder; SciLEx's is elsewhere.
        values["SURVEY"] = (
            api.escape_string(survey_path.as_posix()) if survey_path else ""
        )

        def fill(path: Path) -> str:
            return api.expand(_read(path), values, path.name)

        out_rml = [
            _write(workdir / "rml" / p.name, fill(p), "")
            for p in sorted((mappings / "rml").glob("*.rml.ttl"))
            if survey_path or "survey" not in p.name
        ]
        out_ru = [
            _write(workdir / "sparql" / p.name, fill(p), "")
            for p in sorted((mappings / "sparql").glob("*.ru"))
        ]
    except ValueError as exc:  # the contract's ProfileError is a ValueError
        raise ProfileError(str(exc)) from exc
    udf_file = next((mappings / "functions").glob("*.py"))
    # morph-kgc opens the functions file with the locale encoding (cp1252 on Windows).
    out_udfs = _write(
        workdir / "functions" / udf_file.name, ascii_source(_read(udf_file)), ""
    )
    return PreparedMapping(
        workdir,
        out_rml,
        out_udfs,
        out_ru,
        base_iri,
        env={"SCILEX_PROFILE": str(Path(effective_path).resolve())},
        templated=True,
        contract=True,
    )


def ascii_source(code: str) -> str:
    r"""Return Python ``code`` with every non-ASCII character written as ``\uXXXX``.

    Same meaning in comments, string literals and ``re`` patterns (``re`` reads
    ``\u`` escapes in raw strings too), which is all the profile's functions
    contain. The result compiles to the same constants.
    """

    def escape(char: str) -> str:
        code_point = ord(char)
        if code_point < 128:
            return char
        return (
            f"\\u{code_point:04x}" if code_point <= 0xFFFF else f"\\U{code_point:08x}"
        )

    return "".join(escape(c) for c in code)


def _write(path: Path, text: str, upstream_base: str) -> Path:
    if upstream_base and upstream_base in text:
        raise ProfileError(f"{path.name} still refers to {upstream_base}")
    path.write_text(text, encoding="utf-8")
    return path


def lifting_update(base_iri: str, roles: dict[str, tuple[str, str]]) -> str:
    """SPARQL UPDATE lifting a review's grid dimensions into LPWC, like the profile's sparql/04."""
    values = "\n".join(
        f"    (<{base_iri}coding/{dim}> lpwcp:{prop} lpwc:{cls})"
        for dim, (prop, cls) in sorted(roles.items())
    )
    return f"""# Generated by SciLEx: LPWC lifting of the review's own grid dimensions
# (the profile's sparql/04 lifts TASK, DATASET, PTM, MODEL and ARCHI by exact name).

PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
PREFIX foaf:    <http://xmlns.com/foaf/0.1/>
PREFIX lpwc:    <https://linkedpaperswithcode.com/class/>
PREFIX lpwcp:   <https://linkedpaperswithcode.com/property/>

INSERT {{ ?br ?lpwcProp ?c . ?c a ?lpwcClass ; foaf:name ?label . ?br a lpwc:paper }}
WHERE {{
  VALUES (?scheme ?lpwcProp ?lpwcClass) {{
{values}
  }}
  ?br dcterms:subject ?c .
  ?c skos:inScheme ?scheme ; skos:prefLabel ?label .
  FILTER (!REGEX(STR(?c), "/(unknown|not-specified|none)$"))
}}
"""
