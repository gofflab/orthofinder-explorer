Deployment (Docker)
===================

This deployment flow uses Docker Compose to run the Flask app behind Gunicorn
and Nginx, with a one-off ingest service for loading Orthofinder datasets.

Container layout
----------------

Services:

- ``web``: Builds the app image and runs Gunicorn on port 8000.
- ``nginx``: Reverse proxy listening on host ports 80/443 and forwarding to
  ``web:8000``.
- ``ingest``: One-off job (enabled via the ``ingest`` profile) that runs
  ``scripts/ingest_orthofinder.py`` inside the app image.

Volumes:

- ``orthofinder-data``: Persistent SQLite database at
  ``/data/orthofinder_new.db``. The ingest job also writes
  ``/data/species_colors.json``, which the app serves from ``/species-colors.json``
  based on ``ORTHOFINDER_SPECIES_COLORS_PATH``.

Build and run
-------------

Build the images and start the web stack:

.. code-block:: bash

   docker compose up --build

The app is available at ``https://cephexplorer.gofflab.org`` once DNS and TLS
are configured for the host.

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

Local-only note
---------------

For local development without TLS, update ``deploy/nginx.conf`` to remove the
HTTPS server block and change the Nginx ports in ``docker-compose.yml`` to use a
non-privileged port (for example ``8080:80``). You can also remove the
``/etc/letsencrypt`` mount in that case.
