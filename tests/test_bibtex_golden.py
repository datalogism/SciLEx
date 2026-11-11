"""Golden-output tests pinning format_bibtex_entry (no special characters)."""

import pandas as pd

from scilex.export_to_bibtex import format_bibtex_entry

FULL_ARTICLE = {
    "itemType": "journalArticle",
    "title": "Deep Learning for Metabolomics",
    "authors": "Jane Doe;John Smith",
    "date": "2023-05-01",
    "journalAbbreviation": "J Metab",
    "conferenceName": "Ignored Conf",
    "volume": 12,
    "issue": "3",
    "pages": "10-20",
    "publisher": "Ignored Publisher",
    "serie": "Series A",
    "DOI": "10.1000/xyz",
    "url": "https://example.org/paper",
    "pdf_url": "https://example.org/paper.pdf",
    "abstract": "An abstract. " * 60,
    "language": "en",
    "rights": "CC-BY",
    "archive": "OpenAlex",
    "archiveID": "W123",
    "tags": "TASK:NER;PTM:BERT",
    "pwc_url": "https://paperswithcode.co/paper/x",
    "github_repo": "https://github.com/a/b",
}


def _entry(**overrides):
    return format_bibtex_entry(pd.Series({**FULL_ARTICLE, **overrides}), "key1")


def test_golden_full_article():
    assert _entry() == (
        "@article{key1,\n"
        "  title = {Deep Learning for Metabolomics},\n"
        "  author = {Jane Doe and John Smith},\n"
        "  year = {2023},\n"
        "  journal = {J Metab},\n"
        "  volume = {12},\n"
        "  number = {3},\n"
        "  pages = {10--20},\n"
        "  series = {Series A},\n"
        "  doi = {10.1000/xyz},\n"
        "  url = {https://example.org/paper},\n"
        "  file = {https://example.org/paper.pdf},\n"
        f"  abstract = {{{'An abstract. ' * 60}}},\n"
        "  language = {en},\n"
        "  copyright = {CC-BY},\n"
        "  archiveprefix = {OpenAlex},\n"
        "  eprint = {W123},\n"
        "  pwcurl = {https://paperswithcode.co/paper/x},\n"
        "  howpublished = {https://github.com/a/b},\n"
        "  task = {NER},\n"
        "  ptm = {BERT}\n"
        "}"
    )


def test_golden_inproceedings():
    entry = _entry(itemType="conferencePaper")
    assert entry.startswith("@inproceedings{key1,")
    lines = entry.splitlines()
    assert "  booktitle = {Ignored Conf}," in lines
    assert "  publisher = {Ignored Publisher}," in lines
    assert not any(line.startswith("  journal") for line in lines)
    assert lines.index("  booktitle = {Ignored Conf},") == 4
    assert lines.index("  publisher = {Ignored Publisher},") == 8


def test_golden_minimal_book_missing_author():
    row = pd.Series({"itemType": "book", "title": "T", "publisher": "P"})
    assert format_bibtex_entry(row, "k") == (
        "@book{k,\n  title = {T},\n  author = {Unknown},\n  publisher = {P}\n}"
    )


def test_golden_preprint_only_author():
    row = pd.Series({"itemType": "preprint", "date": "NA"})
    assert format_bibtex_entry(row, "k") == "@misc{k,\n  author = {Unknown}\n}"
