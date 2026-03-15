Species Annotation Inputs
=========================

Beyond the core OrthoFinder outputs, each species can supply richer
per-species annotation files that extend the database with isoform-level gene
structure and functional predictions.  This page describes the expected input
formats, the ingestion workflow, and the planned extensions for future database
integration, indexing, and display.

Overview
--------

The OrthoFinder ingestion pipeline (``ingest_orthofinder.py``) focuses on
**orthogroup-level** relationships: which gene belongs to which family, and
what the evolutionary tree looks like.  It stores one representative protein
sequence per gene.

The species annotation pipeline (``ingest_species_annotations.py``) adds
**within-species** resolution:

* **Isoforms** – all transcript variants of a gene, with their exon/CDS
  structure parsed from a GTF or GFF3 annotation file.
* **Protein domains** – functional domain predictions from InterProScan or
  Pfam/HMMER, linked to genes and transcripts.

These two layers are designed to be loaded independently; the annotation script
requires that the OrthoFinder ingestion has already run.

.. code-block:: text

   ingest_orthofinder.py    →  orthogroups, genes, sequences, gene_trees, species
   ingest_species_annotations.py  →  transcripts, transcript_features, protein_domains

Input File Formats
------------------

GTF / GFF3 Transcriptome Annotation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The primary annotation file for each species is a **GTF 2.2** or **GFF3**
file describing the transcriptome.  Both formats are auto-detected at parse
time (the parser peeks at the first non-comment line).

Minimum required content:

* ``transcript`` feature rows (or ``mRNA`` in GFF3) with ``transcript_id`` and
  ``gene_id`` attributes.
* ``exon`` and/or ``CDS`` feature rows associated to each transcript.

Optional but recommended attributes:

* ``transcript_biotype`` / ``transcript_type`` – used to populate the
  ``biotype`` column (e.g. ``protein_coding``, ``lncRNA``).
* ``transcript_name`` – a human-readable isoform name.

.. code-block:: text

   Typical ENSEMBL GTF layout
   --------------------------
   chr1  ensembl_havana  transcript  11869  14409  .  +  .  gene_id "ENSG00000223972"; transcript_id "ENST00000456328"; transcript_biotype "processed_transcript";
   chr1  ensembl_havana  exon        11869  12227  .  +  .  gene_id "ENSG00000223972"; transcript_id "ENST00000456328";

For non-model organisms (e.g. *Doryteuthis pealeii*) the annotation is often
assembled from a *de novo* transcriptome. Any GTF produced by tools such as
StringTie, Trinity+PASA, or similar pipelines is supported, provided the
``transcript_id`` and ``gene_id`` attributes are present.

Gene ID reconciliation
^^^^^^^^^^^^^^^^^^^^^^

The ``gene_id`` attribute in the GTF is matched against ``gene_id`` values
already stored in the ``genes`` table (populated by ``ingest_orthofinder.py``).
Matching is attempted in order:

1. **Exact match** – GTF ``gene_id`` == database ``gene_id``.
2. **Version-stripped match** – strip trailing ``.N`` or ``|suffix`` from the
   GTF ID and try again (e.g. ``ENSG00000223972.10`` → ``ENSG00000223972``).

Transcripts whose gene cannot be matched are still loaded; their ``gene_id``
column is set to ``NULL``.  A count of unmatched transcripts is printed at the
end of the run.

.. tip::

   If your GTF gene IDs differ systematically from OrthoFinder protein IDs
   (e.g. the protein FASTA uses transcript IDs rather than gene IDs), provide
   a mapping file in the config's ``id_mapping`` key (see :ref:`config-format`
   below).  This is planned for a future release.

Protein Domain Predictions
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two domain-search output formats are supported:

InterProScan TSV (``--output-format TSV``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The most comprehensive source.  A single InterProScan run can cover Pfam,
PANTHER, TIGRFAM, SUPERFAMILY, Gene3D, SMART, CDD, and more.  It also emits
integrated InterPro accessions (IPRxxxxxxx) and GO term mappings.

Recommended InterProScan command::

    interproscan.sh \
        -i proteins.fa \
        -f TSV \
        -o interproscan.tsv \
        --goterms \
        --pathways \
        -appl Pfam,PANTHER,Gene3D,SMART,TIGRFAM,SuperFamily

The parser reads the 15-column TSV format produced by InterProScan ≥ 5.x.

Pfam / HMMER ``--domtblout``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For labs that run Pfam searches independently with ``hmmscan``::

    hmmscan --cpu 8 --domtblout pfam_domtblout.txt Pfam-A.hmm proteins.fa

The parser reads the domain table output format (``--domtblout``), not the
alignment output.  Envelope coordinates (``env from`` / ``env to``) are used
as sequence coordinates.

Both formats can be provided for the same species; the ``domain_predictions``
config key accepts a list of file paths.

Running the Ingestion
---------------------

Prerequisites:

1. The database must already be populated by ``ingest_orthofinder.py``.
2. Species names in the config must match the ``species_name`` values stored in
   the ``species`` table (case-sensitive).

Basic usage::

    python scripts/ingest_species_annotations.py \
        --config config/species_annotations.json

Restrict to specific species::

    python scripts/ingest_species_annotations.py \
        --config config/species_annotations.json \
        --species Homo_sapiens Danio_rerio

Skip exon/CDS feature loading (useful for large genomes where feature storage
is not yet needed)::

    python scripts/ingest_species_annotations.py \
        --config config/species_annotations.json \
        --skip-features

Modes:

* ``rebuild`` (default) – deletes all existing annotation rows for each
  processed species before re-loading.
* ``append`` – adds rows without deleting existing data. Useful for adding
  domain hits from a new database without re-parsing GTFs.

.. _config-format:

Configuration Format
--------------------

See ``config/species_annotations.example.json`` for a complete example.

.. code-block:: json

    {
      "db_path": "instance/orthofinder_new.db",
      "mode": "rebuild",
      "skip_features": false,
      "feature_types": ["exon", "CDS", "five_prime_utr", "three_prime_utr"],

      "gtf_pattern": null,
      "domain_pattern": null,

      "species_annotations": {
        "Homo_sapiens": {
          "gtf_file": "annotations/Homo_sapiens/Homo_sapiens.GRCh38.112.gtf",
          "domain_predictions": [
            "annotations/Homo_sapiens/interproscan.tsv"
          ]
        }
      }
    }

Key options
~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 10 65

   * - Key
     - Default
     - Description
   * - ``db_path``
     - ``instance/orthofinder_new.db``
     - Path to the SQLite database.
   * - ``mode``
     - ``rebuild``
     - ``rebuild`` deletes existing annotations; ``append`` adds to them.
   * - ``skip_features``
     - ``false``
     - When ``true``, transcripts are loaded but individual exon/CDS rows are
       skipped (saves space for large genomes).
   * - ``feature_types``
     - (all four UTR/exon/CDS)
     - List of GTF feature types to store in ``transcript_features``.
   * - ``gtf_pattern``
     - ``null``
     - Pattern with ``{species_name}`` placeholder, used as a fallback when a
       species has no explicit ``gtf_file`` entry.
   * - ``domain_pattern``
     - ``null``
     - Pattern with ``{species_name}`` placeholder for domain files.
   * - ``species_annotations``
     - ``{}``
     - Per-species dict; each value may have ``gtf_file`` and/or
       ``domain_predictions`` (string or list).

Database Tables
---------------

Three new tables are added by this pipeline:

``transcripts``
~~~~~~~~~~~~~~~

One row per transcript isoform.  Links back to ``genes`` via ``gene_id``
(nullable when the gene cannot be matched).

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Column
     - Description
   * - ``transcript_id``
     - Primary key; transcript ID as written in the GTF attribute.
   * - ``gene_id``
     - FK → ``genes.gene_id`` (NULL if unmatched).
   * - ``species_id``
     - FK → ``species.species_id``.
   * - ``gtf_gene_id``
     - The raw ``gene_id`` attribute from the GTF (before matching).
   * - ``transcript_name``
     - ``transcript_name`` attribute if present.
   * - ``seqname``
     - Chromosome / scaffold name.
   * - ``source``
     - GTF source column.
   * - ``biotype``
     - ``transcript_biotype`` attribute (e.g. ``protein_coding``).
   * - ``start``, ``end``
     - 1-based inclusive genomic coordinates.
   * - ``strand``
     - ``+`` or ``-``.
   * - ``exon_count``
     - Number of exon features for this transcript.
   * - ``cds_length``
     - Summed CDS feature length in nucleotides.
   * - ``attributes_json``
     - Full GTF attribute dictionary serialised as JSON.

``transcript_features``
~~~~~~~~~~~~~~~~~~~~~~~

Individual exon, CDS, and UTR features.  Omitted when ``skip_features`` is
``true``.  Storing features as rows (rather than JSON) enables SQL range
queries (e.g. "find all features overlapping position X on scaffold Y").

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Column
     - Description
   * - ``feature_id``
     - Auto-increment integer PK.
   * - ``transcript_id``
     - FK → ``transcripts.transcript_id``.
   * - ``species_id``
     - FK → ``species.species_id``.
   * - ``feature_type``
     - One of: ``exon``, ``CDS``, ``five_prime_utr``, ``three_prime_utr``.
   * - ``seqname``
     - Chromosome / scaffold.
   * - ``start``, ``end``
     - 1-based inclusive coordinates.
   * - ``strand``
     - ``+`` or ``-``.
   * - ``frame``
     - Reading frame (``0``, ``1``, ``2``) for CDS; ``.`` otherwise.
   * - ``score``
     - GTF score column (often ``.``).

``protein_domains``
~~~~~~~~~~~~~~~~~~~

One row per domain hit.  May link to both a gene and a transcript, or to
neither (for sequences not yet matched to the database).

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Column
     - Description
   * - ``domain_id``
     - Auto-increment integer PK.
   * - ``gene_id``
     - FK → ``genes.gene_id`` (nullable).
   * - ``transcript_id``
     - FK → ``transcripts.transcript_id`` (nullable).
   * - ``species_id``
     - FK → ``species.species_id``.
   * - ``query_id``
     - Original sequence ID used in the domain search.
   * - ``database``
     - Domain database (``Pfam``, ``PANTHER``, ``TIGRFAM``, etc.).
   * - ``domain_accession``
     - Database-specific accession (e.g. ``PF00001``, ``IPR000001``).
   * - ``domain_name``
     - Short domain name.
   * - ``description``
     - Human-readable description.
   * - ``seq_start``, ``seq_end``
     - 1-based inclusive coordinates on the protein sequence.
   * - ``score``
     - Bit-score (HMMER) or equivalent.
   * - ``evalue``
     - E-value of the domain hit.
   * - ``interpro_accession``
     - Parent IPR accession (InterProScan only).
   * - ``interpro_description``
     - Parent IPR description (InterProScan only).
   * - ``go_terms``
     - Pipe-separated GO terms (InterProScan only).
   * - ``pathways``
     - Pipe-separated pathway annotations (InterProScan only).

Planned Features
----------------

The following capabilities are planned for future development.  They are noted
here to guide schema and API design decisions.

Display and exploration (web app)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Gene page – isoform panel**: List all transcripts for a gene, with exon
  count, CDS length, biotype, and a compact exon-structure diagram (similar to
  Ensembl transcript views).
* **Domain panel on gene and transcript pages**: Horizontal domain architecture
  diagram (protein length drawn to scale with coloured domain blocks).  Tooltip
  on hover shows accession, description, e-value.
* **Isoform comparison view**: Side-by-side exon structure of two or more
  transcripts belonging to the same gene.
* **Domain family page**: List all genes/proteins across all species that carry
  a given domain accession.
* **Search by domain**: Allow searching for genes by Pfam accession, IPR
  accession, or GO term.

Database indexing
~~~~~~~~~~~~~~~~~

The following indexes are recommended once the initial data load is stable:

.. code-block:: sql

   -- Transcript lookups by gene or species
   CREATE INDEX IF NOT EXISTS ix_transcripts_gene_id     ON transcripts (gene_id);
   CREATE INDEX IF NOT EXISTS ix_transcripts_species_id  ON transcripts (species_id);
   CREATE INDEX IF NOT EXISTS ix_transcripts_gtf_gene_id ON transcripts (gtf_gene_id);

   -- Feature range queries
   CREATE INDEX IF NOT EXISTS ix_features_transcript_id  ON transcript_features (transcript_id);
   CREATE INDEX IF NOT EXISTS ix_features_seqname_start  ON transcript_features (species_id, seqname, start, end);

   -- Domain lookups by gene, accession, GO
   CREATE INDEX IF NOT EXISTS ix_domains_gene_id         ON protein_domains (gene_id);
   CREATE INDEX IF NOT EXISTS ix_domains_accession       ON protein_domains (domain_accession);
   CREATE INDEX IF NOT EXISTS ix_domains_interpro        ON protein_domains (interpro_accession);

Additional annotation sources (future ingestion)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following data types are planned for ingestion in future iterations:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Source
     - Description
   * - **mRNA FASTA (per transcript)**
     - Populate ``sequences.mrna_sequence`` at the isoform level, keyed to
       ``transcripts.transcript_id``.  Currently ``mrna_sequence`` on
       ``Sequence`` is per-gene only.
   * - **Signal peptide / TM predictions**
     - SignalP / DeepTMHMM output; add ``signal_peptide`` and
       ``transmembrane_topology`` columns to ``transcripts`` or a new
       ``sequence_features`` table.
   * - **Ortholog-level functional annotation rollup**
     - Propagate GO terms from well-annotated species (human, mouse, zebrafish)
       to orthologous genes in less-annotated species via the orthogroup
       membership.
   * - **Differential expression**
     - Per-experiment TPM/count matrices linking to transcripts, enabling
       expression-aware exploration of orthogroups.
   * - **Synteny blocks**
     - Macro-synteny and microsynteny coordinates to enable cross-species
       locus comparisons within the browser.
   * - **BLAST / pairwise similarity**
     - Pre-computed pairwise best-hit tables for quick BLAST-free similarity
       lookups.
   * - **Repeat / transposable element annotation**
     - RepeatMasker output, stored as a separate ``repeat_features`` table,
       useful for filtering or annotating gene models near repeats.
   * - **Codon usage / compositional statistics**
     - Per-transcript GC content, codon bias indices; useful for expression
       and evolutionary rate analyses.

ID mapping for non-model organisms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A planned ``id_mapping`` config key will allow providing an explicit two-column
TSV file (``gtf_gene_id → database_gene_id``) for species where the GTF gene
IDs differ systematically from the OrthoFinder protein IDs (common for
*de novo* transcriptomes assembled without a reference genome).

Example config entry (not yet implemented)::

    "Doryteuthis_pealeii_20250213": {
        "gtf_file": "annotations/Dpe/transcriptome.gtf",
        "id_mapping": "annotations/Dpe/gene_id_map.tsv",
        "domain_predictions": ["annotations/Dpe/interproscan.tsv"]
    }
