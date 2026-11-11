# Installation Guide

## Prerequisites

- Python 3.10+ (3.12 or 3.13 recommended); the desktop app builds need no Python
- uv package manager (or pip)
- 4GB RAM minimum

## Installation

### 1. Install Dependencies

```bash
cd SciLEx
uv sync
```

Or with pip:
```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

API keys are stored once, outside any project, in `~/.config/scilex/keys.yml`:

```bash
mkdir -p ~/.config/scilex
cp keys.yml.example ~/.config/scilex/keys.yml
nano ~/.config/scilex/keys.yml
```

Keep only the APIs you use:

```yaml
# Semantic Scholar (optional but recommended for higher rate limits)
SemanticScholar:
  api_key: "your-key-here"

# IEEE (required if using IEEE Xplore)
IEEE:
  api_key: "your-key"

# Elsevier (required if using)
Elsevier:
  api_key: "your-key"

# Springer (required if using)
Springer:
  api_key: "your-key"

# Zotero (for export)
Zotero:
  api_key: "your-key"
  user_id: "your-user-id"
  user_mode: user  # or "group" for group libraries
```

Section names are case-sensitive and match the API names (`SemanticScholar`, `OpenAlex`, ...).
A key can also come from an environment variable such as `SCILEX_SEMANTICSCHOLAR_API_KEY`.
See the [Configuration Reference](../reference/configuration.md) for every field.

Get API keys from:
- [Semantic Scholar](https://www.semanticscholar.org/product/api)
- [IEEE](https://developer.ieee.org/getting_started)
- [Elsevier](https://dev.elsevier.com/)
- [Springer](https://dev.springernature.com/)

The following APIs do **not** require a key: OpenAlex, arXiv, DBLP, HAL, ISTEX, OpenAIRE, ORKG.

### 3. Configure Search

In the folder of your review, create `scilex.yml`:

```bash
scilex init
```

or write it by hand:

```yaml
name: my_review
search:
  keywords:
    - [machine learning]
  years: [2023, 2024]
  apis: [OpenAlex, Arxiv]
```

## Verify Installation

```bash
# Test that dependencies are installed
uv run python -c "import pandas, requests, yaml; print('OK')"

# Validate the configuration files
uv run scilex config check

# Run a test collection
uv run scilex-collect
```

## Common Issues

### Python Version Error
Install Python 3.10+ from [python.org](https://www.python.org)

### Module Not Found
```bash
uv sync
# or
pip install -r requirements.txt
```

### API Key Invalid
- Check for typos in `~/.config/scilex/keys.yml` (run `scilex config show`; secrets are masked)
- Verify the section name matches exactly (e.g., `SemanticScholar`)
- Verify the key is active on the API provider's dashboard

## Next Steps

- [Quick Start](quick-start.md) - Run your first collection
- [Configuration](configuration.md) - Detailed config options
- [Configuration Reference](../reference/configuration.md) - Every option
- [Troubleshooting](troubleshooting.md) - More solutions
