"""Knowledge graph built with the scilex-lpwc-ap application profile (scilex.kg)."""

import importlib.util
import json
import re
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import DCTERMS

from scilex.kg import bib2json
from scilex.kg.build import citation_dict_line, clean_tables
from scilex.kg.profile import (
    PROFILE_DIR,
    ascii_source,
    default_base_iri,
    lpwc_roles,
    prepare_mapping,
    read_version,
)
from scilex.kg.sync_profile import profile_root, select_files

CITO = Namespace("http://purl.org/spar/cito/")
LPWCP = Namespace("https://linkedpaperswithcode.com/property/")
BASE = "https://w3id.org/scilex/data/my-review/"

HAS_KG_DEPS = all(
    importlib.util.find_spec(m) for m in ("morph_kgc", "pyoxigraph")
)

BIB = r"""
@inproceedings{doe_first_2021,
	title = {A {BERT} Study of Relation Extraction},
	doi = {10.1000/first},
	url = {https://example.org/paper%201},
	pages = {10--20},
	booktitle = {Proceedings of {ACL}},
	author = {Doe, Jane and Smith, John},
	date = {2021-05-01},
	note = {\{'citing': ['10.1000/second', ''], 'cited': []\}
Archive ID: arXiv:2101.00001
PDF URL: https://example.org/first.pdf},
	keywords = {{SAT\_TASK}:{NER}, {DONE}, {HavePDF}, {QUALI\_SCORE}:3},
	annotation = {first remark},
	annotation = {second remark},
}

@article{roe_second_2022,
	title = {Second Paper},
	doi = {10.1000/second},
	journaltitle = {Journal of Tests},
	author = {Roe, Richard},
	date = {2022},
	note = {\{'citing': [], 'cited': ['10.1000/first']\}},
	keywords = {{SAT\_TASK}:{RelationClassif}, {SAT\_DATASET}:Tacred},
}
"""


@pytest.fixture
def bib_file(tmp_path: Path) -> Path:
    path = tmp_path / "my-review.bib"
    path.write_text(BIB, encoding="utf-8")
    return path


# --- stage 1: BibLaTeX -> generic JSON ---------------------------------------


def test_bib2json_keeps_tex_ligatures_and_verbatim_fields(bib_file):
    data = bib2json.convert(bib_file)
    first = next(e for e in data["entries"] if e["ID"] == "doe_first_2021")
    assert first["title"] == "A BERT Study of Relation Extraction"
    assert first["pages"] == "10--20"  # not an en dash
    assert first["url"] == "https://example.org/paper%201"  # "%" is not a comment
    assert "''" in first["note"]  # not a typographic quote


def test_bib2json_repeated_field_keeps_first_value(bib_file):
    first = next(e for e in bib2json.convert(bib_file)["entries"] if e["ID"] == "doe_first_2021")
    assert first["annotation"] == "first remark"
    assert first["author"] == "Doe, Jane and Smith, John"  # enclosing braces removed


def test_bib2json_splits_creators_and_keywords(bib_file):
    data = bib2json.convert(bib_file)
    names = [(c["entry"], c["position"], c["full"]) for c in data["creators"]]
    assert ("doe_first_2021", 1, "Jane Doe") in names
    assert ("doe_first_2021", 2, "John Smith") in names
    tags = [r["value"] for r in data["lists"] if r["entry"] == "doe_first_2021"]
    assert tags == ["SAT_TASK:NER", "DONE", "HavePDF", "QUALI_SCORE:3"]


def test_strip_enclosing_only_when_the_braces_enclose_everything():
    assert bib2json.strip_enclosing("{abc}") == "abc"
    assert bib2json.strip_enclosing("{A} and {B}") == "{A} and {B}"
    assert bib2json.strip_enclosing('"abc"') == "abc"


# --- SciLEx clean-up -----------------------------------------------------------


def test_citation_dict_line_ignores_extra_lines():
    note = "{'citing': ['10.1/a'], 'cited': []}\nArchive ID: x\nPDF URL: https://e.org"
    assert citation_dict_line(note) == "{'citing': ['10.1/a'], 'cited': []}"
    assert citation_dict_line("Some free text {not a dict}") is None


def test_clean_tables_drops_automation_tags_and_isolates_notes(bib_file):
    data, dropped, cleaned = clean_tables(bib2json.convert(bib_file))
    assert dropped == 2  # HavePDF, QUALI_SCORE:3
    assert "HavePDF" not in [r["value"] for r in data["lists"]]
    assert cleaned == 1
    first = next(e for e in data["entries"] if e["ID"] == "doe_first_2021")
    assert first["note"].startswith("{") and first["note"].endswith("}")


# --- adapting the profile's mapping to a review --------------------------------


def test_pinned_profile_is_present():
    version = read_version()
    assert version.get("commit")
    assert version.get("version_iri", "").startswith("https://w3id.org/scilex/ap/lpwc/")


def test_lpwc_roles_match_grid_prefixes():
    roles = lpwc_roles(["SAT_TASK", "SAT_DATASET", "SAT_MODEL", "SAT_LANG", "TASK"])
    assert roles == {
        "SAT_TASK": ("hasTask", "task"),
        "SAT_DATASET": ("usesDataset", "dataset"),
        "SAT_MODEL": ("hasModel", "model"),
    }  # TASK is already lifted by the profile itself


def test_prepare_mapping_fills_the_templates_for_the_review(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    mapping = prepare_mapping(
        tmp_path / "mapping",
        base_iri=BASE,
        source_json=source,
        source_name="my review.bib",
        dimensions=["SAT_TASK", "SAT_LANG"],
        title='A "quoted" title',
    )
    assert mapping.templated
    texts = [p.read_text(encoding="utf-8") for p in (*mapping.rml, *mapping.sparql)]
    assert not any(re.search(r"{{[A-Z_]+}}", t) for t in texts)  # all filled
    assert not any("re-slr" in t for t in texts)
    assert source.resolve().as_posix() in texts[0]
    assert any('A \\"quoted\\" title' in t for t in texts)  # escaped in SPARQL strings
    assert any("source/my%20review.bib" in t for t in texts)  # IRI-safe source name
    assert mapping.udfs.read_text(encoding="utf-8").isascii()  # morph-kgc: locale encoding
    # The collection profile the functions read (SCILEX_PROFILE).
    profile = json.loads(Path(mapping.env["SCILEX_PROFILE"]).read_text(encoding="utf-8"))
    assert profile["slug"] == "my-review"
    assert {"SAT_TASK", "SAT_LANG", "QUALI_SCORE"} <= set(profile["tags"]["dimensions"])
    assert r"COLLECT_KW\d+" in profile["tags"]["dimension_patterns"]
    lifting = [p for p in mapping.sparql if p.name.startswith("90-")]
    assert lifting and f"<{BASE}coding/SAT_TASK> lpwcp:hasTask" in lifting[0].read_text()


def test_prepare_mapping_refuses_a_base_the_profile_cannot_use(tmp_path):
    from scilex.kg.profile import ProfileError

    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ProfileError, match="slug"):
        prepare_mapping(
            tmp_path / "m", base_iri="https://example.org/kg/", source_json=source,
            source_name="x.bib",
        )


def test_dimensions_are_deduced_without_a_grid(tmp_path):
    from scilex.kg.profile import deduce_dimensions

    source = tmp_path / "s.json"
    source.write_text(json.dumps({"lists": [
        {"field": "keywords", "value": "SAT_TASK:NER"},
        {"field": "keywords", "value": "free keyword"},
        {"field": "keywords", "value": "Collect_KW1:rag"},
    ]}), encoding="utf-8")
    assert deduce_dimensions(source) == ["COLLECT_KW1", "SAT_TASK"]


def test_ascii_source_keeps_the_meaning_of_constants():
    code = 'S = "10⁵ °"\nimport re\nM = re.fullmatch(r"10([⁰-⁹]+)", "10⁵")\n'
    namespace_a, namespace_b = {}, {}
    exec(code, namespace_a)
    exec(ascii_source(code), namespace_b)
    assert ascii_source(code).isascii()
    assert namespace_a["S"] == namespace_b["S"]
    assert bool(namespace_a["M"]) == bool(namespace_b["M"])


def test_default_base_iri():
    assert default_base_iri("My RE review!") == "https://w3id.org/scilex/data/my-re-review/"


# --- choosing the files of a profile version ----------------------------------


def test_profile_root_prefers_final_then_latest_iteration():
    paths = ["iterations/iter1/ontology/a.ttl", "iterations/iter2/ontology/a.ttl"]
    assert profile_root(paths) == "iterations/iter2"
    assert profile_root([*paths, "final/ontology/a.ttl"]) == "final"


def test_select_files_maps_the_profile_layout():
    root = "iterations/iter2"
    paths = [
        f"{root}/ontology/ap.ttl",
        f"{root}/ontology/modules/00-core.ttl",
        f"{root}/mappings/rml/bib.rml.ttl",
        f"{root}/mappings/functions/udfs.py",
        f"{root}/mappings/sparql/01-a.ru",
        f"{root}/shapes/manual/general/g.shapes.ttl",
        f"{root}/shapes/manual/specific/s.shapes.ttl",
    ]
    assert select_files(paths, root) == {
        f"{root}/ontology/ap.ttl": "ontology/ap.ttl",
        f"{root}/mappings/rml/bib.rml.ttl": "mappings/rml/bib.rml.ttl",
        f"{root}/mappings/functions/udfs.py": "mappings/functions/udfs.py",
        f"{root}/mappings/sparql/01-a.ru": "mappings/sparql/01-a.ru",
        f"{root}/shapes/manual/general/g.shapes.ttl": "shapes/g.shapes.ttl",
    }


# --- end to end ------------------------------------------------------------------


@pytest.mark.skipif(not HAS_KG_DEPS, reason="needs the 'kg' extra (morph-kgc, pyoxigraph)")
def test_build_knowledge_graph_end_to_end(bib_file, tmp_path):
    from scilex.kg.build import build_knowledge_graph

    output = tmp_path / "kg" / "my-review.ttl"
    report = build_knowledge_graph(
        bib_file,
        output,
        review_name="My review",
        base_iri=BASE,
        dimensions=["SAT_TASK", "SAT_DATASET"],
        run_validation=False,
    )
    # iter3+ profiles map SciLEx's own tags (HavePDF, QUALI_SCORE...): none dropped.
    assert report.papers == 2 and report.dropped_tags == 0 and report.notes_cleaned == 1
    graph = Graph().parse(output)
    first, second = URIRef(f"{BASE}br/doe_first_2021"), URIRef(f"{BASE}br/roe_second_2022")
    # citations survive the extra lines of the note, and DOI stubs merge into papers
    assert (second, CITO.cites, first) in graph
    # the review grid's SAT_TASK is lifted into LPWC
    assert (first, LPWCP.hasTask, URIRef(f"{BASE}coding/SAT_TASK/ner")) in graph
    assert (second, LPWCP.usesDataset, URIRef(f"{BASE}coding/SAT_DATASET/tacred")) in graph
    dataset = URIRef(BASE)
    assert (dataset, DCTERMS.conformsTo, URIRef(read_version()["version_iri"])) in graph
    assert not any("re-slr" in str(t) for triple in graph for t in triple)


def test_profile_dir_is_inside_the_package():
    assert PROFILE_DIR.parent.name == "kg"
