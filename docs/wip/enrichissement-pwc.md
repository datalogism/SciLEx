# WIP — Enrichissement Papers with Code (ADR 0006)

## État : terminé (2026-10-28)
- [x] Lot core : `scilex/PapersWithCode/client.py`, `pipeline/enrichment_pwc.py`,
  `enrich_with_pwc.py`, appelants, `huggingface-hub` retiré (2df6f8bb)
- [x] Lot config : `enrichment.paperswithcode`, alias `huggingface` déprécié (e3ff563a)
- [x] Lot exports : BibTeX `pwcurl`, RDF, Zotero `Papers with Code:` + tag `HavePWC` (752f02bf)
- [x] Suite complète verte ; test réel sur l'API (arXiv + repli titre OK)

## Points ouverts
- Le tag Zotero de présence `HaveHF` est devenu `HavePWC`.
- Les méthodes PwC incluent des optimiseurs/couches (Adam, Dropout) → tags `ARCHI:`.
