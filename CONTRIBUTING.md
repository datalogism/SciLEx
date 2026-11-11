# Contributing to SciLEx

## Setup

```bash
uv sync --extra dev
mkdir -p ~/.config/scilex && cp keys.yml.example ~/.config/scilex/keys.yml   # API keys (optional for tests)
cp scilex.yml.example scilex.yml                                              # a review config, only to run the CLI
uv run python -m pytest tests/
```

## Workflow

1. Fork the repository and clone your fork locally
2. Branch off `main`: `git checkout -b feature/your-feature`
3. Make changes, add tests
4. Format and lint: `uvx ruff format . && uvx ruff check --fix .`
5. Open a pull request against `main` with a clear description of your changes

## Code Style

- `ruff` for formatting and linting (configured in `pyproject.toml`)
- Google-style docstrings
- Use `MISSING_VALUE` / `is_valid()` from `scilex/constants.py` — never hardcode `None` or `"NA"`
- Use `logging`, not `print`

## Commits

Follow [conventional commits](https://www.conventionalcommits.org/):

```
feat(collector): add OpenAlex collector
fix(aggregate): correct dedup for IEEE papers
docs: update installation guide
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

## Adding a New API Collector

See [`docs/developer-guides/adding-collectors.md`](docs/developer-guides/adding-collectors.md).

## Reporting Issues

Open a GitHub issue with: steps to reproduce, expected vs actual behavior, Python version, and full traceback.
