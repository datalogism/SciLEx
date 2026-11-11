# Advanced Filtering Guide

SciLEx applies a 5-phase filtering pipeline to refine paper collections.

## Filtering Pipeline

1. **ItemType Filter** - Keep specific publication types
2. **Keyword Match** - Verify search term relevance
3. **Quality Score** - Check metadata completeness
4. **Citation Filter** - Time-aware citation thresholds
5. **Relevance Rank** - Score and limit to top N papers

## Phase 1: ItemType Filtering

Keep only specific publication types.

```yaml
filters:
  item_types:          # null (default) keeps every type
    - journalArticle
    - conferencePaper
    - bookSection
    - book
  always_keep: [journalArticle, conferencePaper]   # types never removed by the quality filters
```

Common types:
- `journalArticle` - Peer-reviewed journals
- `conferencePaper` - Conference proceedings
- `book` - Academic books
- `bookSection` - Book chapters
- `preprint` - Pre-publication
- `thesis` - Dissertations
- `report` - Technical reports

## Phase 2: Keyword Matching

### Single Group (OR Logic)

Papers match ANY keyword:

```yaml
search:
  keywords:
    - [neural network, deep learning, CNN]
```

### Dual Group (AND Logic)

Papers must match at least one from EACH group:

```yaml
search:
  keywords:
    - [climate, weather]         # Topic
    - [prediction, forecast]     # Method
```

## Phase 3: Quality Scoring

Scores metadata completeness (0-100):

- Critical fields (5 pts each): DOI, title, authors, year
- Important fields (3 pts each): abstract, journal, volume, issue
- Nice-to-have (1 pt each): pages, URL, keywords

```yaml
filters:
  require: [abstract, year]    # among abstract, doi, year, open_access
  min_authors: 2
  abstract_words: [50, 1000]   # [min, max]
  abstract_quality: 60         # score 0-100; null disables the validation
```

## Phase 4: Citation Filtering

Time-aware thresholds based on paper age:

- 0-3 months: 0 citations required
- 3-6 months: 1+ required
- 6-12 months: 3+ required
- 12-24 months: 5-8+ required
- 24+ months: 10+ required

```yaml
citations:
  fetch: true                  # fetch citation counts during aggregation

filters:
  citations: true              # apply the time-aware thresholds
```

The thresholds above are fixed in the code (`CitationFilterConfig`); `filters.citations` only switches the filter on or off.

## Phase 5: Relevance Ranking

Composite score combining:
- Keyword frequency (45%)
- Metadata quality (25%)
- Publication type (20%)
- Citation impact (10%)

```yaml
ranking:
  enabled: true
  max_papers: 500  # Keep top 500 (null = no limit)

  weights:
    keywords: 0.45
    quality: 0.25
    itemtype: 0.20
    citations: 0.10
  venue_ranking: false   # true adds a CORE/SJR venue rank and blends it into the score
```

## Complete Configuration

```yaml
name: xai_healthcare
preset: literature_review

search:
  keywords:
    - [explainable AI, XAI]
    - [healthcare, medical]
  years: [2022, 2023, 2024]
  apis: [SemanticScholar, OpenAlex]

filters:
  # Phase 1
  item_types: [journalArticle, conferencePaper]
  # Phase 3
  abstract_quality: 60
  # Phase 4
  citations: true

citations:
  fetch: true

# Phase 5
ranking:
  enabled: true
  max_papers: 300
  weights: {keywords: 0.45, quality: 0.25, itemtype: 0.20, citations: 0.10}
```

## Monitoring

Check the aggregation report:

```
Initial papers: 10,000
After ItemType: 7,000
After Keywords: 4,200
After Quality: 3,360
After Citations: 2,352
After Relevance: 300
```

All keys are documented in the [Configuration Reference](../reference/configuration.md).

## Troubleshooting

### Too Few Papers?

1. Relax keyword restrictions (use single group mode)
2. Lower quality thresholds
3. Disable citation filter

```yaml
filters:
  citations: false
  abstract_quality: 40
```

### Too Many Papers?

1. Use dual keyword groups (AND logic)
2. Enable all filters
3. Set lower `ranking.max_papers` limit

### Check Results

```python
import pandas as pd

df = pd.read_csv('output/<name>/aggregated_results.csv', delimiter=';')

# Check scores
top = df.nlargest(10, 'relevance_score')
print(top[['title', 'relevance_score', 'quality_score', 'nb_citation']])
```
