# Quick Start Guide

Get your first paper collection running. This assumes you've [installed SciLEx](installation.md).

## Quick Start

### 1. Create the configuration

Create a folder for your review and generate a `scilex.yml` in it:

```bash
mkdir my-review && cd my-review
uv run scilex init                  # asks a few questions (or: scilex-init --template computer-science)
```

Or write a minimal `scilex.yml` by hand (everything else uses the defaults):

```yaml
name: test
search:
  keywords:
    - [machine learning]
  years: [2024]
  apis: [OpenAlex, Arxiv]
```

API keys live in `~/.config/scilex/keys.yml`, copied from `keys.yml.example` (OpenAlex and Arxiv work without keys).
Check everything without running anything:

```bash
uv run scilex config check
```

### 2. Run Collection

```bash
uv run scilex-collect
```

You'll see progress like:
```
Progress: 1/4 (25%) collections completed
Progress: 2/4 (50%) collections completed
...
```

### 3. Aggregate Results

```bash
uv run scilex-aggregate
```

Results saved to `output/test/aggregated_results.csv`

### 4. View Results

```bash
head output/test/aggregated_results.csv
```

Or open in spreadsheet software.

## Real Collection Example

For a proper research collection, edit `scilex.yml`:

```yaml
name: kg_llm
preset: literature_review

search:
  keywords:
    - [knowledge graph, ontology]      # Domain
    - [large language model, LLM]      # Technology
  years: [2022, 2023, 2024]
  apis: [SemanticScholar, OpenAlex, Arxiv]

filters:
  item_types: [journalArticle, conferencePaper]

ranking:
  max_papers: 500
```

Then run:
```bash
uv run scilex-collect
uv run scilex-aggregate
```

All options are listed in the [Configuration Reference](../reference/configuration.md).

## CSV Output Columns

- `title` - Paper title
- `authors` - Author list
- `year` - Publication year
- `DOI` - Digital Object Identifier
- `abstract` - Full abstract
- `itemType` - Publication type
- `citation_count` - Citations (if enabled)
- `quality_score` - Metadata completeness (0-100)
- `relevance_score` - Relevance (0-10)

## Next Steps

- [Modules](../modules/index.md) - Every step of a review, from screening to the knowledge graph
- [Desktop application](../user-guides/gui.md) - The same workflow without the command line

- [Configuration Guide](configuration.md) - Setting up `scilex.yml` and `keys.yml`
- [Configuration Reference](../reference/configuration.md) - Every option
- [Basic Workflow](../user-guides/basic-workflow.md) - Detailed workflow
- [Advanced Filtering](../user-guides/advanced-filtering.md) - Filtering options
