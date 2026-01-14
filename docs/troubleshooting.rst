Troubleshooting
===============

404 on Dpe gene links
---------------------

Cause: Tree labels may use ``gert_`` and ``__frame__`` tokens that do not match
DB gene IDs (``_[frame2]_``).

Fix:

- Re-ingest with normalization enabled (default).
- Or set ``normalize_dpe_tree_labels: false`` and use raw IDs in the DB and UI.

Missing species IDs during ingest
---------------------------------

Cause: Species in ``N0.tsv`` do not appear in ``WorkingDirectory/SpeciesIDs.txt``.

Fix:

- Confirm the Orthofinder run outputs are complete and match each other.
- Check that ``species_file`` points to the correct results directory.

Missing gene trees
------------------

Cause: The expected ``Gene_Trees`` directory is missing or incomplete.

Fix:

- Confirm the directory exists in the results folder.
- Override ``gene_tree_dir`` to ``Resolved_Gene_Trees`` if that is what you have.
