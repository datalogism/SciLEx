# API Comparison Matrix

Reference guide comparing all supported academic APIs.

## Quick Comparison

| API | Coverage | API Key | Rate Limit | Abstracts | Citations | DOI | Best For |
|-----|----------|---------|------------|-----------|-----------|-----|----------|
| **Semantic Scholar** | 200M+ papers | Optional | 1 req/s | 95% | Yes | 85% | AI/CS research |
| **OpenAlex** | 250M+ works | No | 10 req/s | 60% | Yes | 90% | Broad coverage |
| **IEEE Xplore** | 5M+ docs | Required | 200/day | 100% | Limited | 95% | Engineering |
| **Elsevier** | 18M+ articles | Required | Varies | 80% | No | 100% | Life sciences |
| **Springer** | 13M+ docs | Required | 5000/day | 90% | No | 98% | Multidisciplinary |
| **arXiv** | 2M+ preprints | No | 3 req/s | 100% | No | 60% | Physics/Math/CS |
| **HAL** | 1M+ docs | No | 10 req/s | 70% | No | 40% | French research |
| **DBLP** | 6M+ CS papers | No | 10 req/s | 0% | No | 95% | CS bibliography |
| **ISTEX** | 25M+ docs | No | 10 req/s | 95% | No | 98% | French archives |
| **OpenAIRE** | 200M+ records | No | 5 req/s | 70% | No | 75% | EU open-access |
| **ORKG** | ~55K papers | No | 2 req/s | 0% | No | 80% | Structured CS research |
| ~~**Google Scholar**~~ | Unknown | No | — | Varies | Yes | 20% | ~~Comprehensive~~ **Deprecated** |

## API Details

### Semantic Scholar

- **Strengths**: Excellent citations, AI/ML coverage, free API
- **Weaknesses**: CS-biased, limited pre-1990 papers
- **Use for**: AI/ML/CS research, citation networks
- **Config key**: `sem_scholar`

### OpenAlex

- **Strengths**: Massive coverage, no key required, institutional data
- **Weaknesses**: 60% abstract coverage, may lag on recent citations
- **Use for**: Broad multidisciplinary searches
- **Config key**: not required

### IEEE Xplore

- **Strengths**: Complete abstracts, engineering focus, standards
- **Weaknesses**: Daily quota limit (200), API key required
- **Use for**: Engineering and technology papers
- **Config key**: `ieee`

### Elsevier

- **Strengths**: High-quality journals, life sciences, medical
- **Weaknesses**: API key required, no citations, complex auth
- **Use for**: Biomedical research
- **Config key**: `elsevier`

### Springer

- **Strengths**: Books and chapters, European content
- **Weaknesses**: API key required, no citations
- **Use for**: Book chapters, multidisciplinary
- **Config key**: `springer`

### arXiv

- **Strengths**: 100% abstracts, free, latest preprints
- **Weaknesses**: Not peer-reviewed, no citations
- **Use for**: Cutting-edge physics/math/CS
- **Config key**: not required

### HAL

- **Strengths**: French research, open access
- **Weaknesses**: Low DOI coverage (40%), French-focused
- **Use for**: French and European research
- **Config key**: not required

### DBLP

- **Strengths**: Complete CS bibliography, high DOI rate (95%)
- **Weaknesses**: No abstracts (copyright policy), CS-only
- **Use for**: CS conference papers, bibliographic data
- **Config key**: not required

### ISTEX

- **Strengths**: Historical archives, 95% abstracts
- **Weaknesses**: French interface, may require institutional access
- **Use for**: Historical papers, French archives
- **Config key**: not required

### OpenAIRE

OpenAIRE is the European open-access research gateway, aggregating publications from Horizon 2020 and other EU-funded projects.

- **Strengths**: 200M+ records, open-access focus, EU-funded research, no key required
- **Weaknesses**: No citations; some records have limited metadata; max 10K results per query
- **Use for**: EU-funded research, open-access papers, broad European coverage
- **Config key**: not required
- **API endpoint**: `https://api.openaire.eu/search/publications`
- **Response format**: XML-over-JSON (`data["response"]["results"]["result"]`); can return a dict (1 result) or a list — the collector normalises this automatically
- **DOI extraction**: from the `pid` list, filtering on `@classid == "doi"`
- **Pagination**: 1-based page number; max 10K results per query

### ORKG (Open Research Knowledge Graph)

ORKG is a structured knowledge graph for scientific research, maintained by TIB Hannover. It models papers, their contributions, and comparisons in a structured format.

- **Strengths**: Structured CS/research data, no key required, high DOI coverage
- **Weaknesses**: Small corpus (~55K papers), no abstracts, no year filter (year filtering applied downstream during aggregation)
- **Use for**: Structured CS research, contribution-level metadata, knowledge graph studies
- **Config key**: not required
- **API endpoint**: `https://orkg.org/api/papers`
- **Response format**: `data["content"]` (list of papers), `data["page"]["total_elements"]` for total count
- **URL fallback**: When `publication_info.url` is empty, URL is set to `https://orkg.org/paper/{orkg_id}`
- **Pagination**: 0-based page index

### Google Scholar (Deprecated)

**⚠️ This API is deprecated and is no longer recommended for use.**

- **Strengths**: Broadest coverage, includes grey literature
- **Weaknesses**: Web scraping (slow), low DOI coverage (20%), unreliable, requires Tor proxy setup
- **Use for**: ~~Maximum coverage~~ Not recommended — use OpenAlex or Semantic Scholar instead

## API Selection Guide

### For AI/CS Research
```yaml
apis:
  - SemanticScholar
  - DBLP
  - Arxiv
  - ORKG
```

### For Biomedical Research
```yaml
apis:
  - Elsevier
  - OpenAlex
  - Springer
```

### For Engineering
```yaml
apis:
  - IEEE
  - Arxiv
  - SemanticScholar
```

### For European/Open-Access Research
```yaml
apis:
  - OpenAIRE
  - HAL
  - OpenAlex
```

### For Broad Coverage (No Keys Required)
```yaml
apis:
  - OpenAlex
  - Arxiv
  - DBLP
  - HAL
  - OpenAIRE
  - ORKG
```

## Configuration

### API Keys

Get keys from:
- [Semantic Scholar](https://www.semanticscholar.org/product/api)
- [IEEE](https://developer.ieee.org/getting_started)
- [Elsevier](https://dev.elsevier.com/)
- [Springer](https://dev.springernature.com/)

### Rate Limits

Built-in defaults (`DEFAULT_RATE_LIMITS` in `scilex/config_defaults.py`, requests per second, with an API key where it matters).
Override any of them in the `rate_limits` section of `~/.config/scilex/keys.yml`:
```yaml
rate_limits:
  SemanticScholar: 1.0
  OpenAlex: 10.0
  IEEE: 2.0
  Elsevier: 9.0      # 2.0 without key
  Springer: 1.67
  Arxiv: 0.33
  HAL: 10.0
  DBLP: 1.0
  Istex: 5.0
  PubMed: 10.0       # 3.0 without key
  OpenAIRE: 1.0      # 0.2 without token
  ORKG: 0.5
```

## Coverage by Field

- **Computer Science**: SemanticScholar, DBLP, Arxiv, IEEE, ORKG
- **Life Sciences**: Elsevier, OpenAlex, Springer
- **Engineering**: IEEE, Springer, Arxiv
- **Physics/Math**: Arxiv, OpenAlex, Springer
- **Social Sciences**: OpenAlex, Springer
- **EU-funded Research**: OpenAIRE, HAL
- **French Research**: HAL, ISTEX

## Known Limitations

### Abstract Availability
- 100%: IEEE, Arxiv
- 95%: Semantic Scholar, ISTEX
- 90%: Springer
- 80%: Elsevier
- 70%: HAL, OpenAIRE
- 60%: OpenAlex
- 0%: DBLP (by policy), ORKG (by design)

### DOI Coverage
- 100%: Elsevier
- 98%: Springer, ISTEX
- 95%: IEEE, DBLP
- 90%: OpenAlex
- 85%: Semantic Scholar
- 80%: ORKG
- 75%: OpenAIRE
- 60%: Arxiv
- 40%: HAL

### Citation Data Available
- Yes: Semantic Scholar, OpenAlex
- No: All others
