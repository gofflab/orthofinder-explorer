Ingest Orthofinder Results
==========================

The ingestion CLI reads Orthofinder outputs and builds a SQLite database used by the web app.

Run with a config file
----------------------

.. code-block:: bash

   python scripts/ingest_orthofinder.py --config config/orthofinder_ingest.example.json

Key CLI flags
-------------

- ``--input-dir``: Path to Orthofinder results (required if not in config).
- ``--db-path``: SQLite database file (default: ``instance/orthofinder_new.db``).
- ``--mode``: ``rebuild`` (drop and recreate) or ``append``.
- ``--dataset-name``: Name stored in ``ingest_runs``.
- ``--no-normalize-dpe-tree-labels``: Disable Dpe tree label normalization.

Config fields
-------------

All config fields are optional except ``input_dir``.

.. code-block:: json

   {
     "input_dir": "data/Results_Feb21",
     "db_path": "instance/orthofinder_new.db",
     "mode": "rebuild",
     "orthogroups_file": "Phylogenetic_Hierarchical_Orthogroups/N0.tsv",
     "species_file": "WorkingDirectory/SpeciesIDs.txt",
  "sequence_ids_file": "WorkingDirectory/SequenceIDs.txt",
  "protein_fasta_pattern": "WorkingDirectory/Species{species_id}.fa",
  "species_tree_file": "Species_Tree/SpeciesTree_rooted.txt",
  "gene_tree_dir": "Gene_Trees",
  "species_colors_output": "app/static/species_colors.json",
  "clade_min_count": 5,
  "clade_max_count": 8,
  "clade_distance_metric": "topology",
  "clade_color_steps": 5,
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
  "dataset_name": "Results_Feb21",
     "normalize_dpe_tree_labels": true
   }

Dpe ID normalization
--------------------

Some Doryteuthis tree labels include a ``gert_`` prefix and ``__frame__`` tokens,
while the database uses bracketed frames (for example ``_[frame2]_``). The
ingestor can normalize these in gene trees so links resolve correctly.

- Normalization is enabled by default.
- Disable with ``--no-normalize-dpe-tree-labels`` or set
  ``"normalize_dpe_tree_labels": false`` in the config.

Species colors
--------------

The ingestor writes a species color map JSON (default:
``app/static/species_colors.json``) based on the species tree. The UI loads this
mapping to color leaf nodes with clade-anchored hues.

Color tuning options
--------------------

Use these config keys or CLI flags to tune clade anchors and shading:

- ``clade_min_count`` / ``clade_max_count``: Bounds on anchor clades.
- ``clade_target_count``: Force a specific number of anchors.
- ``clade_anchor_depth``: Cut depth from the root (edge count).
- ``clade_distance_metric``: ``topology`` (edge count) or ``branch``.
- ``clade_color_steps``: Discrete shades within each anchor.
- ``forced_clades``: JSON object mapping labels to lists of species names.
