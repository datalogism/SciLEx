"""Knowledge graph of a review, built with the scilex-lpwc-ap application profile.

- :mod:`scilex.kg.profile`: the pinned copy of the profile (``ap/``) and its
  adaptation to one review;
- :mod:`scilex.kg.bib2json`: BibLaTeX -> the generic JSON the mapping reads;
- :mod:`scilex.kg.build`: the pipeline (RML with morph-kgc, SPARQL UPDATE with
  pyoxigraph, SHACL validation with pyshacl);
- :mod:`scilex.kg.sync_profile`: maintainer tool refreshing ``ap/`` from Codeberg.
"""
