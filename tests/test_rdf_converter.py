"""Tests for the scilex.rdf module.

All BibTeX fixtures are defined inline; no real file I/O beyond tmp_path.
"""

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, FOAF, RDF, XSD

from scilex.rdf.converter import (
    _add_page_range,
    _parse_author_name,
    _slug,
    _typed_literal,
    convert,
    convert_to_string,
)
from scilex.rdf.namespaces import BIBO, SCHEMA, SCILEX

# ---------------------------------------------------------------------------
# BibTeX fixtures
# ---------------------------------------------------------------------------

_SAMPLE_BIB = """\
@article{smith2024test,
  title = {A Test Article on Knowledge Graphs},
  author = {Smith, John and Doe, Jane},
  year = {2024},
  journal = {J. Knowledge Eng.},
  doi = {10.1234/test.2024},
  abstract = {We present a test.},
  url = {https://doi.org/10.1234/test.2024},
  file = {https://example.com/paper.pdf},
  volume = {42},
  number = {3},
  pages = {123-145},
  keywords = {knowledge graph, RDF},
  language = {en},
  archiveprefix = {SemanticScholar},
  eprint = {abc123},
  series = {LNCS},
  howpublished = {https://github.com/smith/kgtest},
  citationcount = {15},
  relevancescore = {7.34},
}
"""

_SAMPLE_BIB_WITH_REFS = """\
@article{jones2023cited,
  title = {A Citing Paper},
  author = {Jones, Alice},
  year = {2023},
  doi = {10.9999/citing.2023},
  references = {10.1234/test.2024, 10.5678/other.2022},
  cited_by = {10.1111/citer.2025},
}
"""

_SAMPLE_BIB_WITH_MONTH = """\
@article{smith2024month,
  title = {Paper with Month},
  author = {Smith, John},
  year = {2024},
  month = {march},
  doi = {10.1234/month.2024},
}
"""

_SAMPLE_BIB_NO_DOI = """\
@misc{nodoi2024,
  title = {No DOI Paper},
  year = {2024},
}
"""

_SAMPLE_BIB_INPROCEEDINGS = """\
@inproceedings{conf2023,
  title = {A Conference Paper},
  author = {Brown, Alice},
  year = {2023},
  booktitle = {Proceedings of ISWC 2023},
  doi = {10.1234/conf.2023},
}
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bib_file(tmp_path):
    """Full-featured BibTeX article."""
    f = tmp_path / "sample.bib"
    f.write_text(_SAMPLE_BIB, encoding="utf-8")
    return str(f)


@pytest.fixture
def bib_file_with_refs(tmp_path):
    """Article with references / cited_by fields."""
    f = tmp_path / "refs.bib"
    f.write_text(_SAMPLE_BIB_WITH_REFS, encoding="utf-8")
    return str(f)


@pytest.fixture
def bib_file_with_month(tmp_path):
    """Article with month field."""
    f = tmp_path / "month.bib"
    f.write_text(_SAMPLE_BIB_WITH_MONTH, encoding="utf-8")
    return str(f)


@pytest.fixture
def bib_file_no_doi(tmp_path):
    """Misc entry without a DOI."""
    f = tmp_path / "nodoi.bib"
    f.write_text(_SAMPLE_BIB_NO_DOI, encoding="utf-8")
    return str(f)


@pytest.fixture
def bib_file_inproceedings(tmp_path):
    """Conference paper entry."""
    f = tmp_path / "conf.bib"
    f.write_text(_SAMPLE_BIB_INPROCEEDINGS, encoding="utf-8")
    return str(f)


# ---------------------------------------------------------------------------
# TestConvert — core graph building
# ---------------------------------------------------------------------------


class TestConvert:
    """Tests for :func:`scilex.rdf.converter.convert`."""

    def test_returns_graph(self, bib_file):
        g = convert(bib_file)
        assert isinstance(g, Graph)
        assert len(g) > 0

    def test_doi_uri_is_doi_org(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        assert (paper, RDF.type, BIBO.AcademicArticle) in g

    def test_title_triple(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        titles = list(g.objects(paper, DCTERMS.title))
        assert len(titles) == 1
        assert str(titles[0]) == "A Test Article on Knowledge Graphs"

    def test_two_authors_created(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        creators = list(g.objects(paper, DCTERMS.creator))
        assert len(creators) == 2

    def test_authors_are_foaf_persons(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        for person_uri in g.objects(paper, DCTERMS.creator):
            assert (person_uri, RDF.type, FOAF.Person) in g

    def test_keyword_list_split(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        subjects = {str(s) for s in g.objects(paper, DCTERMS.subject)}
        assert "knowledge graph" in subjects
        assert "RDF" in subjects
        assert len(subjects) == 2

    # --- Typed literals ---

    def test_citation_count_integer_literal(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        counts = list(g.objects(paper, SCHEMA.citationCount))
        assert len(counts) == 1
        assert counts[0].datatype == XSD.integer
        assert int(str(counts[0])) == 15

    def test_relevance_score_decimal_literal(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        scores = list(g.objects(paper, SCILEX.relevanceScore))
        assert len(scores) == 1
        assert scores[0].datatype == XSD.decimal
        assert abs(float(str(scores[0])) - 7.34) < 0.001

    def test_year_without_month_is_gyear(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        dates = list(g.objects(paper, DCTERMS.date))
        assert len(dates) == 1
        assert dates[0].datatype == XSD.gYear
        assert str(dates[0]) == "2024"

    def test_year_with_month_is_gyearmonth(self, bib_file_with_month):
        g = convert(bib_file_with_month)
        paper = URIRef("https://doi.org/10.1234/month.2024")
        dates = list(g.objects(paper, DCTERMS.date))
        assert len(dates) == 1
        assert dates[0].datatype == XSD.gYearMonth
        assert str(dates[0]) == "2024-03"

    # --- Page range ---

    def test_page_range_raw_literal(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        pages = list(g.objects(paper, BIBO.pages))
        assert len(pages) == 1
        assert str(pages[0]) == "123-145"

    def test_page_start_integer(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        starts = list(g.objects(paper, BIBO.pageStart))
        assert len(starts) == 1
        assert starts[0].datatype == XSD.integer
        assert int(str(starts[0])) == 123

    def test_page_end_integer(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        ends = list(g.objects(paper, BIBO.pageEnd))
        assert len(ends) == 1
        assert ends[0].datatype == XSD.integer
        assert int(str(ends[0])) == 145

    # --- New fields ---

    def test_file_field_maps_to_content_url(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        urls = list(g.objects(paper, SCHEMA.contentUrl))
        assert len(urls) == 1
        assert str(urls[0]) == "https://example.com/paper.pdf"

    def test_archiveprefix_maps_to_collected_from(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        sources = list(g.objects(paper, SCILEX.collectedFrom))
        assert len(sources) == 1
        assert str(sources[0]) == "SemanticScholar"

    def test_eprint_maps_to_identifier(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        ids = list(g.objects(paper, DCTERMS.identifier))
        assert len(ids) == 1
        assert str(ids[0]) == "abc123"

    def test_series_maps_to_is_part_of_literal(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        literals = [
            o for o in g.objects(paper, DCTERMS.isPartOf) if isinstance(o, Literal)
        ]
        assert any(str(s) == "LNCS" for s in literals)

    def test_howpublished_github_uri(self, bib_file):
        g = convert(bib_file)
        paper = URIRef("https://doi.org/10.1234/test.2024")
        repos = list(g.objects(paper, SCHEMA.codeRepository))
        assert len(repos) == 1
        assert str(repos[0]) == "https://github.com/smith/kgtest"

    # --- Citation links ---

    def test_bibo_cites_triples(self, bib_file_with_refs):
        g = convert(bib_file_with_refs)
        paper = URIRef("https://doi.org/10.9999/citing.2023")
        cited = {str(c) for c in g.objects(paper, BIBO.cites)}
        assert "https://doi.org/10.1234/test.2024" in cited
        assert "https://doi.org/10.5678/other.2022" in cited
        assert len(cited) == 2

    def test_bibo_cited_by_triple(self, bib_file_with_refs):
        g = convert(bib_file_with_refs)
        paper = URIRef("https://doi.org/10.9999/citing.2023")
        citers = list(g.objects(paper, BIBO.citedBy))
        assert len(citers) == 1
        assert str(citers[0]) == "https://doi.org/10.1111/citer.2025"

    # --- Fallback URI and entry types ---

    def test_no_doi_falls_back_to_base_uri(self, bib_file_no_doi):
        g = convert(bib_file_no_doi, base_uri="http://test.org/pub/")
        expected = URIRef("http://test.org/pub/nodoi2024")
        assert (expected, RDF.type, BIBO.Document) in g

    def test_base_uri_slash_appended_automatically(self, bib_file_no_doi):
        # base_uri without trailing slash must still produce correct URIs
        g = convert(bib_file_no_doi, base_uri="http://test.org/pub")
        expected = URIRef("http://test.org/pub/nodoi2024")
        assert (expected, RDF.type, BIBO.Document) in g

    def test_inproceedings_maps_to_academic_article(self, bib_file_inproceedings):
        g = convert(bib_file_inproceedings)
        paper = URIRef("https://doi.org/10.1234/conf.2023")
        assert (paper, RDF.type, BIBO.AcademicArticle) in g

    def test_inproceedings_links_to_proceedings_node(self, bib_file_inproceedings):
        g = convert(bib_file_inproceedings)
        paper = URIRef("https://doi.org/10.1234/conf.2023")
        parts = list(g.objects(paper, DCTERMS.isPartOf))
        assert len(parts) == 1
        proc_uri = parts[0]
        assert (proc_uri, RDF.type, BIBO.Proceedings) in g


# ---------------------------------------------------------------------------
# TestConvertToString
# ---------------------------------------------------------------------------


class TestConvertToString:
    """Tests for :func:`scilex.rdf.converter.convert_to_string`."""

    def test_returns_string(self, bib_file):
        result = convert_to_string(bib_file, fmt="turtle")
        assert isinstance(result, str)
        assert "@prefix bibo:" in result

    def test_scilex_prefix_in_turtle(self, bib_file):
        result = convert_to_string(bib_file, fmt="turtle")
        assert "scilex" in result

    def test_n3_format(self, bib_file):
        result = convert_to_string(bib_file, fmt="n3")
        assert isinstance(result, str)

    def test_xml_format(self, bib_file):
        result = convert_to_string(bib_file, fmt="xml")
        assert "rdf:RDF" in result


# ---------------------------------------------------------------------------
# TestProvenance
# ---------------------------------------------------------------------------


class TestProvenance:
    """Tests for :func:`scilex.rdf.provenance.add_collection_provenance`."""

    def test_activity_node_added(self, bib_file):
        from rdflib.namespace import PROV

        g = convert(bib_file, collect_name="my_review")
        activity = URIRef("http://example.org/pub/collection/my_review")
        assert (activity, RDF.type, PROV.Activity) in g

    def test_scilex_collection_type(self, bib_file):
        g = convert(bib_file, collect_name="my_review")
        activity = URIRef("http://example.org/pub/collection/my_review")
        assert (activity, RDF.type, SCILEX.Collection) in g

    def test_no_collect_name_no_activity(self, bib_file):
        from rdflib.namespace import PROV

        g = convert(bib_file)
        activities = list(g.subjects(RDF.type, PROV.Activity))
        assert len(activities) == 0


# ---------------------------------------------------------------------------
# TestAddPageRange
# ---------------------------------------------------------------------------


class TestAddPageRange:
    """Tests for the :func:`_add_page_range` helper."""

    def _graph_with_pages(self, pages_str: str) -> Graph:
        g = Graph()
        subject = URIRef("http://example.org/paper")
        _add_page_range(g, subject, pages_str)
        return g, subject

    def test_hyphen_separator(self):
        g, s = self._graph_with_pages("123-145")
        assert int(str(list(g.objects(s, BIBO.pageStart))[0])) == 123
        assert int(str(list(g.objects(s, BIBO.pageEnd))[0])) == 145

    def test_double_hyphen_separator(self):
        g, s = self._graph_with_pages("10--20")
        assert int(str(list(g.objects(s, BIBO.pageStart))[0])) == 10
        assert int(str(list(g.objects(s, BIBO.pageEnd))[0])) == 20

    def test_single_page(self):
        g, s = self._graph_with_pages("42")
        starts = list(g.objects(s, BIBO.pageStart))
        ends = list(g.objects(s, BIBO.pageEnd))
        assert len(starts) == 1
        assert int(str(starts[0])) == 42
        assert len(ends) == 0

    def test_non_numeric_no_triples(self):
        g, s = self._graph_with_pages("e123-e145")
        assert len(list(g.objects(s, BIBO.pageStart))) == 0

    def test_page_start_is_integer_typed(self):
        g, s = self._graph_with_pages("5-10")
        start = list(g.objects(s, BIBO.pageStart))[0]
        assert start.datatype == XSD.integer


# ---------------------------------------------------------------------------
# TestTypedLiteral
# ---------------------------------------------------------------------------


class TestTypedLiteral:
    """Tests for the :func:`_typed_literal` helper."""

    def test_integer_type(self):
        lit = _typed_literal("42", "xsd:integer")
        assert lit.datatype == XSD.integer
        assert int(str(lit)) == 42

    def test_decimal_type(self):
        lit = _typed_literal("3.14", "xsd:decimal")
        assert lit.datatype == XSD.decimal
        assert abs(float(str(lit)) - 3.14) < 0.001

    def test_invalid_integer_falls_back_to_string(self):
        lit = _typed_literal("not-a-number", "xsd:integer")
        assert lit.datatype is None

    def test_invalid_decimal_falls_back_to_string(self):
        lit = _typed_literal("not-a-decimal", "xsd:decimal")
        assert lit.datatype is None

    def test_none_type_returns_plain_literal(self):
        lit = _typed_literal("hello", None)
        assert str(lit) == "hello"
        assert lit.datatype is None


# ---------------------------------------------------------------------------
# TestSlug
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BibTeX fixture with HuggingFace enrichment fields
# ---------------------------------------------------------------------------

_SAMPLE_BIB_WITH_HF = """\
@article{hf2024test,
  title = {An HF-Enriched Paper},
  author = {Lee, Alice},
  year = {2024},
  doi = {10.1234/hf.2024},
  task = {TextClassification},
  ptm = {BERT},
  archi = {Transformer},
  hfdataset = {Squad, Glue},
  framework = {PyTorch},
  githubstars = {366},
  citingdatasets = {SQuAD-v2, MNLI},
  hfurl = {https://huggingface.co/papers/2401.12345},
  keywords = {multi-document QA},
}
"""


@pytest.fixture
def bib_file_with_hf(tmp_path):
    """Article with HuggingFace enrichment fields."""
    f = tmp_path / "hf.bib"
    f.write_text(_SAMPLE_BIB_WITH_HF, encoding="utf-8")
    return str(f)


# ---------------------------------------------------------------------------
# TestHuggingFaceFields
# ---------------------------------------------------------------------------


class TestHuggingFaceFields:
    """Tests for HuggingFace enrichment fields in RDF output."""

    _PAPER = URIRef("https://doi.org/10.1234/hf.2024")

    def test_task_triple(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        tasks = list(g.objects(self._PAPER, SCILEX.task))
        assert len(tasks) == 1
        assert str(tasks[0]) == "TextClassification"

    def test_ptm_triple(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        ptms = list(g.objects(self._PAPER, SCILEX.pretrainedModel))
        assert len(ptms) == 1
        assert str(ptms[0]) == "BERT"

    def test_architecture_triple(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        archis = list(g.objects(self._PAPER, SCILEX.architecture))
        assert len(archis) == 1
        assert str(archis[0]) == "Transformer"

    def test_dataset_split_into_multiple_triples(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        datasets = {str(d) for d in g.objects(self._PAPER, SCILEX.usesDataset)}
        assert "Squad" in datasets
        assert "Glue" in datasets
        assert len(datasets) == 2

    def test_framework_triple(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        fws = list(g.objects(self._PAPER, SCILEX.framework))
        assert len(fws) == 1
        assert str(fws[0]) == "PyTorch"

    def test_github_stars_integer(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        stars = list(g.objects(self._PAPER, SCILEX.githubStars))
        assert len(stars) == 1
        assert stars[0].datatype == XSD.integer
        assert int(str(stars[0])) == 366

    def test_citing_datasets_split(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        cds = {str(d) for d in g.objects(self._PAPER, SCILEX.citedByDataset)}
        assert "SQuAD-v2" in cds
        assert "MNLI" in cds
        assert len(cds) == 2

    def test_pwc_url_is_uri(self, tmp_path):
        bib = tmp_path / "pwc.bib"
        bib.write_text(
            _SAMPLE_BIB_WITH_HF.replace(
                "hfurl = {https://huggingface.co/papers/2401.12345}",
                "pwcurl = {https://paperswithcode.co/paper/2401.12345}",
            ),
            encoding="utf-8",
        )
        g = convert(str(bib))
        urls = list(g.objects(self._PAPER, SCILEX.papersWithCodeUrl))
        assert len(urls) == 1
        assert isinstance(urls[0], URIRef)
        assert str(urls[0]) == "https://paperswithcode.co/paper/2401.12345"

    def test_hf_url_is_uri(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        urls = list(g.objects(self._PAPER, SCILEX.huggingFaceUrl))
        assert len(urls) == 1
        assert isinstance(urls[0], URIRef)
        assert str(urls[0]) == "https://huggingface.co/papers/2401.12345"

    def test_unprefixed_keywords_still_dcterms_subject(self, bib_file_with_hf):
        g = convert(bib_file_with_hf)
        subjects = {str(s) for s in g.objects(self._PAPER, DCTERMS.subject)}
        assert "multi-document QA" in subjects


# ---------------------------------------------------------------------------
# TestSlug
# ---------------------------------------------------------------------------


class TestSlug:
    """Tests for the :func:`_slug` helper."""

    def test_ascii_text(self):
        assert _slug("hello world") == "hello-world"

    def test_accented_chars_normalized(self):
        assert _slug("Héllo") == "hello"

    def test_special_chars_removed(self):
        assert _slug("hello!@#world") == "helloworld"

    def test_multiple_spaces_collapsed(self):
        assert _slug("  hello   world  ") == "hello-world"

    def test_empty_string(self):
        assert _slug("") == ""


# ---------------------------------------------------------------------------
# TestParseAuthorName
# ---------------------------------------------------------------------------


class TestParseAuthorName:
    """Tests for the :func:`_parse_author_name` helper."""

    def test_last_first_format(self):
        result = _parse_author_name("Smith, John")
        assert result["last"] == "Smith"
        assert result["first"] == "John"

    def test_first_last_format(self):
        result = _parse_author_name("John Smith")
        assert result["first"] == "John"
        assert result["last"] == "Smith"

    def test_single_name(self):
        result = _parse_author_name("Cher")
        assert result["last"] == "Cher"
        assert result["first"] == ""

    def test_strips_whitespace(self):
        result = _parse_author_name("  Smith , John  ")
        assert result["last"] == "Smith"
        assert result["first"] == "John"
