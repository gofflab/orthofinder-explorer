CephExplorer
============

This project provides two main capabilities:

- A web app to browse orthogroups, genes, and sequences.
- A repeatable ingestion workflow to turn Orthofinder outputs into a SQLite database.

Quick start
-----------

1) Ingest Orthofinder outputs (see :doc:`ingest`).
2) Run the app:

.. code-block:: bash

   export ORTHOFINDER_DB_PATH=instance/orthofinder_new.db
   python run.py

Navigate to ``http://127.0.0.1:5001`` to explore the data.

Project layout
--------------

- ``scripts/ingest_orthofinder.py``: Stage 1 ingestion CLI (OrthoFinder outputs → DB).
- ``scripts/ingest_species_annotations.py``: Stage 2 ingestion CLI (GTF, mRNA, domains → DB).
- ``config/orthofinder_ingest.example.json``: Example Stage 1 config.
- ``config/species_annotations.example.json``: Example Stage 2 config.
- ``app/``: Flask app, templates, and static assets.
- ``instance/``: SQLite databases.
- ``data/``: OrthoFinder outputs.
- ``annotations/``: Per-species GTF, mRNA FASTA, and domain prediction files.

Contents
--------

.. toctree::
   :maxdepth: 2

   adding-species
   ingest
   data-layout
   species-annotations
   database
   app
   deployment
   troubleshooting
   development
