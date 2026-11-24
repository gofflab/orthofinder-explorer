Development
===========

Local environment
-----------------

This section covers local-only development outside Docker. For deployment, use
the Docker + Gunicorn workflow in :doc:`deployment`.

Use the existing Python environment for Flask and the ingestion script. The repo
includes ``environment.yml`` if you want to recreate the environment locally.

Run the app
-----------

.. code-block:: bash

   export ORTHOFINDER_DB_PATH=instance/orthofinder_new.db
   python run.py

``run.py`` is intended for local development (Flask's built-in server). Production
deployments should use the Gunicorn entrypoint via Docker.

Demo database
-------------

The real database is built from OrthoFinder output and is not part of the
repository.  To work on the UI without it, build a small synthetic database
with the same schema and species names:

.. code-block:: bash

   python scripts/build_demo_db.py --db instance/demo.db
   ORTHOFINDER_DB_PATH=$PWD/instance/demo.db python run.py

The demo data is random.  A few gene-family expansions are planted on purpose
(for example a cephalopod protocadherin family) so the species pages have
recognisable signals to display.  Four species also receive transcript and
domain annotations.

Front-end libraries (Bootstrap, d3, phylotree) are loaded from
``app/static/node_modules``; run ``npm install`` in ``app/static`` once.

Tests
-----

.. code-block:: bash

   python -m pytest

``tests/test_species_analysis.py`` covers the comparative analyses on a small
hand-built dataset.  ``tests/test_species_routes.py`` exercises the species
pages and their JSON API against a demo database; it is skipped when Flask is
not installed.

Build and serve docs
--------------------

.. code-block:: bash

   ./scripts/docs.sh build

.. code-block:: bash

   ./scripts/docs.sh serve
