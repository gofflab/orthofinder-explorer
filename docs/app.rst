App Overview
============

The Flask app exposes routes for browsing orthogroups and gene details.

Routes
------

- ``/``: Home page.
- ``/orthogroups``: Orthogroup search and pagination.
- ``/orthogroup/<id>``: Orthogroup detail view.
- ``/gene/<id>``: Gene detail view and sequence display.
- ``/gene_search``: Gene search form and results.
- ``/species``: Overview of every species in the dataset.
- ``/species/<name>``: Summary statistics, plots, and notable orthogroups for
  one species.
- ``/compare?a=<name>&b=<name>``: Gene-family expansions and contractions
  between two species.

The species pages and the JSON API behind them are described in
:doc:`species-pages`.

Gene tree links
---------------

Gene tree nodes render links to ``/gene/<id>``. Dpe tree labels can be
normalized at ingestion time to match database gene IDs (see :doc:`ingest`).

Tree controls
-------------

The orthogroup view includes controls for width, height, tip spacing, font size,
branch scale, and toggles for aligned tips and zoom to help with large trees.
