# SciLEx Documentation

SciLEx is a Python toolkit for systematic literature reviews and academic paper collection. It collects papers from multiple academic APIs, deduplicates results, and exports to Zotero or BibTeX.

```{toctree}
:maxdepth: 2
:caption: Getting Started

getting-started/installation
getting-started/quick-start
getting-started/configuration
getting-started/troubleshooting
```

```{toctree}
:maxdepth: 2
:caption: User Guides

user-guides/basic-workflow
user-guides/advanced-filtering
user-guides/python-scripting
user-guides/gui
```

```{toctree}
:maxdepth: 2
:caption: Developer Guides

developer-guides/architecture
developer-guides/adding-collectors
```

```{toctree}
:maxdepth: 2
:caption: Reference

reference/configuration
reference/api-comparison
reference/bibtex-export
```

## Supported APIs

- **Semantic Scholar** - AI/CS papers with citations
- **OpenAlex** - Open catalog, broad coverage
- **IEEE Xplore** - Engineering and computer science
- **Elsevier** - Scientific journals
- **Springer** - Academic books and journals
- **arXiv** - Preprints in physics, CS, math
- **HAL** - French open archive
- **DBLP** - Computer science bibliography
- **ISTEX** - French scientific archives
- **OpenAIRE** - European open-access research (200M+ records)
- **ORKG** - Open Research Knowledge Graph (~55K structured CS papers)
- ~~**Google Scholar**~~ - Deprecated (web scraping, unreliable, requires Tor)

## Key Features

### Multi-API Collection
Query multiple academic databases in parallel with automatic rate limiting.

### Filtering Pipeline
5-phase filtering system:
1. ItemType filtering - Focus on publication types
2. Keyword matching - Dual-group AND/OR logic
3. Quality scoring - Metadata completeness
4. Citation filtering - Time-aware thresholds
5. Relevance ranking - Multi-signal scoring

### Performance
- Parallel aggregation with multiprocessing
- SQLite citation cache
- Circuit breaker pattern for failed APIs
- Bulk Zotero uploads

## Basic Usage

```bash
# 1. Create the review configuration (scilex.yml in your working folder)
scilex init

# 2. Set up API keys (shared by all reviews)
mkdir -p ~/.config/scilex
cp keys.yml.example ~/.config/scilex/keys.yml
nano ~/.config/scilex/keys.yml

# 3. Validate, then collect
scilex config check
scilex-collect

# 4. Aggregate results
scilex-aggregate

# 5. Export to Zotero (optional)
scilex-push-zotero
```

## System Requirements

- Python 3.13+
- uv package manager (recommended) or pip
- 4GB RAM minimum
- Internet connection
