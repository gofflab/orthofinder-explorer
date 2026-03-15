Ingest Orthofinder Results
==========================

The script ``scripts/ingest_orthofinder.py`` reads OrthoFinder output files and
builds (or appends to) the SQLite database used by the web app.  This page is
the complete reference for all config keys and CLI flags.

For a step-by-step walkthrough of adding or updating species, see
:doc:`adding-species`.

.. contents:: On this page
   :local:
   :depth: 2

Quick start
-----------

Local (non-Docker)::

    python scripts/ingest_orthofinder.py --config config/my_run.json

Docker (via helper script)::

    bash scripts/ingest_docker.sh /path/to/OrthoFinder/Results_Feb21 Results_Feb21

Docker (manual)::

    docker compose --profile ingest run --rm \
        -v /path/to/Results_Feb21:/input:ro \
        ingest --config /config/orthofinder_ingest.docker.json

Modes
-----

``rebuild`` (recommended for any new OrthoFinder run)
    Drops all existing tables (``orthogroups``, ``genes``, ``sequences``,
    ``species``, ``gene_key_lookup``, ``ingest_runs``) and recreates them.
    All previously ingested data is lost.  Use this mode whenever you re-run
    OrthoFinder, since every run reassigns species and gene IDs.

``append``
    Creates tables if missing and inserts new rows alongside any existing data.
    Use only when loading a second, fully independent dataset (e.g. a separate
    clade analysis) into the same database file.  Do **not** use ``append`` for
    a new OrthoFinder run that covers the same species — duplicate or
    conflicting gene IDs will result.

.. _orthofinder-config-reference:

Config reference
----------------

Config files are JSON objects.  All keys are optional except ``input_dir``.
Keys set in the JSON file are overridden by the corresponding CLI flag when both
are provided.

All *relative paths* inside the config are resolved relative to ``input_dir``
(for OrthoFinder output files) or relative to the working directory from which
the script is invoked (for output paths such as ``db_path`` and
``species_colors_output``).

Core settings
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 28 12 60

   * - Key
     - Type / Default
     - Description
   * - ``input_dir``
     - string / **required**
     - Absolute or relative path to the OrthoFinder ``Results_XXXX`` directory.
       All OrthoFinder output paths below are resolved relative to this
       directory.
       *CLI*: ``--input-dir``
   * - ``db_path``
     - string / ``instance/orthofinder_new.db``
     - Path to the SQLite database file.  The parent directory is created
       automatically.
       *CLI*: ``--db-path``
   * - ``mode``
     - ``"rebuild"`` or ``"append"`` / ``"rebuild"``
     - Ingestion mode.  See `Modes`_ above.
       *CLI*: ``--mode``
   * - ``dataset_name``
     - string / basename of ``input_dir``
     - Human-readable name stored in the ``ingest_runs`` audit table.  Defaults
       to the last component of ``input_dir`` if not set.
       *CLI*: ``--dataset-name``

OrthoFinder output file paths
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All paths are relative to ``input_dir``.

.. list-table::
   :header-rows: 1
   :widths: 35 35 30

   * - Key
     - Default
     - Description
   * - ``orthogroups_file``
     - ``Phylogenetic_Hierarchical_Orthogroups/N0.tsv``
     - Hierarchical orthogroup assignments.  Wide-format TSV with one column
       per species.  The ingestor melts this to one row per (orthogroup,
       species, gene) triple.
       *CLI*: ``--orthogroups-file``
   * - ``species_file``
     - ``WorkingDirectory/SpeciesIDs.txt``
     - Maps OrthoFinder's internal numeric species index to species names.
       Format: ``N: SpeciesName.fa`` (one per line).
       *CLI*: ``--species-file``
   * - ``sequence_ids_file``
     - ``WorkingDirectory/SequenceIDs.txt``
     - Maps OrthoFinder's ``{species_idx}_{gene_idx}`` tokens back to the
       original gene/protein IDs from the input FASTA headers.
       *CLI*: ``--sequence-ids-file``
   * - ``protein_fasta_pattern``
     - ``WorkingDirectory/Species{species_id}.fa``
     - Pattern for per-species re-indexed protein FASTAs written by OrthoFinder.
       The ``{species_id}`` placeholder is replaced with the numeric species
       index.
       *CLI*: ``--protein-fasta-pattern``
   * - ``species_tree_file``
     - ``Species_Tree/SpeciesTree_rooted.txt``
     - Rooted species phylogeny in Newick format.  Used to compute the
       clade-anchored species colour map.
       *CLI*: ``--species-tree-file``
   * - ``gene_tree_dir``
     - ``Gene_Trees``
     - Directory containing per-orthogroup gene trees named
       ``{orthogroup_id}_tree.txt``.  To use resolved (reconciled) trees,
       set this to ``Resolved_Gene_Trees``.
       *CLI*: ``--gene-tree-dir``

Output paths
~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 35 30 35

   * - Key
     - Default
     - Description
   * - ``species_colors_output``
     - ``app/static/species_colors.json``
     - Path where the species colour map JSON is written.  In Docker
       deployments this should point to a path on the shared data volume (e.g.
       ``/data/species_colors.json``) so the web app can serve it.
       *CLI*: ``--species-colors-output``

Species colour tuning
~~~~~~~~~~~~~~~~~~~~~~

The ingestor computes a colour for each species based on its position in the
species tree.  Clades are selected as colour-anchor groups; species within each
clade are shaded from light to dark according to their distance from the clade
root.

.. list-table::
   :header-rows: 1
   :widths: 30 12 58

   * - Key
     - Default
     - Description
   * - ``forced_clades``
     - ``{}``
     - JSON object mapping human-readable clade labels to lists of species
       names.  Species in a forced clade are always coloured together using a
       single palette entry, regardless of the automatic depth-cut algorithm.
       Species names must exactly match the values in ``SpeciesIDs.txt``
       (see :doc:`adding-species`).

       .. code-block:: json

           "forced_clades": {
             "Cephalopods": [
               "Doryteuthis_pealeii_20250213",
               "Euprymna_berryi",
               "Octopus_bimaculoides"
             ],
             "Vertebrates": [
               "Danio_rerio",
               "Homo_sapiens",
               "Mus_musculus"
             ]
           }

   * - ``clade_min_count``
     - ``5``
     - Minimum number of automatic clade anchors (after applying forced
       clades).  The algorithm splits the deepest clade until this number is
       reached.
       *CLI*: ``--clade-min-count``
   * - ``clade_max_count``
     - ``8``
     - Maximum number of automatic clade anchors.  If the depth cut produces
       more, the smallest clades are merged into an "Other" bucket.
       *CLI*: ``--clade-max-count``
   * - ``clade_target_count``
     - ``null``
     - Convenience: set both ``clade_min_count`` and ``clade_max_count`` to
       the same value, forcing exactly this many anchors.
       *CLI*: ``--clade-target-count``
   * - ``clade_anchor_depth``
     - ``null``
     - Fix the depth (edge count from the root) at which clades are cut.
       When ``null``, the algorithm increases depth from 1 until
       ``clade_min_count`` anchors are found.
       *CLI*: ``--clade-anchor-depth``
   * - ``clade_distance_metric``
     - ``"topology"``
     - Distance metric used for within-clade shading.
       ``"topology"`` counts tree edges; ``"branch"`` uses summed branch
       lengths.
       *CLI*: ``--clade-distance-metric``
   * - ``clade_color_steps``
     - ``5``
     - Number of discrete lightness steps from the darkest to lightest shade
       within each clade.
       *CLI*: ``--clade-color-steps``

Species-specific normalisation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 12 58

   * - Key
     - Default
     - Description
   * - ``normalize_dpe_tree_labels``
     - ``true``
     - When ``true``, gene tree leaf labels for *Doryteuthis pealeii* are
       rewritten to match database gene IDs.  Specifically, the ``gert_``
       prefix is stripped and ``__frame__`` tokens are converted to
       ``_[frame]_`` notation.  Disable with
       ``--no-normalize-dpe-tree-labels`` or set to ``false`` if your Dpe
       assembly does not use this convention.
       *CLI*: ``--no-normalize-dpe-tree-labels`` (flag inverts the default)

All CLI flags
-------------

.. code-block:: text

    usage: ingest_orthofinder.py [-h] [--config CONFIG]
                                  [--input-dir INPUT_DIR]
                                  [--db-path DB_PATH]
                                  [--mode {rebuild,append}]
                                  [--orthogroups-file ORTHOGROUPS_FILE]
                                  [--species-file SPECIES_FILE]
                                  [--sequence-ids-file SEQUENCE_IDS_FILE]
                                  [--protein-fasta-pattern PROTEIN_FASTA_PATTERN]
                                  [--species-tree-file SPECIES_TREE_FILE]
                                  [--gene-tree-dir GENE_TREE_DIR]
                                  [--species-colors-output SPECIES_COLORS_OUTPUT]
                                  [--clade-target-count CLADE_TARGET_COUNT]
                                  [--clade-min-count CLADE_MIN_COUNT]
                                  [--clade-max-count CLADE_MAX_COUNT]
                                  [--clade-anchor-depth CLADE_ANCHOR_DEPTH]
                                  [--clade-distance-metric {topology,branch}]
                                  [--clade-color-steps CLADE_COLOR_STEPS]
                                  [--dataset-name DATASET_NAME]
                                  [--no-normalize-dpe-tree-labels]
                                  [--verbose]

Annotated example config
------------------------

The following is a fully annotated example showing every supported key.  Copy,
rename, and edit for your run.

.. code-block:: json

    {
      "input_dir":    "data/OrthoFinder/Results_Feb21",
      "db_path":      "instance/orthofinder_new.db",
      "mode":         "rebuild",
      "dataset_name": "Results_Feb21",

      "orthogroups_file":       "Phylogenetic_Hierarchical_Orthogroups/N0.tsv",
      "species_file":           "WorkingDirectory/SpeciesIDs.txt",
      "sequence_ids_file":      "WorkingDirectory/SequenceIDs.txt",
      "protein_fasta_pattern":  "WorkingDirectory/Species{species_id}.fa",
      "species_tree_file":      "Species_Tree/SpeciesTree_rooted.txt",
      "gene_tree_dir":          "Gene_Trees",

      "species_colors_output":  "app/static/species_colors.json",

      "clade_min_count":        5,
      "clade_max_count":        8,
      "clade_distance_metric":  "topology",
      "clade_color_steps":      5,

      "forced_clades": {
        "Cephalopods": [
          "Doryteuthis_pealeii_20250213",
          "Doryteuthis_pealeii_gert",
          "Euprymna_berryi",
          "Octopus_bimaculoides",
          "Octopus_chierchiae",
          "Octopus_sinensis"
        ],
        "Vertebrates": [
          "Danio_rerio",
          "Homo_sapiens",
          "Mus_musculus",
          "Oncorhynchus_tshawytscha",
          "Salmo_salar"
        ]
      },

      "normalize_dpe_tree_labels": true
    }

Docker config notes
-------------------

The file ``config/orthofinder_ingest.docker.json`` is used when running the
ingest via Docker.  Key differences from the local config:

* ``input_dir`` uses the container path ``/input`` (the host results directory
  is bind-mounted there at runtime).
* ``db_path`` uses the container path on the data volume (e.g.
  ``/data/orthofinder_new.db``).
* ``species_colors_output`` likewise points to the data volume path
  (``/data/species_colors.json``).

The helper script ``scripts/ingest_docker.sh`` overrides ``input_dir`` and
``dataset_name`` at runtime, so those values in the Docker config file are
ignored when using the script.

Audit log
---------

Each completed ingest appends one row to the ``ingest_runs`` table with:

* ``dataset_name`` — the value from config or the ``input_dir`` basename.
* ``input_dir`` — fully resolved path.
* ``created_at`` — UTC timestamp.
* ``orthogroups_count``, ``genes_count``, ``sequences_count``,
  ``gene_trees_count`` — record counts for quick sanity checks.
* ``config_json`` — full config dict serialised as JSON (useful for
  reproducing a run).

Query it directly::

    sqlite3 instance/orthofinder_new.db \
        "SELECT id, dataset_name, genes_count, sequences_count, created_at
         FROM ingest_runs ORDER BY id DESC LIMIT 10;"
