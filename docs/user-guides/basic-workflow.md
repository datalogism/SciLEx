# Basic Workflow Guide

Standard workflow for collecting and aggregating papers.

## Workflow Steps

1. **Collection** - Query APIs and download metadata
2. **Aggregation** - Deduplicate and filter
3. **Export** - Push to Zotero (optional)

## Step 1: Collection

### Configure Search

Create `scilex.yml` in the folder of your review (`scilex init`, or by hand):

```yaml
name: my_review
search:
  keywords:
    - [machine learning]
  years: [2023, 2024]
  apis: [SemanticScholar, OpenAlex]
```

Validate it with `scilex config check`. API keys go in `~/.config/scilex/keys.yml` (see the
[Configuration Reference](../reference/configuration.md)).

### Run Collection

```bash
uv run scilex-collect
```

Results saved to `output/<name>/` (`name` from `scilex.yml`).

Output structure:
```
output/my_review/
├── config_used.yml
├── SemanticScholar/
│   ├── 0/              # Query 0: keyword[0] + year[0]
│   │   ├── page_1
│   │   └── page_2
├── OpenAlex/
```

### Idempotent Behavior

Re-running collection skips already completed queries. Safe to re-run without wasting API quotas.

## Step 2: Aggregation

### Basic Aggregation

```bash
uv run scilex-aggregate
```

Process:
1. Loads JSON files
2. Converts to unified format
3. Deduplicates (DOI, URL, fuzzy title)
4. Applies keyword filtering
5. Scores quality
6. Saves to CSV

### With Citations

Enabled by default (`citations.fetch: true` in `scilex.yml`). Use `scilex-aggregate --skip-citations` to skip it for one run.

Citations are fetched from cache → Semantic Scholar → OpenCitations.

### Output

CSV saved to `output/<name>/aggregated_results.csv`

Columns:
- `title`, `authors`, `year`, `DOI`, `abstract`
- `itemType` - Publication type
- `publicationTitle` - Journal/conference
- `citation_count` - Citations (if enabled)
- `quality_score` - Metadata completeness (0-100)
- `relevance_score` - Relevance (0-10)

## Step 3: Export to Zotero

### Configure

Edit `~/.config/scilex/keys.yml`:

```yaml
Zotero:
  api_key: "your-key"
  user_id: "your-user-id"
  user_mode: user  # or "group"
```

### Run Export

```bash
uv run scilex-push-zotero
```

Papers uploaded in batches. Duplicates skipped by URL.

## Filtering Pipeline

Aggregation applies filters:

1. **ItemType** - Keep allowed publication types
2. **Keywords** - Match search terms
3. **Deduplication** - Remove duplicates
4. **Quality** - Remove low-quality metadata
5. **Citations** - Time-aware thresholds
6. **Relevance** - Score and limit to top N

Check logs to see papers filtered at each step.

## Complete Example

```yaml
# scilex.yml
name: kg_llm
search:
  keywords:
    - [knowledge graph]
    - [LLM, large language model]
  years: [2023, 2024]
  apis: [SemanticScholar, OpenAlex]

filters:
  item_types: [journalArticle, conferencePaper]

ranking:
  max_papers: 300
```

Run:
```bash
uv run scilex-collect
uv run scilex-aggregate
uv run scilex-push-zotero
```

## Analyze Results

```python
import pandas as pd

df = pd.read_csv('output/my_review/aggregated_results.csv', delimiter=';')

print(f"Total papers: {len(df)}")
print(f"\nPapers by year:")
print(df['year'].value_counts().sort_index())
print(f"\nTop cited:")
print(df.nlargest(10, 'nb_citation')[['title', 'nb_citation']])
```

## Log Levels

```bash
# Default (clean output)
uv run scilex-collect

# Detailed progress
LOG_LEVEL=INFO uv run scilex-collect

# Full debugging
LOG_LEVEL=DEBUG uv run scilex-collect
```

## Next Steps

- [Modules](../modules/index.md) - Screening, annotation, extension, enrichment, analyses, export
- [Command-line reference](../reference/cli.md) - Every command

- [Advanced Filtering](advanced-filtering.md) - Filtering options
- [Configuration](../getting-started/configuration.md) - All config parameters
- [API Comparison](../reference/api-comparison.md) - API details
