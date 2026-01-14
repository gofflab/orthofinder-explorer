Database
========

The app uses a SQLite database created by the ingestion script.

Selecting the database
----------------------

The Flask app reads the DB path from ``ORTHOFINDER_DB_PATH``:

.. code-block:: bash

   export ORTHOFINDER_DB_PATH=instance/orthofinder_new.db

If not set, the app defaults to ``instance/orthofinder_new.db``.

Tables (high level)
-------------------

- ``orthogroups``: Orthogroup ID and optional gene tree.
- ``genes``: Gene IDs linked to orthogroups and species.
- ``sequences``: Protein sequences keyed by gene ID.
- ``species``: Species IDs and names.
- ``gene_key_lookup``: Optional mapping for Orthofinder IDs.
- ``ingest_runs``: Metadata about each ingestion run.

Ingestion metadata
------------------

Each run adds an ``ingest_runs`` row with:

- Dataset name and input directory
- Counts of loaded records
- JSON config used to generate the DB
