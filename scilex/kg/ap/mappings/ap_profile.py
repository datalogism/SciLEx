"""The mapping interface of the scilex-lpwc-ap profile (iteration 4).

One module, standard library only, used by ``scripts/build_iteration.py`` and by
SciLEx (``scilex-build-kg``) alike, so that both run the profile's templates the
same way and SciLEx no longer has to guess them (iter4 proposal, A2 / A3 / A6):

* :func:`load_profile` reads a collection profile (``collections/<slug>.json``),
  checks it, and merges the reference profiles it ``extends``
  (``_scilex-defaults``) into the **effective profile**;
* :func:`write_effective_profile` writes it where the FnO functions read it
  (environment variable ``SCILEX_PROFILE``);
* :data:`PLACEHOLDERS` is the **placeholder contract** of ``rml/*.rml.ttl`` and
  ``sparql/*.ru``: name, meaning and escaping (documented in ``README.md``);
* :func:`placeholder_values` fills it from a profile, :func:`expand` substitutes
  and **fails on an unknown or unfilled placeholder**.

Run ``python mappings/ap_profile.py collections/<slug>.json`` to print the effective
profile and the placeholder values.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
DATA_NS = "https://w3id.org/scilex/data/"
PROFILE_IRI = "https://w3id.org/scilex/ap/lpwc"
PROFILE_VERSION = "0.8.0"
SCHEMA_VERSION = 1
DEFAULT_EXTENDS = ["_scilex-defaults"]
DEFAULT_GENERATOR = "scilex-lpwc-ap scripts/build_iteration.py"

ORIGINS = ("scilex", "enrichment", "grid", "workflow")
PLAIN_ORIGIN_DEFAULTS = {
    "WORKFLOW": "workflow",
    "PRESENCE": "scilex",
    "ACQUISITION": "scilex",
}
# lpwc role -> (LPWC property, LPWC class), sparql/04
LPWC_ROLES = {
    "task": ("hasTask", "task"),
    "dataset": ("usesDataset", "dataset"),
    "model": ("hasModel", "model"),
    "method": ("hasMethod", "method"),
}

# ---------------------------------------------------------------------------
# Placeholder contract
# ---------------------------------------------------------------------------

#: name -> (meaning, escaping). Escapings:
#:   iri     an absolute IRI, written inside <...>; checked, never escaped
#:   segment one IRI path segment, percent-encoded
#:   string  the inside of a "..." literal (Turtle / SPARQL): \ " and line breaks escaped
#:   path    a file path inside a "..." RML literal: forward slashes, string-escaped
#:   values  rows of a SPARQL VALUES block, generated from the profile
PLACEHOLDERS: dict[str, tuple[str, str]] = {
    "BASE": ("namespace of the collection's resources, ends with '/'", "iri"),
    "JSON": (
        "generic JSON of the collection (bib2json output), RML rml:source",
        "path",
    ),
    "SLUG": ("slug of the collection", "string"),
    "TITLE": ("dataset title", "string"),
    "DESCRIPTION": ("dataset description", "string"),
    "USE_CASE": ("use case (UCA-UCD) or SciLEx", "string"),
    "SOURCE": ("file name of the BibLaTeX export, as text", "string"),
    "SOURCE_IRI": ("file name of the BibLaTeX export, as an IRI segment", "segment"),
    "CREATOR": ("IRI of the review owner (ORCID iD), or empty", "iri"),
    "GENERATOR": ("software that ran the mapping, with its version", "string"),
    "CONFIG_HASH": ("hash of the configuration in force, or empty", "string"),
    "PROFILE_VERSION_IRI": ("version IRI of this profile (owl:versionIRI)", "iri"),
    "LPWC_LIFTING": ("(?scheme ?lpwcProp ?lpwcClass) rows, sparql/04", "values"),
    "LPWC_INTRODUCED": ("(?createdScheme ?targetScheme) rows, sparql/04", "values"),
    "LPWC_ALIGN": (
        "(?schemeA ?schemeB) rows of dimensions with the same LPWC class, sparql/04",
        "values",
    ),
    # iter5 (ORSD SR1): the survey bundle; rml/*survey*.rml.ttl is only run when the profile has one
    "SURVEY": (
        "survey bundle of the collection (survey.json), RML rml:source, or empty",
        "path",
    ),
    # iter6 (ORSD UCR4, UCR20): the grid declaration (dimension "values" and "broader")
    "GRID_VALUE_TYPES": ("(?scheme ?valueType) rows, sparql/03c", "values"),
    "GRID_ALLOWED": (
        "(?scheme ?key) rows: allowed value keys of closed dimensions, sparql/03c",
        "values",
    ),
    "GRID_SPLIT": (
        "(?scheme ?target) rows: binary dimension -> dimension of its other values, sparql/03c",
        "values",
    ),
    "GRID_BROADER": (
        "(?narrower ?broader) concept rows of the value hierarchy, sparql/03c",
        "values",
    ),
    "GRID_IMPLIES": (
        "(?premise ?required) concept rows of the implication rules, sparql/03c",
        "values",
    ),
    # iter8 (ORSD VR9): global reference table mappings/alignments/book-series-issn.json
    "KNOWN_SERIES": (
        "(?issn ?name) rows of book series often exported as journals, sparql/07",
        "values",
    ),
}
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
_IRI = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:[^\s<>\"{}|\\^`]*$")


class ProfileError(ValueError):
    """A collection profile or a template does not follow the contract."""


def escape_string(text: str) -> str:
    """Escape ``text`` for the inside of a double-quoted Turtle / SPARQL literal."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def escape_segment(text: str) -> str:
    return quote(text, safe="._-~")


def check_iri(text: str, name: str, *, empty_ok: bool = False) -> str:
    if text == "" and empty_ok:
        return text
    if not _IRI.match(text):
        raise ProfileError(f"{{{{{name}}}}}: not an absolute IRI: {text!r}")
    return text


def expand(text: str, values: dict[str, str], name: str = "template") -> str:
    """Fill the ``{{NAME}}`` placeholders of ``text``.

    Raises:
        ProfileError: if ``text`` uses a placeholder outside :data:`PLACEHOLDERS`
            or one that ``values`` does not fill.
    """
    used = set(_PLACEHOLDER.findall(text))
    unknown = used - set(PLACEHOLDERS)
    if unknown:
        raise ProfileError(
            f"{name}: unknown placeholder(s) {sorted(unknown)} "
            f"(the contract is mappings/ap_profile.py PLACEHOLDERS)"
        )
    missing = used - set(values)
    if missing:
        raise ProfileError(f"{name}: placeholder(s) {sorted(missing)} not filled")
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def _dim(d) -> dict:
    """A dimension entry as a dict (a plain string is a manual grid dimension)."""
    return {"name": d} if isinstance(d, str) else dict(d)


def _pattern(p) -> dict:
    return {"pattern": p} if isinstance(p, str) else dict(p)


def check(p: dict, where: str = "profile") -> None:
    """The checks of collection-profile.schema.json that matter to the mapping
    (no jsonschema dependency; tests/scilex validates against the full schema)."""
    for key in ("slug", "source", "title", "description", "tags"):
        if key not in p:
            raise ProfileError(f"{where}: missing '{key}'")
    if p.get("schemaVersion", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ProfileError(
            f"{where}: schemaVersion {p['schemaVersion']} is not supported "
            f"(this profile version reads {SCHEMA_VERSION})"
        )
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", p["slug"]):
        raise ProfileError(f"{where}: bad slug {p['slug']!r}")
    if "base" in p and not (p["base"].endswith("/") and _IRI.match(p["base"])):
        raise ProfileError(f"{where}: 'base' must be an absolute IRI ending with '/'")
    for d in map(_dim, p["tags"].get("dimensions", [])):
        if d.get("origin", "grid") not in ORIGINS:
            raise ProfileError(
                f"{where}: {d['name']}: unknown origin {d.get('origin')!r}"
            )
        if "lpwc" in d and d["lpwc"] not in (*LPWC_ROLES, "introducedBy"):
            raise ProfileError(f"{where}: {d['name']}: unknown lpwc role {d['lpwc']!r}")
        if d.get("lpwc") == "introducedBy" and "target" not in d:
            raise ProfileError(
                f"{where}: {d['name']}: lpwc 'introducedBy' needs a 'target'"
            )
        v = d.get("values")
        if v is not None:
            if v.get("type") not in VALUE_TYPES:
                raise ProfileError(
                    f"{where}: {d['name']}: unknown value type {v.get('type')!r}"
                )
            if v["type"] == "closed" and not v.get("list"):
                raise ProfileError(
                    f"{where}: {d['name']}: a closed dimension needs a 'list'"
                )
            if "other_to" in v and v["type"] != "binary":
                raise ProfileError(
                    f"{where}: {d['name']}: 'other_to' is for binary dimensions"
                )


def merge(under: dict, over: dict) -> dict:
    """Merge the tag grammar of ``over`` onto ``under``; ``over`` wins."""
    out = copy.deepcopy(over)
    t_u, t_o = under["tags"], out["tags"]
    dims = {d["name"]: d for d in map(_dim, t_u.get("dimensions", []))}
    for d in map(_dim, t_o.get("dimensions", [])):
        dims[d["name"]] = d  # the profile's own declaration wins (UCR10)
    t_o["dimensions"] = list(dims.values())
    pats = {x["pattern"]: x for x in map(_pattern, t_u.get("dimension_patterns", []))}
    pats.update(
        {x["pattern"]: x for x in map(_pattern, t_o.get("dimension_patterns", []))}
    )
    t_o["dimension_patterns"] = list(pats.values())
    t_o["dimension_aliases"] = {
        **t_u.get("dimension_aliases", {}),
        **t_o.get("dimension_aliases", {}),
    }
    t_o["slash_form"] = t_o.get("slash_form", t_u.get("slash_form", False))
    own = {tag.upper() for tags in t_o.get("plain", {}).values() for tag in tags}
    plain = {
        g: [x for x in tags if x.upper() not in own]
        for g, tags in t_u.get("plain", {}).items()
    }
    for g, tags in t_o.get("plain", {}).items():
        plain[g] = plain.get(g, []) + [x for x in tags if x not in plain.get(g, [])]
    t_o["plain"] = {g: tags for g, tags in plain.items() if tags}
    t_o["plain_origins"] = {
        **t_u.get("plain_origins", {}),
        **t_o.get("plain_origins", {}),
    }
    return out


def load_profile(path: Path | str, search: list[Path] | None = None) -> dict:
    """Read a collection profile and return its effective profile.

    ``extends`` names are looked up next to the profile, then in ``search``, then in
    this module's ``collections/``. The result has every default filled in
    (``base``, ``generator``...), dimensions as dicts with an ``origin``, and
    ``"effective": true``.
    """
    path = Path(path)
    p = json.loads(path.read_text(encoding="utf-8"))
    check(p, path.name)
    dirs = [path.parent, *(search or []), HERE / "collections"]
    eff = {"tags": {"dimensions": []}}
    for name in p.get("extends", DEFAULT_EXTENDS):
        ref = next(
            (d / f"{name}.json" for d in dirs if (d / f"{name}.json").is_file()), None
        )
        if ref is None:
            raise ProfileError(
                f"{path.name}: extends {name!r}, not found in {[str(d) for d in dirs]}"
            )
        r = json.loads(ref.read_text(encoding="utf-8"))
        check(r, ref.name)
        eff = merge(eff, r)
    eff = merge(eff, p)
    for d in eff["tags"]["dimensions"]:
        d.setdefault("origin", "grid")
    for x in eff["tags"]["dimension_patterns"]:
        x.setdefault("origin", "grid")
    eff["tags"]["plain_origins"] = {
        g: eff["tags"]["plain_origins"].get(g, PLAIN_ORIGIN_DEFAULTS.get(g, "grid"))
        for g in eff["tags"]["plain"]
    }
    eff.setdefault("base", f"{DATA_NS}{eff['slug']}/")
    eff.setdefault("use_case", "")
    eff.setdefault("generator", DEFAULT_GENERATOR)
    eff.pop("extends", None)
    eff.pop("$schema", None)
    eff["schemaVersion"] = SCHEMA_VERSION
    eff["effective"] = True
    return eff


def write_effective_profile(eff: dict, path: Path | str) -> Path:
    """Write the effective profile for the FnO functions (``SCILEX_PROFILE``)."""
    path = Path(path)
    path.write_text(json.dumps(eff, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _rows(rows: list[tuple[str, ...]]) -> str:
    return "\n".join("    (" + " ".join(r) + ")" for r in rows)


def lpwc_values(eff: dict) -> dict[str, str]:
    """The three VALUES blocks of sparql/04, from the dimensions' ``lpwc`` roles."""
    base = eff["base"]
    dims = eff["tags"]["dimensions"]
    lifting, introduced, by_class = [], [], {}
    for d in dims:
        role = d.get("lpwc")
        if role in LPWC_ROLES:
            prop, cls = LPWC_ROLES[role]
            lifting.append(
                (f"<{base}coding/{d['name']}>", f"lpwcp:{prop}", f"lpwc:{cls}")
            )
            by_class.setdefault(cls, []).append(d["name"])
        elif role == "introducedBy":
            introduced.append(
                (f"<{base}coding/{d['name']}>", f"<{base}coding/{d['target']}>")
            )
    # equal keys of two dimensions with the same LPWC class are the same thing
    # (UCD: PTM and MODEL); the later-declared one points to the earlier one's partner
    align = []
    for names in by_class.values():
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                align.append((f"<{base}coding/{a}>", f"<{base}coding/{b}>"))
    return {
        "LPWC_LIFTING": _rows(lifting),
        "LPWC_INTRODUCED": _rows(introduced),
        "LPWC_ALIGN": _rows(align),
    }


# iter6: value types of the grid declaration -> sxv individuals (ontology 00-ap-core.ttl)
VALUE_TYPES = {
    "binary": "sxv:BinaryValues",
    "closed": "sxv:ClosedValues",
    "magnitude": "sxv:MagnitudeValues",
    "integer": "sxv:IntegerValues",
    "open": "sxv:OpenValues",
}


def value_key(val: str) -> str:
    """Key of a categorical value in its concept IRI (same rule as the FnO function
    value_key of functions/scilex_udfs.py for non-numeric values)."""
    upper = val.strip().upper()
    if val.strip() in ("", "?"):
        return "unknown"
    if upper in ("NSP", "NS"):
        return "not-specified"
    if upper == "NONE":
        return "none"
    return re.sub(r"[^0-9a-z.]+", "", val.strip().lower()) or quote(
        val.strip().lower(), safe=""
    )


def _concept(base: str, dim: str, val: str) -> str:
    return f"<{base}coding/{quote(dim, safe='')}/{quote(value_key(val), safe='')}>"


def grid_values(eff: dict) -> dict[str, str]:
    """The VALUES blocks of sparql/03c, from the dimensions' ``values``, ``broader`` and ``implies``."""
    base = eff["base"]
    types, allowed, split, broader, implies = [], [], [], [], []
    for d in eff["tags"]["dimensions"]:
        scheme = f"<{base}coding/{quote(d['name'], safe='')}>"
        v = d.get("values")
        if v:
            types.append((scheme, VALUE_TYPES[v["type"]]))
            for val in v.get("list", []):
                allowed.append((scheme, '"' + escape_string(value_key(val)) + '"'))
            if "other_to" in v:
                split.append(
                    (scheme, f"<{base}coding/{quote(v['other_to'], safe='')}>")
                )
        for narrow, wider in d.get("broader", {}).items():
            for w in wider:
                broader.append(
                    (_concept(base, d["name"], narrow), _concept(base, d["name"], w))
                )
        for premise, required in d.get("implies", {}).items():
            for r in required:
                implies.append(
                    (_concept(base, d["name"], premise), _concept(base, d["name"], r))
                )
    return {
        "GRID_VALUE_TYPES": _rows(types),
        "GRID_ALLOWED": _rows(allowed),
        "GRID_SPLIT": _rows(split),
        "GRID_BROADER": _rows(broader),
        "GRID_IMPLIES": _rows(implies),
    }


def known_series() -> dict[str, str]:
    """iter8: the VALUES rows of mappings/alignments/book-series-issn.json."""
    table = json.loads(
        (Path(__file__).parent / "alignments" / "book-series-issn.json").read_text(
            encoding="utf-8"
        )
    )["series"]
    rows = [
        (f'"{escape_string(issn)}"', f'"{escape_string(name)}"')
        for issn, name in sorted(table.items())
    ]
    return {"KNOWN_SERIES": _rows(rows)}


def placeholder_values(eff: dict, json_path: str) -> dict[str, str]:
    """Every placeholder of the contract, filled and escaped for one collection."""
    values = {
        "BASE": check_iri(eff["base"], "BASE"),
        "JSON": escape_string(
            Path(json_path).as_posix() if os.sep != "/" else json_path
        ),
        "SLUG": escape_string(eff["slug"]),
        "TITLE": escape_string(eff["title"]),
        "DESCRIPTION": escape_string(eff["description"]),
        "USE_CASE": escape_string(eff.get("use_case", "")),
        "SOURCE": escape_string(eff["source"]),
        "SOURCE_IRI": escape_segment(eff["source"]),
        "CREATOR": check_iri(eff.get("creator", ""), "CREATOR", empty_ok=True),
        "GENERATOR": escape_string(eff.get("generator", DEFAULT_GENERATOR)),
        "CONFIG_HASH": escape_string(eff.get("config_hash", "")),
        "PROFILE_VERSION_IRI": f"{PROFILE_IRI}/{PROFILE_VERSION}",
        "SURVEY": escape_string(
            f"raw_data/{eff['survey']}" if eff.get("survey") else ""
        ),
        **lpwc_values(eff),
        **grid_values(eff),
        **known_series(),
    }
    assert set(values) == set(PLACEHOLDERS), set(values) ^ set(PLACEHOLDERS)
    return values


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python mappings/ap_profile.py collections/<slug>.json")
    e = load_profile(sys.argv[1])
    print(json.dumps(e, ensure_ascii=False, indent=1))
    for k, v in placeholder_values(e, "raw_data/<source>.json").items():
        print(f"{{{{{k}}}}} = {v}")
