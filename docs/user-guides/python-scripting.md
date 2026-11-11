# Python Scripting Guide

Use SciLEx as a Python library to integrate paper collection into your own scripts and workflows.

## Setup

All SciLEx modules in `src/` rely on YAML config files. Add `src/` to your Python path before importing:

```python
import sys
import os

# Add src/ to path so crawlers and other modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
```

Load `scilex.yml` and `keys.yml` with the same discovery rules as the CLI (`SCILEX_CONFIG`, `./scilex.yml`,
`SCILEX_KEYS`, `~/.config/scilex/keys.yml`):

```python
from scilex.config import SciLExConfig

config = SciLExConfig.from_files()                       # or config_path="scilex.yml", keys_path="keys.yml"
main_config, api_config = config.main_config, config.api_config
```

`main_config` and `api_config` are the internal dictionaries used by the pipeline (a flat form of `scilex.yml`,
with `collect_name` for `name` and a `quality_filters` block). See the
[Configuration Reference](../reference/configuration.md) for the correspondence.

Or build the internal dictionaries entirely in Python (no YAML files needed, as the web API does with `SciLExConfig.from_dicts`):

```python
main_config = {
    "keywords": [["machine learning", "deep learning"], ["healthcare"]],
    "years": [2024, 2025],
    "apis": ["SemanticScholar", "OpenAlex"],
    "output_dir": "output",
    "collect_name": "collect_20250101_120000",
    "collect": True,
    "aggregate_get_citations": False,
    "aggregate_file": "aggregated_results.csv",
}

api_config = {
    "SemanticScholar": {},
    "OpenAlex": {},
}
```

## Collect Papers

Run API collection programmatically using `CollectCollection`:

```python
import os
import sys
import yaml

sys.path.insert(0, 'src')
from crawlers.collector_collection import CollectCollection

# Ensure output directory exists
output_dir = main_config.get("output_dir", "output")
if not os.path.isdir(output_dir):
    os.makedirs(output_dir)
    # Save config snapshot (required for aggregation)
    with open(os.path.join(output_dir, "config_used.yml"), "w") as f:
        yaml.dump(main_config, f)

# Run collection
collector = CollectCollection(main_config, api_config)
collector.create_collects_jobs()
```

## Aggregate and Filter

The aggregation script reads config at import time. Invoke it via `sys.argv`:

```python
import sys

sys.path.insert(0, 'src')

# Set arguments before importing
sys.argv = ["aggregate", "--skip-citations", "--workers", "3"]

from aggregate_collect import main as aggregate_main

aggregate_main()
```

Then read the results:

```python
import pandas as pd

csv_path = "output/collect_20250101_120000/aggregated_results.csv"
df = pd.read_csv(csv_path, delimiter=";")

print(f"Total papers: {len(df)}")
print(f"Papers by year:\n{df['year'].value_counts().sort_index()}")
print(f"\nTop 10 cited:")
print(df.nlargest(10, "nb_citation")[["title", "nb_citation"]])
```

## Export to BibTeX

```python
import sys

sys.path.insert(0, 'src')

from export_to_bibtex import main as bibtex_main

bibtex_main()
# Creates: output/collect_*/aggregated_results.bib
```

## Push to Zotero

```python
import sys

sys.path.insert(0, 'src')

from push_to_Zotero_collect import main as zotero_main

zotero_main()
```

## Full Pipeline Script

A complete end-to-end script combining all steps:

```python
"""Full SciLEx pipeline: collect, aggregate, export."""

import os
import sys

import yaml

# ── Path setup ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# ── 1. Configuration ──────────────────────────────────────────────

main_config = {
    "keywords": [["large language model", "LLM"], ["evaluation", "benchmark"]],
    "years": [2024, 2025],
    "apis": ["SemanticScholar", "OpenAlex", "Arxiv"],
    "output_dir": "output",
    "collect_name": "llm_benchmarks",
    "collect": True,
    "aggregate_get_citations": False,
    "aggregate_file": "aggregated_results.csv",
    "quality_filters": {
        "enable_itemtype_filter": True,
        "allowed_item_types": ["journalArticle", "conferencePaper", "preprint"],
        "apply_relevance_ranking": True,
        "max_papers": 200,
    },
}

api_config = {
    "SemanticScholar": {},
    "OpenAlex": {},
}

# ── 2. Collection ─────────────────────────────────────────────────

from crawlers.collector_collection import CollectCollection

output_dir = main_config["output_dir"]
os.makedirs(output_dir, exist_ok=True)

config_path = os.path.join(output_dir, "config_used.yml")
if not os.path.exists(config_path):
    with open(config_path, "w") as f:
        yaml.dump(main_config, f)

collector = CollectCollection(main_config, api_config)
collector.create_collects_jobs()
print("Collection complete.")

# ── 3. Aggregation ────────────────────────────────────────────────

sys.argv = ["aggregate", "--skip-citations"]

from aggregate_collect import main as aggregate_main

aggregate_main()
print("Aggregation complete.")

# ── 4. Analyze results ────────────────────────────────────────────

import pandas as pd

csv_path = os.path.join(
    output_dir, main_config["collect_name"], "aggregated_results.csv"
)
df = pd.read_csv(csv_path, delimiter=";")

print(f"\nResults: {len(df)} papers")
print(f"Sources: {df['archive'].value_counts().to_dict()}")
print(f"Years: {df['year'].value_counts().sort_index().to_dict()}")
```

## Important Notes

- **Working directory**: Run scripts from the project root so relative paths resolve correctly.
- **Path setup**: Always add `src/` to `sys.path` before importing SciLEx modules.
- **Multiprocessing**: Collection uses spawn mode. Always run collection code inside an `if __name__ == "__main__":` guard.
- **sys.argv**: Modules that use `argparse` parse `sys.argv` in their `main()`. Set `sys.argv` before calling `main()` to pass arguments programmatically.
- **CSV delimiter**: The output CSV uses `;` as delimiter, not `,`.

## Next Steps

- [Basic Workflow](basic-workflow.md) - CLI-based workflow
- [Advanced Filtering](advanced-filtering.md) - Filtering options
- [Configuration](../getting-started/configuration.md) - All config parameters
