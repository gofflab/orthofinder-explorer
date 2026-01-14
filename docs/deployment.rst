Deployment (Docker)
===================

This deployment flow uses Docker Compose to run the Flask app behind Gunicorn
and Nginx, with a one-off ingest service for loading Orthofinder datasets.

Container layout
----------------

Services:

- ``web``: Builds the app image and runs Gunicorn on port 8000.
- ``nginx``: Reverse proxy listening on host port 8080 and forwarding to
  ``web:8000``.
- ``ingest``: One-off job (enabled via the ``ingest`` profile) that runs
  ``scripts/ingest_orthofinder.py`` inside the app image.

Volumes:

- ``orthofinder-data``: Persistent SQLite database at
  ``/data/orthofinder_new.db``.
- ``static-assets``: Shared static assets directory at ``/app/app/static`` so
  the ingest job can update ``species_colors.json`` for the running web app.

Build and run
-------------

Build the images and start the web stack:

.. code-block:: bash

   docker compose up --build

The app is available at ``http://localhost:8080``.

Ingest data
-----------

Mount your Orthofinder results directory into the container at ``/input`` and
run the ingest service:

.. code-block:: bash

   docker compose --profile ingest run --rm \
     -v /path/to/Results_Feb21:/input:ro \
     ingest --config /config/orthofinder_ingest.docker.json

The ingest config uses container paths, so ``input_dir`` should be set to the
directory under ``/input`` that contains the Orthofinder results. Update
``config/orthofinder_ingest.docker.json`` before running an ingest.
You only need to edit the Docker ingest config when you want to change
non-default settings like ``mode``, ``forced_clades``, or ``db_path``. The helper
script overrides ``input_dir`` and ``dataset_name`` at runtime.

To restart the web container after a rebuild or ingest:

.. code-block:: bash

   docker compose restart web
