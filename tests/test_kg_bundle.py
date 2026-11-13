"""Survey bundle of a review (scilex.kg.bundle): SX-1, SX-2, SX-3, SX-6, SX-14."""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from scilex.kg import bib2json
from scilex.kg.bundle import (
    PARTS,
    build_bundle,
    derived_key,
    find_secrets,
    join_papers,
    secret_values,
    write_bundle,
)

HAS_KG_DEPS = all(importlib.util.find_spec(m) for m in ("morph_kgc", "pyoxigraph"))
OWNER = "https://orcid.org/0000-0002-1825-0097"
CONSENTING = "0000-0001-5109-3700"
SHY = "0000-0003-1415-9269"
SECRET = "sk_live_9f8e7d6c5b4a39281706"
BASE = "https://w3id.org/scilex/data/fixture/"

BIB = r"""
@article{doe_first_2021,
	title = {A Study of Relation Extraction},
	doi = {10.1000/first},
	journaltitle = {Journal of Tests},
	author = {Doe, Jane},
	date = {2021-05-01},
	keywords = {{TASK}:{RE}, ANNOT:0000-0001-5109-3700, ANNOT_VALID_BY:0000-0003-1415-9269, {PAPER\_TYPE}:Dataset, KEEP:C1},
}

@article{roe_second_2022,
	title = {Second Paper},
	doi = {10.1000/second},
	author = {Roe, Richard},
	date = {2022},
	keywords = {{TASK}:{NER}, DELETED_BY:filter:C1 published in 2010},
}
"""

CORPUS = [
    {
        "itemType": "journalArticle",
        "title": "A Study of Relation Extraction",
        "DOI": "10.1000/first",
        "date": "2021-05-01",
        "zotero_key": "ZK1",
        "journalAbbreviation": "Journal of Tests",
        "serie": "0015-6191",
        "relevance_score": 0.8,
        "quality_score": 3,
        "metric_pagerank": 0.12,
        "metric_computed_at": "2026-11-01",
        "lpwc_task": "relation extraction",
        "paper_type_origin": f"person:https://orcid.org/{SHY}",
        "url": f"https://api.example.org/x?api_key={SECRET}",
        "tags": "",
    },
    {
        "itemType": "journalArticle",
        "title": "Second Paper",
        "DOI": "10.1000/second",
        "date": "2022",
        "zotero_key": "ZK2",
        "tags": "",
    },
    {  # discarded by a person, left out of the BibLaTeX export
        "itemType": "conferencePaper",
        "title": "Off-topic paper",
        "DOI": "10.1000/third",
        "date": "2023",
        "zotero_key": "ZK3",
        "conferenceName": "ACL 2023",
        "tags": f"DELETED_BY:{SHY}",
    },
]


@pytest.fixture
def review_full(tmp_path: Path):
    """A review folder with every file of docs/reference/review-files.md."""
    from scilex.gui.services import journal

    folder = tmp_path / "review"
    out = folder / "output" / "fixture"
    out.mkdir(parents=True)
    (folder / "scilex.yml").write_text(
        "name: fixture\nsearch:\n  keywords: [relation extraction]\n"
        "  years: 2021-2023\n  apis: [OpenAlex]\n",
        encoding="utf-8",
    )
    (folder / "criteria.yml").write_text(
        yaml.safe_dump([{"id": "C1", "kind": "period", "enabled": True}]),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "tag": "TASK",
                "detail": "Which task?",
                "datasets": "X",
                "surveys": "",
                "models": "X",
            }
        ]
    ).to_csv(folder / "annotation_grid.csv", index=False)
    (folder / "collection_roles.yml").write_text(
        yaml.safe_dump(
            {
                "collections": [
                    {"path": "fixture / screened", "role": "screened", "key": "C9"}
                ]
            }
        ),
        encoding="utf-8",
    )
    (folder / "members.yml").write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Consenting Person",
                    "orcid": CONSENTING,
                    "consent_public": True,
                },
                {"name": "Shy Person", "orcid": SHY},
            ]
        ),
        encoding="utf-8",
    )
    (folder / "annotation_history.jsonl").write_text(
        json.dumps(
            {
                "at": "2026-11-01T10:00:00",
                "origin": "sync",
                "papers": 2,
                "codes_added": [["ZK1", "TASK:RE"]],
                "codes_removed": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (folder / "paper_log.json").write_text(
        json.dumps(
            {"doi:10.1000/first": {"imported_at": "2026-10-01", "origin": "Collect"}}
        ),
        encoding="utf-8",
    )
    (folder / "snowball.yml").write_text("direction: backward\n", encoding="utf-8")
    (folder / "zotero_source.yml").write_text(
        "library_type: group\nlibrary_id: '42'\ncollection_key: ABC\ncollection_name: fixture\n",
        encoding="utf-8",
    )
    (folder / "kg_source.yml").write_text(
        "iri: https://w3id.org/scilex/data/origin/\nversion: '1'\n", encoding="utf-8"
    )
    journal.append(folder, "configure", params={"token": SECRET, "note": "ok"})
    pd.DataFrame(CORPUS).to_csv(out / "aggregated_results.csv", sep=";", index=False)
    (out / "screening.csv").write_text(
        "paper_key,decision,note,updated_at,decided_by\n"
        f"doi:10.1000/first,include,core paper,2026-11-02,https://orcid.org/{SHY}\n"
        "doi:10.1000/second,exclude,,2026-11-02,\n",
        encoding="utf-8",
    )
    (out / "aggregation_stats.csv").write_text(
        "stat,value\nraw_records,120\nafter_dedup,90\nrun_date,2026-10-01 10:00\n",
        encoding="utf-8",
    )
    study = out / "annotations" / "agreement"
    study.mkdir(parents=True)
    (study / "2026-11-03T10-00-00.json").write_text(
        json.dumps(
            {
                "at": "2026-11-03T10:00:00",
                "sample": ["ZK1"],
                "annotators": [CONSENTING, SHY],
                "measures": [
                    {"dimension": "TASK", "alpha": 1.0, "papers": 1, "values": 2}
                ],
                "codes": [
                    {
                        "paper": "ZK1",
                        "annotator": CONSENTING,
                        "dimension": "TASK",
                        "value": "RE",
                    },
                    {
                        "paper": "ZK1",
                        "annotator": SHY,
                        "dimension": "TASK",
                        "value": "RE",
                    },
                ],
                "merge": {"rule": "majority", "to_adjudicate": []},
            }
        ),
        encoding="utf-8",
    )
    bib = tmp_path / "fixture.bib"
    bib.write_text(BIB, encoding="utf-8")
    return folder, out, bib2json.convert(bib), bib


def _bundle(review_full, disclosure="public"):
    folder, out, tables, _ = review_full
    return build_bundle(
        folder,
        out,
        review_name="fixture",
        bib=tables,
        base_iri=BASE,
        owner=OWNER,
        disclosure=disclosure,
        secrets=secret_values({"zotero": {"api_key": SECRET}}),
    )


def test_every_part_is_present_at_full_level(review_full):
    bundle, report = _bundle(review_full, "full")
    assert {p["name"] for p in bundle["parts"]} == set(PARTS)
    absent = [p["name"] for p in bundle["parts"] if p["status"] != "present"]
    assert absent == [], absent
    assert report.papers == 3 and report.unmatched == 1
    json.dumps(bundle)  # JSON-ready


def test_one_join_key_per_paper(review_full):
    """SX-2: screening and paper-log rows land on exactly one paper of the graph."""
    bundle, _ = _bundle(review_full, "team")
    papers = {p["paper"]: p for p in bundle["papers"]}
    assert papers["doe_first_2021"]["zotero_key"] == "ZK1"
    assert papers["doe_first_2021"]["paper_key"] == "doi:10.1000/first"
    third = derived_key("doi:10.1000/third")
    assert papers[third]["in_bibliography"] is False
    decisions = {r["paper"]: r for r in bundle["screening"]}
    assert set(decisions) == {"doe_first_2021", "roe_second_2022"}
    assert decisions["doe_first_2021"]["note"] == "core paper"  # team level
    assert [r["paper"] for r in bundle["paper_log"]] == ["doe_first_2021"]
    # snapshot codes (by Zotero key) land on the citation key
    assert bundle["annotation_codes"] == [
        {"snapshot": 1, "paper": "doe_first_2021", "code": "TASK:RE", "change": "added"}
    ]
    # agreement copies are not papers: their codes sit on the original paper
    assert {c["paper"] for c in bundle["agreement_codes"]} == {"doe_first_2021"}


def test_discards_are_flagged_not_dropped(review_full):
    """SX-3: a rule's and a person's discard, each with who and why."""
    bundle, _ = _bundle(review_full, "team")
    excluded = {r["paper"]: r for r in bundle["excluded"]}
    assert excluded["roe_second_2022"]["by"] == "filter:C1"
    assert excluded["roe_second_2022"]["cause"] == "published in 2010"
    assert (
        excluded[derived_key("doi:10.1000/third")]["by"] == f"https://orcid.org/{SHY}"
    )
    assert bundle["keep"] == [{"paper": "doe_first_2021", "criterion": "C1"}]
    roles = {(r["agent"], r["role"]) for r in bundle["assignments"]}
    assert (f"https://orcid.org/{CONSENTING}", "assigned") in roles
    (kind,) = bundle["paper_types"]
    assert kind == {
        "paper": "doe_first_2021",
        "type": "Dataset",
        "origin": f"person:https://orcid.org/{SHY}",
    }


def test_public_level_names_only_consenting_members(review_full):
    """SX-6: no note, no name, no ORCID iD of a member without consent."""
    bundle, report = _bundle(review_full, "public")
    text = json.dumps(bundle)
    assert SHY not in text and "Shy Person" not in text and "core paper" not in text
    assert f"https://orcid.org/{CONSENTING}" in text
    assert "agent/" in text  # the pseudonym of the member without consent
    status = {p["name"]: p["status"] for p in bundle["parts"]}
    assert status["agreement_codes"] == "withheld" and "agreement_codes" not in bundle
    assert all(e["params"] is None for e in bundle["journal"])
    assert report.parts["agreement_codes"] == "withheld"


def test_no_secret_at_any_level(review_full):
    """SX-14: a key in a URL and in a journal parameter never reaches the bundle."""
    for level in ("public", "team", "full"):
        bundle, _ = _bundle(review_full, level)
        assert SECRET not in json.dumps(bundle), level


def test_venues_keep_the_name_and_the_issn(review_full):
    bundle, _ = _bundle(review_full)
    venues = {v["paper"]: v for v in bundle["venues"]}
    assert venues["doe_first_2021"] == {
        "paper": "doe_first_2021",
        "journal": "Journal of Tests",
        "issn": "0015-6191",
    }
    assert venues[derived_key("doi:10.1000/third")]["conference"] == "ACL 2023"


def test_find_secrets_tells_keys_from_hashes():
    from rdflib import Graph, Literal, URIRef

    graph = Graph()
    s = URIRef("https://example.org/s")
    p = URIRef("https://example.org/p")
    graph.add((s, p, Literal("a" * 64)))  # a SHA-256: a configuration version
    graph.add((s, p, Literal("Graph neural networks for relation extraction")))
    assert find_secrets(graph) == []
    graph.add((s, p, Literal("https://api.example.org/q?api_key=abcdef123456")))
    graph.add((s, p, Literal("token Zx9Qa7Lm3Np5Rt8Vw2Yb6Cd4Ef1Gh0Jk")))
    assert len(find_secrets(graph)) == 2
    assert find_secrets(graph, ["Graph neural"])  # a value of the keys file


def test_join_without_bibliography_derives_keys():
    papers = join_papers(
        {"entries": [], "lists": []}, [{"DOI": "10.1/x", "title": "X"}]
    )
    assert papers[0].key == derived_key("doi:10.1/x")


@pytest.mark.skipif(not HAS_KG_DEPS, reason="needs the 'kg' extra")
def test_build_with_the_bundle_names_issn_only_journals(review_full, tmp_path):
    """Profile iteration 7+: the bundle's venues name a journal known by its ISSN."""
    from rdflib import Graph, Namespace, URIRef
    from rdflib.namespace import DCTERMS

    from scilex.kg.build import build_knowledge_graph

    folder, out, tables, bib = review_full
    # the second paper's journal is known only by an ISSN, as SciLEx pushed it
    bib.write_text(
        BIB.replace(
            "author = {Roe, Richard},",
            "author = {Roe, Richard},\n\tissn = {0015-6191},",
        ),
        encoding="utf-8",
    )
    corpus = pd.read_csv(out / "aggregated_results.csv", sep=";")
    corpus.loc[1, "journalAbbreviation"] = "Fontes Artis Musicae"
    corpus.loc[1, "serie"] = "0015-6191"
    corpus.to_csv(out / "aggregated_results.csv", sep=";", index=False)
    report = write_bundle(
        tmp_path / "kg" / "bundle" / "survey.json",
        folder,
        out,
        review_name="fixture",
        bib=bib2json.convert(bib),
        base_iri=BASE,
        owner=OWNER,
    )
    result = build_knowledge_graph(
        bib,
        tmp_path / "kg" / "fixture.ttl",
        review_name="fixture",
        base_iri=BASE,
        dimensions=["TASK"],
        run_validation=False,
        creator=OWNER,
        survey=report.path,
        secrets=[SECRET],
    )
    graph = Graph().parse(result.output)
    frbr = Namespace("http://purl.org/vocab/frbr/core#")
    journal = graph.value(URIRef(f"{BASE}br/roe_second_2022"), frbr.partOf)
    assert journal is not None
    assert str(graph.value(journal, DCTERMS.title)) == "Fontes Artis Musicae"
    # workflow tags are bundle parts, not keywords; nothing looks like a key
    assert not any("DELETED_BY" in str(o) for o in graph.objects())
    assert result.suspect_literals == []
