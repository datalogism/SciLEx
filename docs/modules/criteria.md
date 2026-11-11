# Eligibility criteria

<img src="../_static/modules/criteria.png" alt="Eligibility criteria module" height="80">

A systematic review states its criteria as a table: for each criterion (C1 publication
period, C2 coherence, C3 language…) an **exclusion criterion** (EC), an **inclusion
criterion** (IC) and its **exceptions**. In SciLEx each criterion is also a **rule**
checked on every paper. The step sits between ② Collect and ③ Screen and opens once the
review has papers.

| Sub-module | What it does |
|---|---|
| <a href="#test"><img src="../_static/modules/sub/criteria-test.png" height="30" alt="Test"></a> | See which papers a criterion would exclude, and why |
| <a href="#apply"><img src="../_static/modules/sub/criteria-apply.png" height="30" alt="Apply"></a> | Tag the excluded papers, re-evaluate on each run |
| <a href="#exceptions"><img src="../_static/modules/sub/criteria-exceptions.png" height="30" alt="Exceptions"></a> | Keep papers a criterion would exclude |

## The criteria

The defaults follow a common SLR table and the review's `scilex.yml`:

| Id | Criterion | Rule | Default |
|---|---|---|---|
| C1 | Publication period | year outside the `scilex.yml` years (option: exclude papers without a year) | on, Dataset papers kept |
| C2 | Coherence | no term of a keyword group in the title or abstract | on |
| C3 | Language | not in English | on |
| C4 | Access | not freely accessible (option: also when access is unknown) | off — enable after Crossref |
| C5 | Publication process | not peer-reviewed (preprints, reports, theses…) | off |
| C6 | Referenceability | no DOI | on |
| C7 | Duplicates | a more recent version exists | on |
| C8 | Quality | fails a quality filter of `scilex.yml` | on when quality filters are set |

**Add a criterion** adds a custom rule (title or abstract matching a pattern) or another
instance of a kind above. Each row has its EC, IC and exception texts, an on/off switch
and its parameters. **Save** writes `criteria.yml` in the review folder; **Table for the
paper** gives the criteria table in Markdown, ready for the methods section.

## Test

**Test** on a criterion lists the papers it would exclude with the cause, and those an
exception keeps, without writing anything. The paper notice of
[Explore](explore.md#paper-notice) and [③ Screen](screen.md) shows each criterion's
verdict on one paper.

## Apply

**Apply the criteria** tags each excluded paper `DELETED_BY:filter:<id> <cause>`: the
paper stays in the corpus, leaves the analyses, counts and charts, and the tag is
shared with the team through Zotero. Applying again re-evaluates: a paper that passes
now loses its tag. The [PRISMA flow](overview.md#prisma-flow) shows the count of each
criterion.

## Exceptions

- a person tags a paper `KEEP:<id>` (e.g. `KEEP:C1` for a dataset paper published
  before the period but still relevant), from the notice in one click or in Zotero;
- a criterion can spare some [paper types](enrich.md#paper-types) automatically (C1
  keeps Dataset papers by default);
- papers included in ③ Screen are never excluded.
