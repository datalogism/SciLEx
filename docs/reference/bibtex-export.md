# BibTeX Export Reference

Export aggregated papers to BibTeX format for LaTeX, Overleaf, JabRef, and other citation managers.

```bash
# Run after scilex-aggregate (and optionally scilex-enrich)
scilex-export-bibtex
```

**Output**: `output/{collect_name}/aggregated_results.bib`

---

## Entry Types

| CSV `itemType` | BibTeX Entry | Usage |
|----------------|--------------|-------|
| `journalArticle` | `@article` | Journal papers |
| `conferencePaper` | `@inproceedings` | Conference proceedings |
| `bookSection` | `@incollection` | Book chapters |
| `book` | `@book` | Books |
| `preprint` | `@misc` | Preprints (arXiv, bioRxiv) |
| `Manuscript` | `@unpublished` | Unpublished manuscripts |

**Citation keys** are DOI-based (e.g., `10_1021_acsomega_2c06948`) — unique and portable across citation managers.

---

## BibTeX Fields Reference

### Core Bibliographic Fields

| Field | Description | When Present |
|-------|-------------|--------------|
| `title` | Paper title | Always |
| `author` | Authors in BibTeX "and" format | Always (or "Unknown") |
| `year` | Publication year | When date available |
| `journal` | Journal name | `@article` only |
| `booktitle` | Conference name | `@inproceedings` only |
| `volume` | Volume number | When available |
| `number` | Issue number | When available |
| `pages` | Page range (e.g., `123--145`) | When available |
| `publisher` | Publisher name | Books/chapters |

### Links and Access

| Field | Description | Coverage |
|-------|-------------|---------|
| **`file`** | **Direct PDF download URL** | ~40–60% (open-access only) |
| **`url`** | Paper landing page (publisher site) | ~95% |

**Key distinction for agentic pipelines:**

```python
# ✓ CORRECT: file field is a direct PDF link
if 'file' in entry:
    pdf_bytes = requests.get(entry['file']).content

# ✗ WRONG: url is a landing page, returns HTML not PDF
if 'url' in entry:
    pdf_bytes = requests.get(entry['url']).content
```

### Identifiers and Metadata

| Field | Description | Example |
|-------|-------------|---------|
| `doi` | Digital Object Identifier | `10.1038/s41586-024-07146-0` |
| `abstract` | Full paper abstract (no truncation) | `In this paper we...` |
| `language` | Paper language | `en` |
| `copyright` | License/rights | `CC-BY-4.0` |

### Source Tracking

| Field | Description | Example |
|-------|-------------|---------|
| `archiveprefix` | Source API name | `SemanticScholar` |
| `eprint` | Original API identifier | `2307.03172` |

### Papers with Code Enrichment (after `scilex-enrich`)

| Field | Description | Example |
|-------|-------------|---------|
| `keywords` | Tags from Papers with Code (tasks, methods, benchmarks) | `TASK:NER, PTM:BERT` |
| `pwcurl` | Papers with Code paper URL (from `pwc_url`; old CSVs: `hf_url`) | `https://paperswithcode.co/paper/...` |
| `howpublished` | GitHub repository URL | `https://github.com/...` |

---

## PDF Links by API

~40–60% of papers will have `file` links (open-access papers only).

| API | PDF Availability | Source | Notes |
|-----|-----------------|--------|-------|
| **arXiv** | ✅ Always (100%) | Constructed from ID | `https://arxiv.org/pdf/{id}.pdf` |
| **SemanticScholar** | ✅ Good (~60%) | `open_access_pdf` field | Includes bioRxiv, medRxiv, SSRN |
| **OpenAlex** | ✅ Good (~50%) | `best_oa_location.pdf_url` | DOAJ, PubMed Central, repos |
| **HAL** | ✅ Good (~70%) | `files_s` list | French institutional repos |
| **IEEE** | ⚠️ Rare | `pdf_url` field | Requires subscription |
| **Springer** | ❌ Rarely | None | Paywalled |
| **Elsevier** | ❌ Rarely | None | Paywalled |
| **Others** | ❌ None | N/A | No PDF fields in API response |

**Implementation** (in `scilex/crawlers/aggregate.py`):
- SemanticScholar: line 414 — `row["open_access_pdf"]`
- arXiv: line 594 — constructed as `https://arxiv.org/pdf/{arxiv_id}.pdf`
- OpenAlex: line 901 — `oa_location["pdf_url"]` from `best_oa_location`
- HAL: lines 780–786 — first `.pdf` file in `files_s` list
- IEEE: line 1075 — `row["pdf_url"]` (when available)

---

## Example Entry

```bibtex
@article{10_48550_arxiv_2307_03172,
  title = {Llama 2: Open Foundation and Fine-Tuned Chat Models},
  author = {Hugo Touvron and Louis Martin and Kevin Stone},
  year = {2023},
  journal = {arXiv},
  doi = {10.48550/arXiv.2307.03172},
  url = {https://arxiv.org/abs/2307.03172},
  file = {https://arxiv.org/pdf/2307.03172.pdf},
  abstract = {In this work, we develop and release Llama 2...},
  language = {en},
  archiveprefix = {arXiv},
  eprint = {2307.03172},
  keywords = {TASK:TextGeneration, PTM:Llama2, FRAMEWORK:PyTorch},
  pwcurl = {https://paperswithcode.co/paper/2307.03172},
  howpublished = {https://github.com/facebookresearch/llama}
}
```

---

## See Also

- [Basic Workflow](../user-guides/basic-workflow.md) — Pipeline overview including export step
- [Papers with Code Enrichment](configuration.md) — `enrichment.paperswithcode` (`huggingface` is a deprecated alias) in `scilex.yml`, then `scilex-enrich` before export
- [Python Scripting](../user-guides/python-scripting.md) — Programmatic BibTeX parsing
