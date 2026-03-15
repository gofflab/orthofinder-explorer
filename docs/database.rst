Database
========

The app uses a single SQLite database file built by the two ingestion scripts.
This page is the complete reference for all tables, columns, and relationships.

For the ingestion pipeline that creates these tables, see :doc:`ingest` and
:doc:`species-annotations`.

.. contents:: On this page
   :local:
   :depth: 2

Selecting the database
----------------------

The Flask app reads the DB path from the ``ORTHOFINDER_DB_PATH`` environment
variable::

    export ORTHOFINDER_DB_PATH=instance/orthofinder_new.db
    python run.py

If not set, the app defaults to ``instance/orthofinder_new.db`` inside the
Flask instance directory.

In Docker, the variable is set in ``docker-compose.yml`` and points to the
path on the persistent ``orthofinder-data`` volume.

Table overview
--------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Table
     - Populated by
     - Purpose
   * - ``species``
     - Stage 1
     - One row per species.  The canonical species name is the protein FASTA
       basename used as OrthoFinder input.
   * - ``orthogroups``
     - Stage 1
     - One row per orthogroup (gene family), with the optional Newick gene
       tree.
   * - ``genes``
     - Stage 1
     - One row per gene, linked to an orthogroup and a species.
   * - ``sequences``
     - Stage 1
     - Protein sequence for each gene, linked back to ``genes``.
   * - ``gene_key_lookup``
     - Stage 1
     - Maps OrthoFinder's internal ``{species_idx}_{gene_idx}`` tokens back
       to the original gene IDs.
   * - ``ingest_runs``
     - Stage 1
     - Audit log of every ingest run with config and record counts.
   * - ``transcripts``
     - Stage 2
     - One row per transcript isoform, parsed from per-species GTF/GFF3 files.
       Optionally includes the spliced mRNA nucleotide sequence.
   * - ``transcript_features``
     - Stage 2
     - Individual exon, CDS, and UTR features for each transcript.
   * - ``protein_domains``
     - Stage 2
     - Protein domain predictions from InterProScan or Pfam/HMMER, linked to
       genes and transcripts.

Stage 1 tables
--------------

``species``
~~~~~~~~~~~

One row per species loaded from ``WorkingDirectory/SpeciesIDs.txt``.

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``species_id``
     - INTEGER PK
     - OrthoFinder's internal numeric species index (0-based, reassigned on
       every run).
   * - ``species_name``
     - TEXT
     - Species name derived from the protein FASTA basename (without
       extension).  This is the canonical identifier used across all config
       files and the ``species_annotations.json`` keys.

.. note::

   ``species_id`` values are **not stable** across OrthoFinder runs.  A fresh
   run will reassign indices even for the same set of species, depending on
   alphabetical order.  Always refer to species by ``species_name``.

``orthogroups``
~~~~~~~~~~~~~~~

One row per orthogroup (HOG or OG) present in ``N0.tsv``.  The gene tree is
populated after the orthogroup rows are inserted.

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``orthogroup_id``
     - TEXT PK
     - OrthoFinder orthogroup identifier (e.g. ``N0.HOG0000001`` or
       ``OG0000001``).
   * - ``gene_tree``
     - TEXT
     - Newick-format gene tree string.  NULL if no tree file was found.
   * - ``description``
     - TEXT
     - Optional human-readable description.  Not populated by the ingestor;
       available for manual annotation.

``genes``
~~~~~~~~~

One row per gene across all species.  A gene may belong to at most one
orthogroup.

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``gene_id``
     - TEXT PK
     - Original gene/protein identifier from the species protein FASTA header
       (first whitespace-delimited token after ``>``).
   * - ``ortho_gene_id``
     - TEXT
     - OrthoFinder's internal gene identifier (the ``{species_idx}_{gene_idx}``
       token from ``SequenceIDs.txt``).
   * - ``orthogroup_id``
     - TEXT FK → ``orthogroups``
     - Orthogroup this gene belongs to.  NULL for genes that OrthoFinder
       assigned to no orthogroup.
   * - ``species_id``
     - INTEGER FK → ``species``
     - Species this gene comes from.
   * - ``gene_name``
     - TEXT
     - Optional common gene name.  Not populated by the ingestor.
   * - ``description``
     - TEXT
     - Optional gene description.  Not populated by the ingestor.

``sequences``
~~~~~~~~~~~~~

Protein sequence for each gene.  One-to-one with ``genes``.

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``sequence_idx``
     - TEXT PK
     - Row index from the merged protein sequence DataFrame (string
       representation of an integer).
   * - ``ortho_id``
     - TEXT
     - OrthoFinder's ``{species_idx}_{gene_idx}`` token for this sequence.
   * - ``species_id``
     - INTEGER FK → ``species``
     - Species this sequence comes from.
   * - ``ortho_gene_id``
     - TEXT
     - OrthoFinder gene index within the species.
   * - ``gene_id``
     - TEXT FK → ``genes``
     - Links to the ``genes`` row for this sequence.
   * - ``protein_sequence``
     - TEXT
     - Full amino acid sequence.
   * - ``mrna_sequence``
     - TEXT
     - Nucleotide (mRNA) sequence at the gene level, if available.  Currently
       not populated by the Stage 1 ingestor.  For isoform-level mRNA
       sequences see ``transcripts.mrna_sequence`` (Stage 2).

``gene_key_lookup``
~~~~~~~~~~~~~~~~~~~

Mapping table that allows resolving OrthoFinder's internal sequence IDs back
to original gene IDs and vice versa.

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``of_gene_id``
     - TEXT PK
     - OrthoFinder's ``{species_idx}_{gene_idx}`` token.
   * - ``species_id``
     - INTEGER FK → ``species``
     - Species this token belongs to.
   * - ``species_of_index``
     - INTEGER
     - The numeric gene index within the species (second component of
       ``of_gene_id``).
   * - ``gene_id``
     - TEXT FK → ``genes``
     - The original gene ID from the protein FASTA header.

``ingest_runs``
~~~~~~~~~~~~~~~

Audit log.  One row is appended per completed ``ingest_orthofinder.py`` run.
In ``rebuild`` mode the table itself is re-created, so only the current run's
row is retained.

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``id``
     - INTEGER PK
     - Auto-increment.
   * - ``dataset_name``
     - TEXT
     - Value of the ``dataset_name`` config key, or the ``input_dir``
       basename if not set.
   * - ``input_dir``
     - TEXT
     - Fully resolved ``input_dir`` path.
   * - ``created_at``
     - DATETIME
     - UTC timestamp of the run.
   * - ``orthogroups_count``
     - INTEGER
     - Number of distinct orthogroup IDs loaded.
   * - ``genes_count``
     - INTEGER
     - Number of gene rows inserted.
   * - ``sequences_count``
     - INTEGER
     - Number of sequence rows inserted.
   * - ``gene_trees_count``
     - INTEGER
     - Number of gene trees loaded.
   * - ``config_json``
     - TEXT
     - Full merged config dictionary serialised as JSON.

Stage 2 tables
--------------

These tables are populated by ``scripts/ingest_species_annotations.py``.  They
can be dropped and rebuilt independently without affecting the Stage 1 tables.

``transcripts``
~~~~~~~~~~~~~~~

One row per transcript isoform, parsed from per-species GTF or GFF3 annotation
files.  The ``gene_id`` foreign key links to ``genes`` when the GTF
``gene_id`` attribute can be matched to an existing gene record; it is NULL
when no match is found.

Genomic coordinates use the **1-based inclusive** interval convention (GTF
standard).

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``transcript_id``
     - TEXT PK
     - Transcript identifier from the GTF ``transcript_id`` attribute (or GFF3
       ``ID`` attribute).
   * - ``gene_id``
     - TEXT FK → ``genes`` (nullable)
     - Linked gene record.  NULL when the GTF gene_id cannot be matched.
   * - ``species_id``
     - INTEGER FK → ``species``
     - Species this transcript belongs to.
   * - ``gtf_gene_id``
     - TEXT
     - Raw ``gene_id`` attribute value from the GTF, stored before any
       matching attempt.  Useful for debugging unmatched transcripts.
   * - ``transcript_name``
     - TEXT
     - ``transcript_name`` attribute if present in the GTF.  For
       mRNA-FASTA-only stubs this field holds the remainder of the FASTA
       header line.
   * - ``seqname``
     - TEXT
     - Chromosome or scaffold name (GTF column 1).  NULL for mRNA-FASTA-only
       stub records.
   * - ``source``
     - TEXT
     - GTF source column (e.g. ``ensembl_havana``, ``StringTie``).  Set to
       ``mrna_fasta`` for stub records created during mRNA FASTA ingestion.
   * - ``biotype``
     - TEXT
     - ``transcript_biotype`` or ``transcript_type`` attribute
       (e.g. ``protein_coding``, ``lncRNA``).  Empty string when absent.
   * - ``start``
     - INTEGER
     - 1-based start coordinate.  NULL for mRNA-FASTA-only stubs.
   * - ``end``
     - INTEGER
     - 1-based end coordinate (inclusive).  NULL for mRNA-FASTA-only stubs.
   * - ``strand``
     - TEXT(1)
     - ``+`` or ``-``.  NULL for mRNA-FASTA-only stubs.
   * - ``exon_count``
     - INTEGER
     - Number of ``exon`` feature rows associated with this transcript.
   * - ``cds_length``
     - INTEGER
     - Summed length (nt) of all ``CDS`` feature rows.  Zero when no CDS
       features are present.
   * - ``attributes_json``
     - TEXT
     - Full GTF attribute dictionary serialised as JSON.  Useful for accessing
       fields not stored in dedicated columns.
   * - ``mrna_sequence``
     - TEXT (nullable)
     - Full spliced transcript nucleotide sequence loaded from the per-species
       mRNA FASTA file.  NULL until an mRNA FASTA is ingested.

``transcript_features``
~~~~~~~~~~~~~~~~~~~~~~~

Individual exon, CDS, and UTR features for each transcript.  Storing features
as individual rows enables SQL range queries such as "find all features
overlapping position X on scaffold Y".

This table is omitted when ``skip_features: true`` is set in the annotations
config.

Coordinates use the **1-based inclusive** interval convention (GTF standard).

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``feature_id``
     - INTEGER PK
     - Auto-increment.
   * - ``transcript_id``
     - TEXT FK → ``transcripts``
     - Transcript this feature belongs to.
   * - ``species_id``
     - INTEGER FK → ``species``
     - Species, denormalised for efficient species-level queries.
   * - ``feature_type``
     - TEXT
     - GTF feature type.  One of: ``exon``, ``CDS``, ``five_prime_utr``,
       ``three_prime_utr``.  Controlled by the ``feature_types`` config key.
   * - ``seqname``
     - TEXT
     - Chromosome or scaffold name.
   * - ``start``
     - INTEGER
     - 1-based start coordinate.
   * - ``end``
     - INTEGER
     - 1-based end coordinate (inclusive).
   * - ``strand``
     - TEXT(1)
     - ``+`` or ``-``.
   * - ``frame``
     - TEXT(1)
     - Reading frame (``0``, ``1``, or ``2``) for CDS features.  ``.`` for
       exon and UTR features.
   * - ``score``
     - TEXT
     - GTF score column value (often ``.``).

``protein_domains``
~~~~~~~~~~~~~~~~~~~

One row per domain hit from an InterProScan TSV or HMMER ``--domtblout`` file.
The ``gene_id`` and ``transcript_id`` foreign keys are set whenever the query
sequence ID can be matched to an existing record; both may be NULL.

Protein coordinates use the **1-based inclusive** convention (standard
InterProScan and HMMER output).

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Column
     - Type
     - Description
   * - ``domain_id``
     - INTEGER PK
     - Auto-increment.
   * - ``gene_id``
     - TEXT FK → ``genes`` (nullable)
     - Gene whose protein carries this domain.  NULL when the query ID cannot
       be matched.
   * - ``transcript_id``
     - TEXT FK → ``transcripts`` (nullable)
     - Specific transcript/isoform this domain was predicted on.  NULL when
       the query ID cannot be matched to a transcript.
   * - ``species_id``
     - INTEGER FK → ``species`` (nullable)
     - Species, denormalised for efficient species-level queries.
   * - ``query_id``
     - TEXT
     - Original sequence identifier used in the domain search (verbatim from
       the domain file).
   * - ``database``
     - TEXT
     - Domain database (e.g. ``Pfam``, ``PANTHER``, ``Gene3D``, ``TIGRFAM``,
       ``SUPERFAMILY``, ``SMART``).
   * - ``domain_accession``
     - TEXT
     - Database-specific accession (e.g. ``PF00001``, ``PTHR11111``).
   * - ``domain_name``
     - TEXT
     - Short name or identifier for the domain/family.
   * - ``description``
     - TEXT
     - Human-readable description of the domain.
   * - ``seq_start``
     - INTEGER
     - Start of the domain hit on the protein sequence (1-based).
   * - ``seq_end``
     - INTEGER
     - End of the domain hit on the protein sequence (1-based, inclusive).
   * - ``score``
     - REAL
     - Bit-score (HMMER) or equivalent numeric score.
   * - ``evalue``
     - REAL
     - E-value of the domain hit.
   * - ``interpro_accession``
     - TEXT
     - Parent InterPro accession (e.g. ``IPR000001``).  Populated from
       InterProScan TSV column 11.  Empty string for HMMER-only inputs.
   * - ``interpro_description``
     - TEXT
     - Human-readable InterPro entry description.
   * - ``go_terms``
     - TEXT
     - Pipe-separated GO term accessions (e.g. ``GO:0005488|GO:0006810``).
       Populated when InterProScan is run with ``--goterms``.
   * - ``pathways``
     - TEXT
     - Pipe-separated pathway annotations (e.g. ``Reactome: R-HSA-1``).
       Populated when InterProScan is run with ``--pathways``.

Recommended indexes
-------------------

SQLite does not create indexes on foreign key columns automatically.  Add these
after the initial data load and before enabling the web app for interactive
use:

.. code-block:: sql

   -- Gene lookups
   CREATE INDEX IF NOT EXISTS ix_genes_species_id      ON genes (species_id);
   CREATE INDEX IF NOT EXISTS ix_genes_orthogroup_id   ON genes (orthogroup_id);

   -- Transcript lookups
   CREATE INDEX IF NOT EXISTS ix_transcripts_gene_id     ON transcripts (gene_id);
   CREATE INDEX IF NOT EXISTS ix_transcripts_species_id  ON transcripts (species_id);
   CREATE INDEX IF NOT EXISTS ix_transcripts_gtf_gene_id ON transcripts (gtf_gene_id);

   -- Feature range queries (species + scaffold + position)
   CREATE INDEX IF NOT EXISTS ix_features_transcript_id
       ON transcript_features (transcript_id);
   CREATE INDEX IF NOT EXISTS ix_features_seqname_start
       ON transcript_features (species_id, seqname, start, end);

   -- Domain lookups
   CREATE INDEX IF NOT EXISTS ix_domains_gene_id        ON protein_domains (gene_id);
   CREATE INDEX IF NOT EXISTS ix_domains_transcript_id  ON protein_domains (transcript_id);
   CREATE INDEX IF NOT EXISTS ix_domains_accession      ON protein_domains (domain_accession);
   CREATE INDEX IF NOT EXISTS ix_domains_interpro       ON protein_domains (interpro_accession);

Entity-relationship summary
---------------------------

.. code-block:: text

   species ──(1:N)──► genes ──(N:1)──► orthogroups
                        │
                        └──(1:1)──► sequences

   species ──(1:N)──► transcripts ◄──(N:1, nullable)── genes
                          │
                          ├──(1:N)──► transcript_features
                          │
                          └──(1:N, nullable)──► protein_domains
                                                    │
                                        (N:1, nullable)── genes
