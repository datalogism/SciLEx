# Troubleshooting Guide

Common issues and solutions when using SciLEx.

## Installation Issues

### Python Version Error

**Problem**:
```
Error: Python 3.10+ required
```

**Solution**:
```bash
# Check your Python version
python --version

# Install Python 3.10+ (3.13 recommended) from python.org
# Or use pyenv
pyenv install 3.13
pyenv local 3.13
```

### Module Not Found

**Problem**:
```
ModuleNotFoundError: No module named 'pandas'
```

**Solution**:
```bash
# Reinstall dependencies
uv sync
# Or with pip
pip install -r requirements.txt
```

### uv Command Not Found

**Problem**:
```
bash: uv: command not found
```

**Solution**:
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or use pip instead
pip install -r requirements.txt
```

## API Issues

### API Key Invalid

**Problem**:
```
Error: IEEE API key validation failed
```

**Solution**:
1. Check your API key is correct in `~/.config/scilex/keys.yml` (`scilex config show` displays the effective values, secrets masked)
2. Verify the section name matches the API name exactly (e.g., `SemanticScholar`, `IEEE`)
3. Remove any extra spaces or quotes
4. Verify key is active on API provider's dashboard
5. Check if key has expired

### Rate Limit Errors (429)

**Problem**:
```
HTTP 429: Too Many Requests
```

**Solution**:
```yaml
# Lower rate limits in ~/.config/scilex/keys.yml
rate_limits:
  SemanticScholar: 0.5  # Reduce from 1.0
  IEEE: 1.0  # Reduce from 2.0
```

### Connection Timeout

**Problem**:
```
requests.exceptions.Timeout: Request timed out
```

**Solution**:
```bash
# Check internet connection
ping api.semanticscholar.org

# Try again - timeouts can be transient
# Or check if the API is down
```

### SSL Certificate Error

**Problem**:
```
SSL: CERTIFICATE_VERIFY_FAILED
```

**Solution (macOS)**:
```bash
pip install --upgrade certifi
```

## Collection Issues

### No Results Found

**Problem**: Collection returns 0 papers

**Solutions**:
1. Check keywords are not too specific
2. Try broader search terms
3. Try different years
4. Try different APIs
5. Search only in titles first:
   ```yaml
   fields: ["title"]
   ```

### Too Many Results

**Problem**: Collection returns millions of papers

**Solutions**:
1. Use dual keyword groups:
   ```yaml
   keywords:
     - ["specific term"]
     - ["another specific term"]
   ```
2. Limit results:
   ```yaml
   max_results_per_api: 1000
   ```
3. Reduce year range:
   ```yaml
   years: [2024]  # Just current year
   ```

### Collection Stuck

**Problem**: Collection appears frozen

**Solution**:
1. Check if it's actually making progress (logs update slowly for large queries)
2. Enable debug logging:
   ```bash
   LOG_LEVEL=DEBUG uv run scilex-collect
   ```
3. Check API rate limits aren't too low
4. Try with fewer APIs first

### Missing Output Directory

**Problem**:
```
FileNotFoundError: output/ directory not found
```

**Solution**:
```bash
# Create output directory
mkdir -p output
```

## Aggregation Issues

### No Papers After Filtering

**Problem**: Aggregation filters out all papers

**Solutions**:
1. Check dual keyword logic:
   ```yaml
   # If only one group is needed:
   search:
     keywords:
       - [your, keywords]  # one group only
   ```
2. Disable strict filters:
   ```yaml
   filters:
     citations: false
     item_types: null
   ```
3. Check the aggregation report for which filter removed papers

### Memory Error

**Problem**:
```
MemoryError: Unable to allocate array
```

**Solution**:
```bash
# Use parallel mode with batching (default)
uv run scilex-aggregate

# Or reduce the year range and re-collect
```

### Slow Aggregation

**Problem**: Aggregation takes too long

**Solution**:
```bash
# Ensure parallel mode is used (default)
uv run scilex-aggregate

# Skip citations if not needed:
uv run scilex-aggregate --skip-citations
# or set citations.fetch: false in scilex.yml
```

## Zotero Issues

### Upload Failed

**Problem**: Papers don't appear in Zotero

**Solution**:
1. Check the `Zotero` section of `~/.config/scilex/keys.yml`
2. Verify `user_mode` is set correctly (`user` or `group`)
3. Check that the target Zotero collection exists
4. Check Zotero storage quota

### Duplicate Papers

**Problem**: Same papers uploaded multiple times

**Solution**:
```bash
# The system checks URLs to avoid duplicates.
# If papers have different URLs they will be treated as distinct.
# You can manually deduplicate in Zotero using its built-in merge tool.
```

## Configuration Issues

### Invalid YAML

**Problem**:
```
yaml.scanner.ScannerError: mapping values are not allowed here
```

**Solution**:
1. Check indentation (use spaces, not tabs)
2. Check special characters are quoted:
   ```yaml
   search:
     keywords: [["term: with colon"]]  # Use quotes
   ```
3. Validate YAML online

### Config Not Found

**Problem**:
```
FileNotFoundError: No scilex.yml found
```

**Solution**:
```bash
# Run from the folder that contains scilex.yml, or point to it
ls scilex.yml
scilex-collect --config /path/to/scilex.yml

# Or create one
scilex init
```

## Data Quality Issues

### Missing Abstracts

**Problem**: Many papers have "NA" for abstracts

**Explanation**: Some APIs don't provide abstracts (e.g., DBLP by policy, ORKG by design). This is expected.

**Solution**: Use APIs with better abstract coverage:
- SemanticScholar (95%)
- IEEE (100%)
- Arxiv (100%)

### Low Citation Counts

**Problem**: Most papers show 0 citations

**Explanation**: OpenCitations has limited coverage for recent papers and preprints.

**Solution**: This is normal. Citation data is best-effort only.

### Incorrect Paper Metadata

**Problem**: Author names or titles incorrect

**Solution**: This comes from the source API. Report issues to the API provider.

## Debugging

### Enable Debug Logging

```bash
LOG_LEVEL=DEBUG uv run scilex-collect
```

### Check Logs

Look for errors in console output or check the collection directory for state files.

### Test Individual APIs

```bash
uv run python "src/API tests/SemanticScholarAPI.py"
uv run python "src/API tests/OpenAlexAPI.py"
```

### Verify Configuration

```bash
# Check syntax and values of scilex.yml and keys.yml
uv run scilex config check
```

## Getting Help

If none of these solutions work:

1. Check console output for error messages
2. Enable DEBUG logging
3. Try with a minimal configuration
4. Check if the issue is API-specific

## Common Error Messages

### "Circuit breaker OPEN"

**Meaning**: API has failed multiple times and is being skipped

**Action**: This is normal. The system will retry later. If persistent, check API status.

### "Waiting for rate limit"

**Meaning**: Respecting API rate limits

**Action**: This is normal. Be patient or adjust rate limits.

### "Query already completed, skipping"

**Meaning**: Results already exist for this query

**Action**: This is normal (idempotent behavior). Delete the output directory to re-collect.
