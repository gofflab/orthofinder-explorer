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

Build and serve docs
--------------------

.. code-block:: bash

   ./scripts/docs.sh build

.. code-block:: bash

   ./scripts/docs.sh serve
