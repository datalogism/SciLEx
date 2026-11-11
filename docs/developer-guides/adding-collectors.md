# Adding API Collectors Guide

Guide for adding new academic API collectors to SciLEx.

## Overview

Steps to add a collector:
1. Create collector class
2. Implement required methods
3. Create format converter
4. Register collector
5. Add configuration
6. Test

## Collector Class

Create in `src/crawlers/collectors.py`:

```python
class YourAPI_collector(API_collector):
    """Collector for YourAPI."""

    def __init__(self, config=None):
        super().__init__()
        self.api_name = "YourAPI"  # Must match config and registration key
        self.base_url = "https://api.yourapi.com"
        self.max_by_page = 100

        if config:
            self.api_key = config.get('yourapi', {}).get('api_key')

        self.load_rate_limit_from_config(config)  # Always call last

    def get_configurated_url(self):
        """Return URL template with {} placeholder for page/offset."""
        params = f"query={{}}&pageSize={self.max_by_page}"
        if self.api_key:
            params += f"&apiKey={self.api_key}"
        return f"{self.base_url}/search?{params}"

    def get_offset(self, page):
        """Return the value to substitute into the URL template for the given page.

        Examples:
        - 1-based page (OpenAlex, OpenAIRE style): return page
        - 0-based page (ORKG style): return page - 1
        - Offset-based (DBLP, ISTEX style): return (page - 1) * self.max_by_page
        """
        return page  # adjust as needed for your API

    def query_build(self, keywords, year, fields):
        """Build the API query string from keywords and year."""
        # Single group mode
        if not keywords[1]:
            query = " OR ".join(keywords[0])
        # Dual group mode
        else:
            g1 = "(" + " OR ".join(keywords[0]) + ")"
            g2 = "(" + " OR ".join(keywords[1]) + ")"
            query = f"{g1} AND {g2}"

        return f"{query} AND year:{year}"

    def parsePageResults(self, response, page):
        """Parse one page of API response.

        Must return a dict with keys:
          date_search, id_collect, page, total, results
        """
        data = response.json()

        total = data.get("total", 0)
        results = data.get("items", [])

        return {
            "date_search": self.date_search,
            "id_collect": self.id_collect,
            "page": page,
            "total": total,
            "results": results,
        }
```

## Format Converter

Add to `src/crawlers/aggregate.py`:

```python
from scilex.constants import MISSING_VALUE, is_valid

def YourAPItoZoteroFormat(paper):
    """Convert YourAPI format to Zotero-compatible unified format."""

    # Determine item type
    item_type = 'journalArticle'  # Default
    pub_type = paper.get('type', '').lower()
    if 'conference' in pub_type:
        item_type = 'conferencePaper'
    elif 'book' in pub_type:
        item_type = 'book'

    # Format authors
    authors = paper.get('authors', [])
    author_str = ', '.join(authors) if authors else MISSING_VALUE

    return {
        'itemType': item_type,
        'title': paper.get('title', MISSING_VALUE),
        'authors': author_str,
        'abstractNote': paper.get('abstract', MISSING_VALUE),
        'date': str(paper.get('year', MISSING_VALUE)),
        'DOI': paper.get('doi', MISSING_VALUE),
        'url': paper.get('url', MISSING_VALUE),
        'publicationTitle': paper.get('journal', MISSING_VALUE),
        'volume': str(paper.get('volume', MISSING_VALUE)),
        'issue': str(paper.get('issue', MISSING_VALUE)),
        'pages': paper.get('pages', MISSING_VALUE),
        'year': str(paper.get('year', MISSING_VALUE)),
        'citation_count': paper.get('citations', 0),
    }
```

## Registration

### Register the collector

In `src/crawlers/collector_collection.py`:

```python
api_collectors = {
    'SemanticScholar': SemanticScholar_collector,
    'OpenAlex': OpenAlex_collector,
    # Add your collector
    'YourAPI': YourAPI_collector,
}
```

### Register the format converter

In `src/crawlers/aggregate.py` (in the `FORMAT_CONVERTERS` dict):

```python
FORMAT_CONVERTERS = {
    'SemanticScholar': SemanticScholartoZoteroFormat,
    'OpenAlex': OpenAlextoZoteroFormat,
    # Add your converter
    'YourAPI': YourAPItoZoteroFormat,
}
```

## Configuration

Add the API's credentials to `keys.yml.example` (users copy it to `~/.config/scilex/keys.yml`):

```yaml
# YourAPI
YourAPI:
  api_key: "your-key-here"   # a string or a list of strings (key pool)

# Optional rate limit override (requests/second)
# rate_limits:
#   YourAPI: 2.0
```

Built-in defaults live in `DEFAULT_RATE_LIMITS` in `scilex/config_defaults.py` (`without_key` / `with_key`).

Add the API name to the `search.apis` list of `scilex.yml.example`:

```yaml
search:
  apis: [SemanticScholar, OpenAlex, YourAPI]
```

## Testing

Create a test script at `src/API tests/YourAPITest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from crawlers.collectors import YourAPI_collector
from crawlers.aggregate import YourAPItoZoteroFormat
from scilex.config import SciLExConfig

def test_collector():
    # Load config
    config = SciLExConfig.from_files().api_config   # reads keys.yml

    # Test collection
    collector = YourAPI_collector(config)
    papers = collector.run([["test"]], 10, 2024, ["title"])

    print(f"Retrieved {len(papers)} papers")

    if papers:
        # Test converter
        zotero_item = YourAPItoZoteroFormat(papers[0])
        print(f"Title: {zotero_item['title']}")

if __name__ == "__main__":
    test_collector()
```

Run:
```bash
uv run python "src/API tests/YourAPITest.py"
```

For unit tests with fixtures, create `tests/test_yourapi_collector.py`:

```python
from unittest.mock import MagicMock
import json

def test_parse_page_results():
    import sys
    sys.path.insert(0, 'src')
    from crawlers.collectors import YourAPI_collector

    collector = YourAPI_collector()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "total": 1,
        "items": [{"title": "Test Paper", "year": 2024}]
    }

    result = collector.parsePageResults(mock_response, 1)
    assert result["total"] == 1
    assert len(result["results"]) == 1
```

Run all tests:
```bash
uv run python -m pytest tests/
```

## Key Points

### Rate Limiting

The base `API_collector` class provides `load_rate_limit_from_config()`. Always call it at the end of `__init__` after setting `self.api_name`:

```python
def __init__(self, config=None):
    super().__init__()
    self.api_name = "YourAPI"
    # ... other setup ...
    self.load_rate_limit_from_config(config)  # Must be last
```

### MISSING_VALUE

Always use `MISSING_VALUE` from `scilex.constants` for missing fields — never use `None` or `""`:

```python
from scilex.constants import MISSING_VALUE, is_valid

title = paper.get('title') or MISSING_VALUE
if is_valid(title):
    # field is present
```

### Handling Dict vs List Responses

Some APIs return a single result as a dict instead of a list when there is only one result. Always normalise:

```python
results = data.get("results", [])
if isinstance(results, dict):
    results = [results]  # Wrap single result in a list
```

### Error Handling

```python
try:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
except requests.Timeout:
    print(f"Timeout on page {page}")
    break
except requests.HTTPError as e:
    if e.response.status_code == 429:
        print("Rate limited")
        sleep(60)
    else:
        raise
```

### Pagination Strategies

```python
# Offset-based (DBLP, ISTEX style)
def get_offset(self, page):
    return (page - 1) * self.max_by_page

# 1-based page (OpenAlex, OpenAIRE style)
def get_offset(self, page):
    return page

# 0-based page (ORKG style)
def get_offset(self, page):
    return page - 1
```

## Checklist

Before submitting:

- [ ] Collector inherits from `API_collector`
- [ ] `api_name` matches the registration key exactly
- [ ] `load_rate_limit_from_config()` called at end of `__init__`
- [ ] `get_configurated_url()` returns a template with `{}` placeholder
- [ ] `get_offset(page)` returns the correct value for this API's pagination style
- [ ] `parsePageResults()` returns `{date_search, id_collect, page, total, results}`
- [ ] Handles dict vs list in API responses (normalise to list)
- [ ] Format converter uses `MISSING_VALUE` for all missing fields
- [ ] Registered in both `api_collectors` and `FORMAT_CONVERTERS` dicts
- [ ] Config examples added to `keys.yml.example`
- [ ] Test script created in `src/API tests/`
- [ ] Unit tests added in `tests/`
- [ ] Code formatted with `uvx ruff format .`

## Common Issues

### Case Sensitivity
Ensure `api_name` matches the registration key and config value exactly.

### Missing Data
Always use `MISSING_VALUE` for missing fields, never `None`.

### Rate Limits
Start conservative, test with small batches first.

## Next Steps

See [Architecture](architecture.md) for system design details.
