"""Comparative-genomics analyses computed on top of the OrthoFinder database.

The modules in this package are deliberately free of Flask imports so they can
be unit tested against an in-memory SQLite session:

``newick``
    Minimal Newick parser and species-tree helpers.
``matrix``
    Orthogroup x species gene-count matrix (the substrate for every analysis).
``species_stats``
    Per-species summaries, conservation profiles, and notable orthogroups.
``phylostrata``
    Gene-age (phylostratigraphy) assignment along a species' lineage.
``compare``
    Pairwise species comparison (expansions, contractions, orthology classes).
``annotations``
    Protein, transcript, and protein-domain annotation statistics.
``store``
    Small TTL cache that the Flask routes use to avoid recomputing the above.
"""
