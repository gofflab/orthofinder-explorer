Development
===========

Local environment
-----------------

Use the existing Python environment for Flask and the ingestion script. The repo
includes ``environment.yml`` if you want to recreate the environment.

Run the app
-----------

.. code-block:: bash

   export ORTHOFINDER_DB_PATH=instance/orthofinder_new.db
   python run.py

Build and serve docs
--------------------

.. code-block:: bash

   ./scripts/docs.sh build

.. code-block:: bash

   ./scripts/docs.sh serve
