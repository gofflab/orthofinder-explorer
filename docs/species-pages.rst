Species and Species Comparison Pages
====================================

Three pages summarise the OrthoFinder results at the level of whole species
rather than single orthogroups:

- ``/species``: every species in the dataset, side by side.
- ``/species/<name>``: one species in detail.
- ``/compare?a=<name>&b=<name>``: two species against each other.

All statistics are computed on demand from the database and cached in the web
process; nothing extra has to be precomputed at ingest time.

.. contents:: On this page
   :local:
   :depth: 2

Enabling the pages on an existing database
------------------------------------------

The pages work on any database built by ``scripts/ingest_orthofinder.py``.
Two optional additions make them faster and unlock the tree-based views.  Both
are applied by one idempotent script, which only ever adds things::

    python scripts/upgrade_db.py \
        --db instance/orthofinder_new.db \
        --species-tree /path/to/Results_XXXX/Species_Tree/SpeciesTree_rooted.txt

With Docker, rebuild the ``ingest`` image so that it contains the script, then
run it through that service::

    docker compose --profile ingest build ingest

    docker compose --profile ingest run --rm \
        -v /path/to/Results_XXXX:/input:ro \
        --entrypoint python ingest scripts/upgrade_db.py \
        --db /data/orthofinder_new.db \
        --species-tree /input/Species_Tree/SpeciesTree_rooted.txt

The script

* creates the ``species_tree`` table and stores the rooted species tree in it.
  Without a tree, species are listed alphabetically and the gene-age chart is
  replaced by a note;
* creates the indexes declared on the models (see :doc:`database`).  Without
  them every query still works, but annotation lookups scan whole tables.

Databases built after this feature was added need neither step:
``ingest_orthofinder.py`` stores the species tree and creates the indexes
itself.

How the numbers are defined
---------------------------

Everything starts from one table: the number of genes each species contributes
to each orthogroup.  Genes that OrthoFinder did not place in an orthogroup do
not appear in that table and are reported separately as *unassigned*.

Reference set and reference copy number
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When a species (or a pair of species) is studied, **all other species** form
the reference set.  The *reference copy number* of a family is the **median
copy number among the reference species that carry the family**.  Species that
lack the family are left out of the median on purpose: a single-copy family
found in only a few species should not make each of those species look
expanded.

The reference set can be narrowed on both pages (*Reference set* control).
Leave out a second annotation of the same species, for example, to stop it
from masking a lineage-specific family.

log2 ratio
~~~~~~~~~~

Copy-number differences are reported as
``log2((copies + 1) / (reference + 1))``.  The pseudocount keeps the ratio
finite when one side is zero and damps differences between very small counts.

Conservation classes
~~~~~~~~~~~~~~~~~~~~

Each orthogroup is classed by the share of species represented in it:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Class
     - Definition
   * - Species-specific
     - Found in exactly one species.
   * - Narrow
     - Found in two or more species, but in at most one third of them.
   * - Intermediate
     - Everything between narrow and near-universal.
   * - Near-universal
     - Found in at least 90% of species.

Core family coverage
~~~~~~~~~~~~~~~~~~~~

For a species, the *core* families are those present in at least 90% of the
**other** species.  Core coverage is the share of those families in which the
species has at least one gene.  It behaves like a BUSCO completeness score
built from the dataset itself: a low value usually means an incomplete or
fragmented gene set rather than genuine loss.

Gene age (phylostrata)
~~~~~~~~~~~~~~~~~~~~~~

Requires the species tree.  The tree defines a series of nested clades from
its root down to the species.  Each family is assigned to the smallest of
those clades that still contains every species in the family, that is, to the
most recent common ancestor of its members.  Families in the last stratum are
species-specific; families in the first span the root of the tree.

This is a presence/absence inference.  Missing annotations in distant species
make families look younger than they are, and mis-clustered genes can do the
opposite, so read the distribution as the result and individual calls as
hypotheses.

Notable orthogroups (species page)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - List
     - Rule
   * - Expanded
     - Shared with at least *N* reference species, and at least two copies
       above the reference copy number.  Ranked by log2 ratio.
   * - Species-specific
     - Present in no reference species.  Ranked by size.
   * - Contracted
     - Shared with at least *N* reference species, and at least two copies
       below the reference copy number.  Ranked by log2 ratio.
   * - Missing here
     - Absent from the species, present in at least *N* reference species.
       Ranked by how many reference species carry the family.
   * - Gene-age stratum
     - Families assigned to the stratum clicked in the gene-age chart.

*N* is the "Shared with at least" control (default 3).

Comparison classes (comparison page)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A shared family is called *larger in A* when it clears both thresholds chosen
on the page: a minimum fold difference (default 2x, on the pseudocounted
ratio) and a minimum absolute difference (default 2 genes).  Families present
in only one of the two species are listed separately.

The *likely change* column polarises a difference with the reference copy
number.  A species counts as having gained (or lost) copies when it differs
from the reference by at least one gene and at least 1.5-fold.  A family that
is larger in A may therefore be reported as a gain in A, a loss in B, both, or
unclear.  This is a quick orientation, not a gene-tree reconciliation; use the
gene tree on the orthogroup page, or a dedicated method such as CAFE, before
drawing conclusions about a particular family.

Charts
------

Species overview (``/species``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **How conserved is each gene set?**  Genes per species split by conservation
  class, drawn beside the species tree when one is loaded.
* **Which species share the most gene families?**  Jaccard similarity of the
  orthogroup sets of every pair of species.  Click a cell to compare the pair.
* **Summary table.**  Sortable; includes core coverage and which optional
  annotations are loaded.

Species (``/species/<name>``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Headline numbers: proteins, share in orthogroups, orthogroups,
  species-specific families, core coverage, median protein length.
* Families by the number of species sharing them, gene age along the lineage,
  family size, and families shared with each other species.
* One measure across all species with this species highlighted.
* Notable orthogroups, with the selected family's copy number in every species
  shown beside the table.
* Annotation: protein length distribution; transcript statistics (isoforms per
  gene, exons per transcript, biotypes); domain statistics (coverage, largest
  families per database, and coverage by conservation class).

Species comparison (``/compare``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Copy-number landscape.**  Orthogroups counted by copies in A (across) and
  B (up).  Off-diagonal cells are expansions or contractions.
* **Which lineage changed?**  Copy number in each species relative to the
  reference.  Points right of zero have more copies in A than the reference;
  points above zero have more in B.
* **How large are the differences?**  Distribution of the log2 ratio for
  shared families with unequal copy number.
* **Orthology relationships.**  One-to-one, one-to-many, many-to-one,
  many-to-many, and families found in only one species.
* **Families that differ.**  Tables for each class, plus any selection made by
  clicking a cell or bubble in the charts above.
* **Protein domain families.**  Genes per domain in the two species, when both
  have domain annotations loaded.  Independent of the orthogroup clustering.

Every chart has a *View data* button that swaps it for the underlying table.

JSON API
--------

The pages load their data from these endpoints, which can also be used
directly.

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Endpoint
     - Returns
   * - ``GET /api/species``
     - Summary row per species, species tree, pairwise shared-orthogroup
       counts.
   * - ``GET /api/species/<name>/overview``
     - Summary, breadth and copy-number distributions, sharing with each
       other species, phylostrata.
   * - ``GET /api/species/<name>/orthogroups``
     - Ranked orthogroups.  Parameters: ``category`` (``expanded``,
       ``specific``, ``contracted``, ``absent``, ``stratum``), ``min_other``,
       ``limit``, ``stratum``, ``exclude`` (comma-separated species names).
   * - ``GET /api/species/<name>/annotations``
     - Protein length, transcript and domain statistics.
   * - ``GET /api/species/<name>/domains``
     - Largest domain families.  Parameters: ``db``, ``limit``.
   * - ``GET /api/compare?a=&b=``
     - Orthology classes and per-orthogroup copy numbers with the reference
       copy number.  Parameter: ``exclude``.
   * - ``GET /api/compare/domains?a=&b=``
     - Genes per domain family in the two species.  Parameter: ``db``.
   * - ``GET /api/orthogroup/<id>/profile``
     - Copy number of one orthogroup in every species.
   * - ``POST /api/orthogroups/annotations``
     - Representative domain annotations for ``{"ids": [...]}``.

Caching
-------

Results are cached per web process and discarded automatically when an ingest
script or ``upgrade_db.py`` changes the database (checked at most every ten
seconds).  Entries also expire after ``ORTHOFINDER_ANALYSIS_CACHE_TTL``
seconds (default 1800).  The first request after a restart or an ingest is
therefore the slow one: expect a few seconds on a full-size dataset.

Colors
------

Chart colors are CSS custom properties in ``app/static/charts.css``
(``--chart-series-a``, ``--chart-series-b``, the ``--chart-ordinal-*`` ramp and
so on).  The JavaScript reads them at render time, so the palette can be
changed there without touching chart code.  Species A (or the focal species)
is always the first series color and species B the second; clade colors from
``species_colors.json`` appear only as small dots beside species names.
