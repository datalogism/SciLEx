# SciLEx Tests

## Running Tests

Install dev dependencies first (pytest is not included in the default install):

```bash
uv sync --extra dev
```

Then run the tests:

```bash
uv run python -m pytest tests/ -v                          # All tests
uv run python -m pytest tests/ --cov=scilex --cov-report=term-missing  # With coverage
```

## Test Files

| File | Module Under Test | Focus |
|------|-------------------|-------|
| `test_constants.py` | `constants.py` | `is_valid`, `is_missing`, `safe_str` |
| `test_bibtex_export.py` | `export_to_bibtex.py` | Escaping, authors, citation keys, entry formatting |
| `test_keyword_validation.py` | `keyword_validation.py` | Single/dual keyword matching, filtering |
| `test_quality_validation.py` | `quality_validation.py` | Word/author counting, abstract validation, quality filters |
| `test_circuit_breaker.py` | `crawlers/circuit_breaker.py` | State machine (CLOSED/OPEN/HALF_OPEN), registry, timeouts |
| `test_aggregate_functions.py` | `crawlers/aggregate.py` | `clean_doi`, `getquality`, inverted index reconstruction |
| `test_aggregate_collect.py` | `aggregate_collect.py` | Citation thresholds, text filters, `FilteringTracker` |
| `test_duplicate_tracking.py` | `duplicate_tracking.py` | API overlap analysis, statistics |
| `test_pagination_bug.py` | *(standalone logic)* | Pagination limit enforcement |
| `test_semantic_scholar_url.py` | `collectors/semantic_scholar.py` | URL construction, pagination params |
| `test_dual_keyword_logic.py` | `collectors/*` | AND logic across all collectors |
| `test_openalex.py` | `collectors/openalex.py` | Cursor pagination, API key sanitization |
| `test_pubmed_*.py` | `collectors/pubmed.py`, `aggregate.py` | PubMed query building, XML parsing, aggregation |
| `test_rate_limits.py` | `config_defaults.py`, `collectors/base.py` | Rate limit structure, config overrides |
| `test_path_normalization.py` | `constants.py` | `normalize_path_component` |
| `test_hf_csv_enrichment.py` | `enrich_with_pwc.py` | Papers with Code CSV enrichment |
| `test_crossref_citations.py` | `citations/citations_tools.py`, `aggregate_collect.py` | CrossRef per-DOI lookup, pipeline tier integration |
| `test_crossref_coverage.py` | `citations/citations_tools.py` | Live CrossRef vs OpenCitations comparison (`-m live`) |

## Coverage

**376+ tests, 38% overall coverage.** Key modules: `constants` 100%, `circuit_breaker` 97%, `quality_validation` 74%, `export_to_bibtex` 71%. Coverage floor set to 35% in `pyproject.toml`.

Shared fixtures live in `conftest.py`. Test XML fixtures for PubMed are in `fixtures/pubmed/`.
