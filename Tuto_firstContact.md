![Scilex](img/projectLogoScilex.png)

# 🚀 SciLEx Tutorial

## 0. 🔑 Obtain the API Keys You Need

\:heavy\_plus\_sign: [Create a Zotero API key](https://www.zotero.org/support/dev/web_api/v3/start)
\:heavy\_plus\_sign: Create accounts for the following APIs:

* [Semantic Scholar](https://www.semanticscholar.org/product/api/tutorial) (optional – allows a higher rate limit ⬆️, but takes time ⏳)
* [Springer](https://dev.springernature.com/) (mandatory if selected as a source 📚)
* [IEEE](https://developer.ieee.org/) (mandatory if selected as a source ⚡)
* [Elsevier](https://dev.elsevier.com/) (mandatory if selected as a source 🧪)

---

## 1. 🛠 Clone the Repository and Install Requirements

```bash
git clone https://github.com/datalogism/SciLEx.git
cd SciLEx
pip install -r requirements.txt
```

---

## 2. 📝 Create and Configure Your Files

1. **Copy the API configuration template:**

   ```bash
   cp src/api.config.yml.example src/api.config.yml
   ```

2. **Edit `src/api.config.yml` with your API credentials:**

   * **Zotero API Key**: [Create here](https://www.zotero.org/settings/keys)
   * **IEEE API Key**: [Register at IEEE Developer Portal](https://developer.ieee.org/)
   * **Elsevier API Key**: [Register at Elsevier Developer Portal](https://dev.elsevier.com/)
   * **Springer API Key**: [Register at Springer Nature Developer Portal](https://dev.springernature.com/)
   * **Semantic Scholar API Key**: Optional, [register here](https://www.semanticscholar.org/product/api/tutorial)

3. **Update your main configuration in [`src/scilex.config.yml`](src/scilex.config.yml):**

```yaml
aggregate_txt_filter: true         # Filter articles based on the given keywords 🔍
aggregate_get_citations: true      # Collect all citations during aggregation 📑
aggregate_file: '/FileAggreg.csv'  # Aggregated results will be saved here 💾
apis:                              
  - DBLP
  - Arxiv
  - OpenAlex
  - SemanticScholar
collect: true                       # Flag to enable or disable collection ✅
collect_name: graphrag              # Name for this collection 🏷
email: YOUR_MAIL                    # Email used for API requests 📧
fields:                             # Fields to search for keywords (currently all available) 🧩
  - title
  - abstract
keywords:                            # Two lists of keywords for collection 💡
  - ["RAG", "Graphrag", "LLM", "sparql", "Multi-agent", "agent", "agentic", "Langchain", "RAG", "RAGs", "rag", "rag"]
  - ["Knowledge Graph", "Knowledge Graphs", "knowledge graph", "knowledge graph"]
output_dir: output
years:
  - 2023
  - 2024
  - 2025
```

---

## 3. ▶️ Run Your Collection

Once the previous steps are complete, run the collection from the library source:

```bash
python run_collect.py
```

---

## 4. 📦 Aggregate the Collection

After collecting all papers, create the final aggregated file:

```bash
python aggregate_collect.py
```

---

## 5. 📂 View the Results

Results are saved in a dedicated directory inside `./output_dir`. Each directory is named according to the `collect_name` in your configuration:

```
output_dir/collect_name/
├── LibraryOne/           # Individual libraries 📚
├── Library.../            
├── LibraryN/             
│   ├── page0/   
│   ├── page.../   
│   └── pagen/
├── configuration_used.yml # Local copy of the configuration 📝
├── state_details.json     # Tracks the state of collection to resume if interrupted ⏯
└── aggregation_file.csv   # Aggregated results 💾
```

---

## 6. 🔄 Push Results to Zotero

If you have your Zotero API key, you can push the `aggregation_file.csv` content to a Zotero library. Note that free Zotero accounts have storage limits, so manual filtering is recommended.

```bash
python aggregate_collect.py
```

This will create a new library based on the `collect_name` defined in your configuration 🏁.
