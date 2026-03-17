Troubleshooting
===============

.. contents:: On this page
   :local:
   :depth: 2

Stage 1 — OrthoFinder ingest
-----------------------------

Missing species IDs during ingest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: ``ValueError: Missing species IDs for: SpeciesX``

**Cause**: A species column found in ``N0.tsv`` does not have a corresponding
entry in ``WorkingDirectory/SpeciesIDs.txt``.  This usually means the files
are from different OrthoFinder runs or the results directory is incomplete.

**Fix**:

- Confirm that ``input_dir`` points to the same ``Results_XXXX`` directory
  for both files.
- Re-run OrthoFinder if the results appear corrupted.

Missing gene trees
~~~~~~~~~~~~~~~~~~

**Symptom**: Many warnings like ``Warning: Gene tree not found: Gene_Trees/OG0000001_tree.txt``

**Cause**: The ``Gene_Trees`` directory is missing, empty, or OrthoFinder did
not complete the tree-inference step.

**Fix**:

- Confirm ``Gene_Trees/`` exists and contains ``*_tree.txt`` files.
- If you have reconciled trees instead, set ``gene_tree_dir`` to
  ``Resolved_Gene_Trees``.
- If tree inference did not run, re-run OrthoFinder with ``-M msa`` and
  sufficient CPU/memory resources.

OrthoFinder FASTA file rejected
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: OrthoFinder exits with an error about invalid sequence characters
or file format.

**Cause**: The protein FASTA contains nucleotide sequences, stop codons
(``*``), or blank sequence entries.

**Fix**:

- Confirm the FASTA contains amino acid sequences (single-letter codes).
- Remove or replace stop codon characters (``*``) before running OrthoFinder.
- Remove any empty FASTA entries (headers with no sequence lines).

Species appear in wrong clade colour
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: A species is assigned a colour that visually groups it with the
wrong clade.

**Cause**: The automatic depth-cut algorithm chose different clade anchors than
expected, or a forced clade entry has a typo in a species name.

**Fix**:

- Use ``forced_clades`` to explicitly group species (see :ref:`orthofinder-config-reference`).
- Check that every name in ``forced_clades`` exactly matches the
  ``species_name`` in the database (query: ``SELECT species_name FROM species;``).
- Tune ``clade_min_count``, ``clade_max_count``, or ``clade_anchor_depth`` to
  shift the automatic cut point.

404 on Dpe gene links
~~~~~~~~~~~~~~~~~~~~~

**Symptom**: Clicking a gene tree node for *Doryteuthis pealeii* returns a 404.

**Cause**: Gene tree leaf labels use the ``gert_`` prefix or ``__frame__``
tokens (e.g. ``gert_Dpe_XYZ__1__``) that do not match the normalised gene IDs
stored in the database (e.g. ``Dpe_XYZ_[1]_``).

**Fix**:

- Re-ingest with ``normalize_dpe_tree_labels: true`` (the default).
- If your assembly does not use this naming scheme, set
  ``normalize_dpe_tree_labels: false`` so raw IDs are used throughout.

Stage 2 — Species annotation ingest
-------------------------------------

Species name not found
~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: ``ValueError: Species 'Homo_sapiens' not found in database.``

**Cause**: The species name used as a key in ``species_annotations.json`` does
not match any ``species_name`` value in the ``species`` table.  Common causes:

- Stage 1 has not been run yet (``species`` table is empty).
- The name in the config has a typo, different capitalisation, or a different
  date suffix from the one OrthoFinder stored.
- You ran Stage 1 with a different protein FASTA filename than expected.

**Fix**:

1. Query the database for the exact names stored::

       sqlite3 instance/orthofinder_new.db "SELECT species_id, species_name FROM species;"

2. Update ``species_annotations.json`` keys to match exactly.

High fraction of unmatched transcripts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: After GTF ingestion the log reports a large number of transcripts
with no gene match, or the verification query::

    SELECT species_name, COUNT(*) AS unmatched
    FROM transcripts t JOIN species s USING (species_id)
    WHERE t.gene_id IS NULL
    GROUP BY s.species_name;

returns most or all transcripts.

**Cause**: The ``gene_id`` attribute values in the GTF do not match the gene
IDs stored in the ``genes`` table.  Common causes:

- The GTF and the protein FASTA used for OrthoFinder came from different
  annotation versions.
- The protein FASTA headers use transcript IDs rather than gene IDs (common
  for Trinity assemblies) while the GTF uses gene IDs.
- Version suffixes differ: the GTF has ``ENSG00000001.10`` while the gene
  table has ``ENSG00000001``.

**Fix**:

- Confirm the GTF and protein FASTA derive from the same annotation release.
- If the protein FASTA headers are transcript IDs (e.g. ``ENST00000001``
  rather than ``ENSG00000001``), switch ``gtf_gene_id`` matching: use the GTF
  ``transcript_id`` attribute as the key and match it against ``gene_id``
  values in the database.  (An ``id_mapping`` config key is planned for a
  future release to handle this systematically — see :doc:`species-annotations`.)
- Check whether version stripping helps: the ingestor already tries
  ``ENSG00000001.10`` → ``ENSG00000001``, but only for dot (``.``) and pipe
  (``|``) delimiters.

GTF file not found
~~~~~~~~~~~~~~~~~~

**Symptom**: ``Warning: GTF file not found, skipping: annotations/Homo_sapiens/Homo_sapiens.gtf``

**Cause**: The path in the config does not exist on disk.

**Fix**:

- Check that the path is correct (relative to the working directory from which
  the script is invoked, not relative to ``input_dir``).
- If using Docker, confirm the annotation directory is mounted into the
  container.

InterProScan TSV not parsing correctly
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: Domain rows are loaded but most fields are empty, or the row count
is lower than expected.

**Cause**: The file may not be in the standard 15-column TSV format, or it was
produced by an older InterProScan version with a different column layout.

**Fix**:

- Confirm the file was generated with ``--output-format TSV``.
- Check that the file has 9–15 tab-separated columns per data row (comment
  lines starting with ``#`` are skipped).
- Re-run InterProScan with the current version (≥ 5.x).

Existing database tables not updated after re-running Stage 2
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: After editing annotation files and re-running
``ingest_species_annotations.py``, old data is still visible.

**Cause**: The script defaults to ``mode: append``, which does not remove
existing rows.

**Fix**: Run with ``--mode rebuild`` or set ``"mode": "rebuild"`` in the config
to delete and reload all annotation rows for the processed species.

General database issues
-----------------------

Database file locked
~~~~~~~~~~~~~~~~~~~~

**Symptom**: ``sqlite3.OperationalError: database is locked``

**Cause**: Another process (e.g. the running web app or a previous ingest job)
has the database open with a write lock.

**Fix**:

- Stop the Flask/Gunicorn process before running the ingest in ``rebuild``
  mode.
- In Docker, run::

      docker compose stop web
      docker compose --profile ingest run --rm ingest --config ...
      docker compose start web

Database schema out of date
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: ``sqlalchemy.exc.OperationalError: table X has no column named Y``

**Cause**: The database was created by an older version of the code that did
not include a column added in a later release (e.g. ``transcripts.mrna_sequence``).

**Fix**: The annotations ingest script automatically adds missing columns to
existing databases via ``ensure_column()``.  Run
``ingest_species_annotations.py`` once (even with ``--skip-features
--skip-mrna``) to trigger the migration.  For the core Stage 1 tables, a full
``rebuild`` is required.

Checking row counts
~~~~~~~~~~~~~~~~~~~

A quick sanity check after any ingest::

    sqlite3 instance/orthofinder_new.db "
        SELECT 'orthogroups',   COUNT(*) FROM orthogroups
        UNION ALL
        SELECT 'genes',         COUNT(*) FROM genes
        UNION ALL
        SELECT 'sequences',     COUNT(*) FROM sequences
        UNION ALL
        SELECT 'species',       COUNT(*) FROM species
        UNION ALL
        SELECT 'transcripts',   COUNT(*) FROM transcripts
        UNION ALL
        SELECT 'features',      COUNT(*) FROM transcript_features
        UNION ALL
        SELECT 'domains',       COUNT(*) FROM protein_domains;
    "
