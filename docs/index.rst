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

- ``scripts/ingest_orthofinder.py``: Ingestion CLI.
- ``config/orthofinder_ingest.example.json``: Example ingest config.
- ``app/``: Flask app, templates, and static assets.
- ``instance/``: SQLite databases.
- ``data/``: Orthofinder outputs.

Contents
--------

.. toctree::
   :maxdepth: 2

   ingest
   data-layout
   database
   app
   troubleshooting
   development
