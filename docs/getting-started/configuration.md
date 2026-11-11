# Configuration Guide

This guide shows how to configure SciLEx for your research. For the exhaustive list of keys, defaults,
presets, environment variables and the old-to-new name table, see the
[Configuration Reference](../reference/configuration.md).

## Two files

1. **`scilex.yml`**: one per review, in your working folder (search, filters, ranking, enrichment).
2. **`keys.yml`**: your API keys and rate limits, shared by all reviews, in `~/.config/scilex/keys.yml`.

Templates: `scilex.yml.example` and `keys.yml.example` at the repository root.

```bash
mkdir my-review && cd my-review
scilex init                                     # creates ./scilex.yml
mkdir -p ~/.config/scilex
cp /path/to/SciLEx/keys.yml.example ~/.config/scilex/keys.yml
scilex config check                             # validate without running anything
scilex config show                              # effective values and where each comes from
```

You only write what differs from the defaults. A typo is reported with a suggestion instead of being ignored.

Discovery order: `scilex.yml` is `--config PATH`, then `$SCILEX_CONFIG`, then `./scilex.yml`.
`keys.yml` is `--keys PATH`, then `$SCILEX_KEYS`, then `~/.config/scilex/keys.yml`.

## Basic Configuration

```yaml
name: my_collection              # results go to output/my_collection
output_dir: output

search:
  keywords:
    - [knowledge graph, ontology]      # Group 1
    - [large language model, LLM]      # Group 2
  years: [2022, 2023, 2024]
  apis: [SemanticScholar, OpenAlex, Arxiv]
```

### Keywords

One group: papers matching ANY term.

```yaml
search:
  keywords:
    - [neural network, deep learning, CNN, RNN]
```

Two groups: papers must contain at least one term from EACH group.

```yaml
search:
  keywords:
    - [climate, weather, temperature]     # Topic
    - [prediction, forecast, model]       # Method
```

## Filtering Configuration

```yaml
filters:
  item_types: [journalArticle, conferencePaper]   # whitelist (null = all types)
  abstract_quality: 60                            # drop low-quality abstracts (null = off)
  citations: true                                 # time-aware citation filter

citations:
  fetch: true                                     # fetch citation counts during aggregation

ranking:
  enabled: true
  max_papers: 500                                 # keep the top 500 (null = no limit)
  weights: {keywords: 0.45, quality: 0.25, itemtype: 0.20, citations: 0.10}
```

See [Advanced Filtering](../user-guides/advanced-filtering.md) for how each filter behaves.

### Presets

`preset: literature_review` (requires abstract and year, citation filter on, abstract quality 60) or
`preset: bibliometrics` (no required fields, no citation filter, no cap on papers) set several filters at once.
Your own keys in `scilex.yml` override the preset.

## Common Configurations

### Quick Test

```yaml
name: quick_test
search:
  keywords: [[test]]
  years: [2024]
  apis: [OpenAlex]
  max_articles_per_query: 10
```

### Comprehensive Search

```yaml
name: ai_survey
preset: literature_review
search:
  keywords:
    - [artificial intelligence, AI]
  years: "2020-2024"
  apis: [SemanticScholar, OpenAlex, IEEE, Arxiv, OpenAIRE]
ranking:
  max_papers: 1000
```

### Focused Conference Papers

```yaml
name: nn_conferences
search:
  keywords: [[neural networks]]
  years: [2023, 2024]
  apis: [SemanticScholar, DBLP]
filters:
  item_types: [conferencePaper]
```

### Incremental update

```yaml
search:
  since: 2025-06-01      # re-collect only newer records; merged by scilex-aggregate
```

## API Selection

### APIs Without Keys

These APIs work without any configuration:
- OpenAlex
- Arxiv
- DBLP
- HAL
- ISTEX
- OpenAIRE
- ORKG

### APIs Requiring Keys

Must be configured in `~/.config/scilex/keys.yml`:
- SemanticScholar (optional but recommended for higher rate limits)
- IEEE
- Elsevier
- Springer

A pool of keys can be given as a list (`api_key: ["k1", "k2"]`); SciLEx rotates between them.

## Environment Variables

```bash
export LOG_LEVEL=INFO                              # log verbosity
export LOG_COLOR=false                             # disable colored output
export SCILEX_SEMANTICSCHOLAR_API_KEY=...          # override keys.yml (SCILEX_<API>_<FIELD>)
export OPENROUTER_API_KEY=...                      # for llm_screening
export SCILEX_CONFIG=/path/to/scilex.yml           # same as --config
export SCILEX_KEYS=/path/to/keys.yml               # same as --keys
```

## Migrating from the old format

Older versions used `scilex/scilex.config.yml`, `scilex/scilex.advanced.yml` and `scilex/api.config.yml`.
They are still read, with a warning. Convert them with `scilex config migrate --write`
(`--from DIR` to read them from another folder), then move your keys to `~/.config/scilex/keys.yml`.
The old-to-new name table is in the [reference](../reference/configuration.md).

## Tips

1. **Start Small**: Test with one year and one API
2. **Use Open APIs First**: No keys needed (OpenAlex, Arxiv, OpenAIRE, ORKG)
3. **Add APIs Gradually**: Test each one separately
4. **Check Rate Limits**: Respect API quotas (`rate_limits` in `keys.yml`)
5. **Save Working Configs**: `scilex-init --save-profile NAME` stores a `scilex.yml` for reuse

## Next Steps

- See [Quick Start](quick-start.md) for your first collection
- See [Configuration Reference](../reference/configuration.md) for every option
- See [Advanced Filtering](../user-guides/advanced-filtering.md) for filtering options
- See [API Comparison](../reference/api-comparison.md) for API details
