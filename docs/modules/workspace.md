# Workspace

<img src="../_static/modules/workspace.png" alt="Workspace module" height="80">

The workspace is everything around a review: the list of reviews, your identity
(ORCID iD), the API keys shared by all reviews, and the jobs running in the
background. It is the home page of the desktop app.

| Sub-module | What it does |
|---|---|
| <a href="#reviews"><img src="../_static/modules/sub/workspace-reviews.png" height="30" alt="Reviews"></a> | Create, open, rename and forget reviews |
| <a href="#orcid-profile"><img src="../_static/modules/sub/workspace-profile.png" height="30" alt="ORCID profile"></a> | Your ORCID iD, required before anything else |
| <a href="#api-keys"><img src="../_static/modules/sub/workspace-keys.png" height="30" alt="API keys"></a> | Global keys, per-review overrides, Zotero key |
| <a href="#running-jobs"><img src="../_static/modules/sub/workspace-jobs.png" height="30" alt="Running jobs"></a> | What runs now, and what waits for what |

## Reviews

A **review** is a folder that contains a `scilex.yml`. The app keeps the list of the
reviews it knows in `gui_reviews.yml` (user configuration folder); the command line
works on the same folders, so you can switch between the app and `scilex-*` commands
at any time.

**New review** asks for a name, an optional folder and a starting point. Without a
folder, the review goes to `~/SciLEx/<name>`; a relative folder such as `Test` also
starts in `~/SciLEx` (an absolute path is used as is). A Zotero group is *not* asked
here: it is chosen later on the review's [Zotero group](zotero.md#zotero-group) page.

- **From scratch**: a blank `scilex.yml`, or one of the templates
  (`computer-science`, `machine-learning`, `bioinformatics`, `clinical-medicine`,
  `social-sciences`); then collect in [② Collect](collect.md).
- **From Zotero** (needs the Zotero key in the global API keys; the dialog says when
  it is missing): click **Load**, choose a library (yours, or a group the key can
  read), then the **whole library** or a collection, with or without its
  **sub-collections**. Choose **One review** (the collections a paper belongs to are
  kept in its `zotero_collections` column and become sub-corpora) or **One review per
  collection** (one sub-folder each). The papers become the review's
  `aggregated_results.csv`, so every step works at once. Keywords come from the
  `Collect_KW1:…`/`Collect_KW2:…` tags SciLEx writes when pushing, years from the paper
  dates, and the annotation grid from the `DIMENSION:value` tags. An optional
  configuration file wins over these deductions. The library is remembered in
  `zotero_source.yml`.
- **From a knowledge graph**: load a SciLEx knowledge graph (`.ttl`, written by
  [⑧ Export](export.md#knowledge-graph)), the richest record of a review: bibliographic
  data, authors, venues, coding, citation links and sub-corpora. The review is created
  as from Zotero, and the graph is copied into its `kg/` folder. Any key or token
  found in a URL of the graph is removed on import.

**Open a folder** adds a folder that already holds a `scilex.yml`. Each review card
shows whether it has results, whether a job is running on it, and whether its
`scilex.yml` is invalid (then only ① Configure and API keys open, to repair it).
**Remove** forgets a review without deleting its folder.

**Results folder.** The folder holding a review's results is recorded in
`review_state.yml` and kept when you rename the review, so results never move or get
lost. A review opened for the first time whose `output/<name>` has no results adopts
a sibling folder that does when it carries a name the review had. The command line
still uses `output/<name>`.

## ORCID profile

The app asks for your **ORCID iD** before anything else and stays locked without
one. It is checked locally (format and check digit); **Check on orcid.org** shows the
name registered for it. It is stored in `user.yml` (user configuration folder), shown
on the home page (click it to change it), recorded as the agent of every event of a
review's [history](overview.md#history), used as your annotator identifier in
[workflow tags](zotero.md#tag-conventions), and written as the creator of the knowledge
graphs you export. `scilex-build-kg` reads the same file, or takes `--orcid`.

## API keys

**Global keys** (**API keys** on the home page) are the default of every review,
stored in one file whose path is shown (`$SCILEX_KEYS`, else
`~/.config/scilex/keys.yml`, readable by you only). If an older
`scilex/api.config.yml` holds keys this file lacks, the home page offers to
**Import** them; values already set are kept.

- **Zotero**: one *global access key* for the whole app. Create it on zotero.org
  (Settings → Security → Applications) with access to the groups of your reviews.
  The user id is detected from the key; each review then works in its own group.
- **Collection APIs**: Semantic Scholar, OpenAlex, IEEE, Elsevier, Springer, PubMed…
  Add several keys to a list for rotation; **Test** checks a key.
- **E-mails**: Unpaywall and Crossref (the faster "polite" Crossref service).
- **Advanced**: rate limits per API.

**A review's keys** (its **API keys** step) show the same form with the global value
under each field. Leave a field empty to use the global value; fill it to override it
for this review only. Only overridden fields are written, to `review_keys.yml` in the
review folder (keep it out of shared folders and version control).

An environment variable `SCILEX_<API>_<FIELD>` takes precedence over both files; a
warning says so. See the [configuration reference](../reference/configuration.md#keysyml).

## Running jobs

Every costly action (collection, aggregation, extension, enrichment, analysis,
export, Zotero write) runs as a background **job**. The **running jobs** button, on
the home page and in every review, shows their count; it opens their list with the
review, what each job does, its progress and message. A job can be opened (its review)
or cancelled; finished jobs stay listed a few minutes with their outcome.

Several jobs run at the same time; a job waits only for one that uses the same thing:

| Job | Runs alongside | Waits for |
|---|---|---|
| Collection (② Collect, ⑤ Extend → New collect) | anything on other reviews except a collection; analyses and exports of its review | another collection (source APIs and VPN are shared), jobs rewriting its review's papers |
| Aggregation, Extend modes, Consolidate, BibTeX / Zotero import, Zotero sync, Snowball adding papers | everything on other reviews; readers of this review | jobs writing this review's papers |
| Enrichers | each other, readers, other reviews | jobs rewriting the rows of this review |
| Analyses, file exports | everything | nothing |
| Writes to Zotero (annotations, tag cleaning, push) | everything else | another write to the same Zotero library |

The same action never runs twice at once on a review. Enrichers running together each
write only the cells they changed, so none erases another's results. When a button is
disabled, the line under it names the job it waits for.

**Last run chips.** Each costly action shows when it last completed, so you do not run
it again by mistake: **red** never run for this review, **green** completed in the last
30 days, **grey** completed earlier. The colour is a chip next to the button and a dot
on the tabs of ⑤ Extend, ⑥ Enrich and ⑦ Analyses; hover it for the date and the
result. Dates are kept in `gui_run_history.json` in the review folder.
