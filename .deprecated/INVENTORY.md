# Deprecated Code Inventory

This directory contains code that has been deprecated and will be removed in a future version.

**Date Created:** 2026-01-22
**Status:** Deprecated - Safe to delete after backup period
**Verification Status:** ✅ No active imports found

---

## Deprecated Modules

### 1. PapersWithCode Integration (`src/PWC/`)
- **Reason:** Replaced by HuggingFace enrichment
- **Replacement:** `src/getHF_collect.py` and `src/enrich_with_hf.py`
- **Location:** `src/PWC/` (entire directory)
- **Files:**
  - All files in the PWC directory
- **Import Check:** ✅ No active imports from `src.PWC`

### 2. Tagging Module (`src/tagging/`)
- **Reason:** Functionality integrated into main pipeline
- **Location:** `src/tagging/` (entire directory)
- **Import Check:** ✅ No active imports from `src.tagging`

### 3. ORCID Integration (`src/orcid/`)
- **Reason:** Not actively used in current pipeline
- **Location:** `src/orcid/` (entire directory)
- **Import Check:** ✅ No active imports from `src.orcid`

### 4. DOI Module (`src/doi/`)
- **Reason:** Functionality integrated into aggregate pipeline
- **Location:** `src/doi/` (entire directory)
- **Import Check:** ✅ No active imports from `src.doi`

### 5. Text Analysis Module (`src/text_analysis/`)
- **Reason:** Not actively used in current pipeline
- **Location:** `src/text_analysis/` (entire directory)
- **Import Check:** ✅ No active imports from `src.text_analysis`

### 6. Annotation Agreement Module (`src/annotation_agreement/`)
- **Reason:** Research/experimental code, not part of production pipeline
- **Location:** `src/annotation_agreement/` (entire directory)
- **Import Check:** ✅ No active imports from `src.annotation_agreement`

---

## Deprecated Collectors

### 1. PubMed Central Collector (`src/crawlers/collectors/pubmed_central.py`)
- **Reason:** Replaced by comprehensive PubMed collector with integrated PMC PDF enrichment
- **Replacement:** `src/crawlers/collectors/pubmed.py`
- **Date Deprecated:** 2026-01-22
- **Location:** `.deprecated/collectors/pubmed_central.py`
- **Size:** ~14KB
- **Key Changes:**
  - PubMed collector provides 5x more papers (35M vs 7M)
  - Same open-access PDF coverage (~20-30% of papers)
  - Automatic PMCID detection and PDF URL construction
  - Metadata for paywalled papers (useful for systematic reviews)
- **Migration:** Update `scilex.config.yml` to use `PubMed` instead of `PubMedCentral`
- **Import Check:** ⚠️ Still referenced in code (will be removed in cleanup phase)

### 2. Google Scholar Collector (`scilex/crawlers/collectors/google_scholar.py`)
- **Reason:** Unreliable scraping, requires Tor proxy, frequent blocking by Google
- **Replacement:** Use `SemanticScholar` or `OpenAlex` for broad coverage
- **Date Deprecated:** 2026-02-16
- **Location:** `.deprecated/collectors/google_scholar.py`
- **Key Issues:**
  - Relies on web scraping (no official API) - fragile and unreliable
  - Requires Tor proxy setup for IP rotation
  - Frequently blocked by Google anti-bot measures
  - Rate-limited to ~2 req/sec even with Tor
  - SemanticScholar and OpenAlex provide better programmatic access
- **Migration:** Remove `GoogleScholar` from `apis` list in `scilex.config.yml`
- **Import Check:** ✅ Removed from collector registry and `__init__.py`

---

## Deprecated Scripts

### 1. Legacy PapersWithCode Collector (`src/getLPWC_collect.py`)
- **Reason:** Replaced by CSV-based HuggingFace enrichment (`src/enrich_with_hf.py`)
- **Size:** ~18KB
- **Last Modified:** 2026-01-16
- **Replacement:** `src/enrich_with_hf.py` (CSV-based enrichment)
- **Import Check:** ✅ No active imports of `getLPWC_collect`
- **Key Difference:** Old script modified Zotero directly; new script enriches CSV before export

### 2. Keyword Optimizer (`src/optimize_keywords.py`)
- **Reason:** Experimental tool, not part of main pipeline
- **Size:** ~7KB
- **Last Modified:** 2024-11-08
- **Import Check:** ✅ No active imports of `optimize_keywords`

---

## Verification Results

All grep checks performed on 2026-01-22:

```bash
# All commands returned NO OUTPUT (confirmed safe to remove)
grep -r "from src.PWC" src --include="*.py"
grep -r "from src.tagging" src --include="*.py"
grep -r "from src.orcid" src --include="*.py"
grep -r "from src.doi" src --include="*.py"
grep -r "from src.text_analysis" src --include="*.py"
grep -r "from src.annotation_agreement" src --include="*.py"
grep -r "getLPWC_collect" src --include="*.py"
grep -r "optimize_keywords" src --include="*.py"
```

**Result:** ✅ Zero active imports found - safe to proceed with deletion

**PubMedCentral Collector Deprecation (2026-01-22):**
```bash
# Note: PubMedCentral collector is still imported but deprecated
# Kept in codebase for backward compatibility during migration period
# Will be fully removed after users migrate to PubMed collector
grep -r "PubMedCentral_collector" src --include="*.py"
```

**Status:** ⚠️ Soft deprecation - users should migrate to `PubMed` collector
**Migration Period:** 30 days minimum before full removal

---

## Backup Strategy

1. **Git History:** All code preserved in git history (commit hash before deletion)
2. **Local Backup:** Code moved to `.deprecated/` before deletion
3. **Recovery:** Can restore from git history or `.deprecated/` backup

---

## Removal Plan

**Phase 1: Backup** (Current)
- ✅ Create `.deprecated/` directory structure
- ✅ Document all deprecated code
- ✅ Verify no active imports

**Phase 2: Move to Backup** (Next)
- Move deprecated modules to `.deprecated/modules/`
- Move deprecated scripts to `.deprecated/scripts/`
- Create git commit for backup

**Phase 3: Removal** (Final)
- Delete deprecated code from `src/`
- Update documentation (CLAUDE.md, README)
- Clean up config file examples

---

## Notes

- **Review Period:** Keep backups for 30 days minimum
- **Git Recovery:** All code can be recovered from git history before this cleanup
- **Documentation:** Update CLAUDE.md to remove all references to deprecated code
- **Testing:** Run full test suite after removal to confirm no breakage

---

## Contact

If you need to restore any of this code, check:
1. Git history (pre-cleanup commits)
2. `.deprecated/` directory backups
3. Project documentation for replacement functionality
