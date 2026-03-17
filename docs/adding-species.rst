Adding or Updating Species
==========================

This guide walks through the complete process of incorporating new species — or
re-running with an updated set — from raw protein sequences through to a fully
annotated database.  Read this page first, then refer to :doc:`ingest` and
:doc:`species-annotations` for detailed config references.

.. contents:: On this page
   :local:
   :depth: 2

Overview
--------

The pipeline has two sequential stages.  Both must be run in order; the second
stage depends on the database rows written by the first.

.. code-block:: text

   ┌──────────────────────────────────────────────────────────────────┐
   │  Stage 1 – OrthoFinder + core ingest                            │
   │                                                                  │
   │  Protein FASTAs ──► OrthoFinder ──► ingest_orthofinder.py       │
   │                                          │                       │
   │                                          ▼                       │
   │                                    SQLite DB                     │
   │                                    (orthogroups, genes,          │
   │                                     sequences, species)          │
   └──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  Stage 2 – Per-species annotation ingest (optional but          │
   │            recommended for each species)                        │
   │                                                                  │
   │  Per-species:  GTF/GFF3 ─────────────────────────────┐          │
   │                mRNA FASTA ──────────────────────────► │          │
   │                InterProScan / Pfam domtblout ────────► │         │
   │                                                        ▼         │
   │                             ingest_species_annotations.py        │
   │                                          │                       │
   │                                          ▼                       │
   │                                    SQLite DB                     │
   │                                    (transcripts, domains)        │
   └──────────────────────────────────────────────────────────────────┘

Important rules
~~~~~~~~~~~~~~~

* **OrthoFinder cannot add species incrementally.**  Adding even one new species
  requires re-running OrthoFinder from scratch with the full species set.  The
  result is a new ``Results_XXXX`` directory that replaces the previous one.
* **Stage 1 must run before Stage 2.**  ``ingest_species_annotations.py``
  matches annotation records against ``species``, ``genes``, and ``transcripts``
  rows that only exist after Stage 1.
* **Species names are fixed at protein FASTA filename.**  The name OrthoFinder
  writes to ``WorkingDirectory/SpeciesIDs.txt`` is the basename of the protein
  FASTA file (without extension).  This exact string must be used in
  ``species_annotations.json``.

.. _species-naming:

Species naming
--------------

OrthoFinder derives each species' canonical name from the filename of its
protein FASTA::

    proteins/
      Homo_sapiens.fa             →  species_name = "Homo_sapiens"
      Mus_musculus.fa             →  species_name = "Mus_musculus"
      Doryteuthis_pealeii_20250213.fa  →  species_name = "Doryteuthis_pealeii_20250213"

The name appears verbatim in ``WorkingDirectory/SpeciesIDs.txt``::

    0: Homo_sapiens.fa
    1: Mus_musculus.fa
    2: Doryteuthis_pealeii_20250213.fa

The ingestor strips the ``.fa`` suffix and stores the remainder as
``species.species_name``.  **Every downstream config — forced clades,
species_annotations keys — must use this exact string.**

Naming conventions to follow:

* Use underscores, not spaces.
* Include a date or version suffix when the proteome assembly may change
  (e.g. ``Doryteuthis_pealeii_20250213``).  This allows multiple assemblies
  of the same species to coexist without key collisions.
* Avoid special characters that the filesystem or SQLite would misinterpret
  (parentheses, slashes, etc.).

Stage 1: Preparing inputs and running OrthoFinder
--------------------------------------------------

Step 1 – Collect protein FASTA files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One protein FASTA file is required per species.  OrthoFinder uses these as its
primary input.

**File format requirements:**

* Standard FASTA format (``>``, header, one or more sequence lines).
* **Amino acid sequences only** — OrthoFinder does not accept nucleotide FASTAs
  at this stage.
* Each sequence header must be unique within the file.  Headers may contain
  spaces; only the first whitespace-delimited token is used as the sequence ID.
* Multi-line (wrapped) sequences are accepted.
* Compressed files (``.gz``) are not accepted by OrthoFinder directly;
  decompress first.

Example::

    >TP53_HUMAN
    MEEPQSDPSVEPPLSQETFSDLWKLLPENNVLSPLPSQAMDDLMLSPDDIEQWFTEDP
    GPDEAPRMPEAAPPVAPAPAAPTPAAPAPAPSWPLSSSVPSQKTYPQGLNGTVSTMDVFR
    ...
    >BRCA1_HUMAN
    MDLSALRVEEVQNVINAMQKILECPICLELIKEPVSTKCDHIFCKFCMLKLLNQKKGPS
    ...

Place all protein FASTAs in a single directory::

    proteins/
      Homo_sapiens.fa
      Mus_musculus.fa
      Danio_rerio.fa
      Doryteuthis_pealeii_20250213.fa
      Octopus_bimaculoides.fa

Step 2 – Run OrthoFinder
~~~~~~~~~~~~~~~~~~~~~~~~

A minimal OrthoFinder run::

    orthofinder -f proteins/ -t 16 -a 4

Common flags:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Flag
     - Meaning
   * - ``-f``
     - Input directory containing protein FASTAs.
   * - ``-t``
     - Number of threads for BLAST/Diamond searches.
   * - ``-a``
     - Number of threads for tree inference.
   * - ``-M msa``
     - Use MSA-based trees (slower but higher quality for large orthogroups).
   * - ``-S diamond``
     - Use Diamond instead of BLAST for all-vs-all (default for most runs).
   * - ``-n``
     - Append a name to the results directory (e.g. ``-n Feb21`` →
       ``Results_Feb21``).

OrthoFinder writes its output to a timestamped subdirectory inside the input
directory::

    proteins/
      OrthoFinder/
        Results_Feb21/
          Gene_Trees/
          Phylogenetic_Hierarchical_Orthogroups/N0.tsv
          Species_Tree/SpeciesTree_rooted.txt
          WorkingDirectory/
            SpeciesIDs.txt
            SequenceIDs.txt
            Species0.fa
            Species1.fa
            ...

Step 3 – Verify OrthoFinder outputs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before ingesting, confirm that these files all exist:

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Path (relative to ``Results_XXXX/``)
     - Purpose
   * - ``WorkingDirectory/SpeciesIDs.txt``
     - Maps numeric species index → species name.
   * - ``WorkingDirectory/SequenceIDs.txt``
     - Maps ``N_M`` index → original gene ID.
   * - ``WorkingDirectory/Species{N}.fa``
     - Re-indexed protein FASTA for each species.
   * - ``Phylogenetic_Hierarchical_Orthogroups/N0.tsv``
     - Orthogroup assignments (one column per species).
   * - ``Species_Tree/SpeciesTree_rooted.txt``
     - Rooted species phylogeny in Newick format.
   * - ``Gene_Trees/{OG}_tree.txt``
     - Per-orthogroup gene trees (one file each).

If ``Gene_Trees/`` is empty, OrthoFinder may not have completed tree
inference.  Re-run with ``-M msa`` or allow more wall-clock time.

Stage 1 ingest: ``ingest_orthofinder.py``
-----------------------------------------

Step 4 – Write the OrthoFinder ingest config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Copy the example and edit for your run::

    cp config/orthofinder_ingest.example.json config/my_run.json

Minimum required changes:

.. code-block:: json

    {
      "input_dir":    "data/OrthoFinder/Results_Feb21",
      "db_path":      "instance/orthofinder_new.db",
      "mode":         "rebuild",
      "dataset_name": "Results_Feb21"
    }

See :ref:`orthofinder-config-reference` in :doc:`ingest` for every available
key with type, default, and description.

**Key decision — ``mode``:**

``rebuild``
    Drops all existing tables and rebuilds from scratch.  Use this for any new
    OrthoFinder run, including one that adds species to an existing study.
    Because OrthoFinder re-numbers all species and gene IDs in every run, an
    ``append`` of a new run would produce duplicate or conflicting rows.

``append``
    Adds rows to an existing database without dropping tables.  Only use this
    if you are loading a second, completely independent dataset (e.g. a
    parallel analysis of a different clade) into the same DB.

**Updating ``forced_clades``:**  If you added new species, update the
``forced_clades`` section to include them in the appropriate clade.  Species
not listed in any forced clade are coloured automatically by tree topology.

Step 5 – Run the OrthoFinder ingest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Local (non-Docker)::

    python scripts/ingest_orthofinder.py --config config/my_run.json

Docker::

    docker compose --profile ingest run --rm \
        -v /path/to/OrthoFinder/Results_Feb21:/input:ro \
        ingest --config /config/orthofinder_ingest.docker.json

Or using the helper script::

    bash scripts/ingest_docker.sh /path/to/OrthoFinder/Results_Feb21 Results_Feb21

Expected output::

    Rebuilding database...
    Loading orthogroups...
    Loading species...
    Loading genes...
    Loading protein sequences...
    Computing species color palette...
    Loading gene trees...
    Done.

Verify the ingest succeeded by checking the row counts in ``ingest_runs``::

    sqlite3 instance/orthofinder_new.db \
        "SELECT dataset_name, orthogroups_count, genes_count, sequences_count, gene_trees_count, created_at FROM ingest_runs ORDER BY id DESC LIMIT 5;"

Stage 2: Preparing per-species annotation files
------------------------------------------------

Each species can optionally supply up to three types of annotation files.  None
is strictly required, but all three together give the richest database.

.. _per-species-files:

Per-species file summary
~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - File type
     - Required?
     - Purpose
   * - Protein FASTA
     - **Yes** (Stage 1)
     - OrthoFinder input.  Must be provided for every species before running
       OrthoFinder.  Not used again after Stage 1.
   * - GTF / GFF3
     - Optional
     - Isoform-level gene structure: transcript coordinates, exon/CDS
       boundaries, biotype, strand.  Populates ``transcripts`` and
       ``transcript_features``.
   * - mRNA FASTA
     - Optional
     - Spliced transcript nucleotide sequences, one per isoform.  Populates
       ``transcripts.mrna_sequence``.
   * - InterProScan TSV
     - Optional
     - Protein domain predictions from multiple databases (Pfam, PANTHER,
       Gene3D, SMART, TIGRFAM, …) with integrated IPR accessions and GO terms.
       Populates ``protein_domains``.
   * - Pfam domtblout
     - Optional
     - Pfam-only HMMER ``--domtblout`` output, for labs that run Pfam
       independently.  Also populates ``protein_domains``.

Where to obtain annotation files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Model organisms:**

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Species
     - Recommended source
   * - *Homo sapiens*
     - Ensembl FTP: ``Homo_sapiens.GRCh38.NN.gtf.gz``,
       ``Homo_sapiens.GRCh38.cdna.all.fa.gz``
   * - *Mus musculus*
     - Ensembl FTP: ``Mus_musculus.GRCm39.NN.gtf.gz``,
       ``Mus_musculus.GRCm39.cdna.all.fa.gz``
   * - *Danio rerio*
     - Ensembl FTP: ``Danio_rerio.GRCz11.NN.gtf.gz``,
       ``Danio_rerio.GRCz11.cdna.all.fa.gz``
   * - *Oncorhynchus tshawytscha*
     - NCBI RefSeq: ``GCF_002872995.1_Otsh_v1.0_genomic.gtf.gz``,
       ``GCF_002872995.1_Otsh_v1.0_rna.fna.gz``

**Non-model organisms (e.g. cephalopods):**

GTF and mRNA FASTA are typically produced by the same pipeline that generated
the protein FASTA used for OrthoFinder:

* **StringTie** (genome-guided): run ``stringtie --merge`` to produce a
  consensus GTF; extract transcript sequences with ``gffread -w mrna.fa``.
* **Trinity + PASA** (de novo): PASA generates a GFF3; Trinity produces the
  transcript FASTA directly.
* **TransDecoder**: if protein sequences were predicted with TransDecoder, the
  ``.pep`` FASTA and ``.gff3`` annotation are suitable inputs.

Protein domain predictions
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run InterProScan on the same protein FASTA used for OrthoFinder::

    interproscan.sh \
        -i proteins/Homo_sapiens.fa \
        -f TSV \
        -o annotations/Homo_sapiens/interproscan.tsv \
        --goterms \
        --pathways \
        -appl Pfam,PANTHER,Gene3D,SMART,TIGRFAM,SuperFamily \
        -cpu 16

Or run Pfam with HMMER directly::

    hmmscan \
        --cpu 16 \
        --domtblout annotations/Homo_sapiens/pfam_domtblout.txt \
        Pfam-A.hmm \
        proteins/Homo_sapiens.fa

Both files can be provided for the same species; the ingestion script loads
them in the order listed under ``domain_predictions``.

Organising annotation files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

We recommend keeping all annotation files under an ``annotations/`` directory
with one subdirectory per species name.  The directory name **must exactly
match** the ``species_name`` stored in the database (i.e. the protein FASTA
basename)::

    annotations/
      Homo_sapiens/
        Homo_sapiens.GRCh38.112.gtf
        Homo_sapiens.GRCh38.cdna.all.fa
        interproscan.tsv
      Mus_musculus/
        Mus_musculus.GRCm39.112.gtf
        Mus_musculus.GRCm39.cdna.all.fa
        interproscan.tsv
      Doryteuthis_pealeii_20250213/
        transcriptome_annotated.gtf
        transcriptome.fa
        interproscan.tsv
        pfam_domtblout.txt

Stage 2 ingest: ``ingest_species_annotations.py``
--------------------------------------------------

Step 6 – Write the annotations config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Copy the example and edit::

    cp config/species_annotations.example.json config/my_annotations.json

Minimum config for one species with all file types:

.. code-block:: json

    {
      "db_path": "instance/orthofinder_new.db",
      "mode": "rebuild",
      "species_annotations": {
        "Homo_sapiens": {
          "gtf_file":           "annotations/Homo_sapiens/Homo_sapiens.GRCh38.112.gtf",
          "mrna_fasta":         "annotations/Homo_sapiens/Homo_sapiens.GRCh38.cdna.all.fa",
          "domain_predictions": ["annotations/Homo_sapiens/interproscan.tsv"]
        }
      }
    }

See :ref:`annotations-config-reference` in :doc:`species-annotations` for every
available key.

**Key decision — ``mode``:**

``rebuild``
    Deletes all existing ``transcripts``, ``transcript_features``, and
    ``protein_domains`` rows for each processed species, then re-loads from the
    configured files.  Use this whenever you re-run Stage 1 (because gene IDs
    change) or whenever you have updated annotation files.

``append``
    Adds rows without removing existing data.  Safe to use when you are adding
    domain hits from a *new* domain database (e.g. updating to a new Pfam
    release) without re-processing the GTF.

Step 7 – Run the annotations ingest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Process all species in the config::

    python scripts/ingest_species_annotations.py --config config/my_annotations.json

Process only selected species (useful when testing or adding one new species
without re-loading existing ones)::

    python scripts/ingest_species_annotations.py \
        --config config/my_annotations.json \
        --species Doryteuthis_pealeii_20250213

Skip large transcript feature tables when disk space is limited::

    python scripts/ingest_species_annotations.py \
        --config config/my_annotations.json \
        --skip-features

Step 8 – Verify annotations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Check that transcripts and domains loaded::

    sqlite3 instance/orthofinder_new.db "
        SELECT s.species_name,
               COUNT(DISTINCT t.transcript_id) AS transcripts,
               COUNT(DISTINCT d.domain_id)     AS domains
        FROM   species s
        LEFT JOIN transcripts t ON t.species_id = s.species_id
        LEFT JOIN protein_domains d ON d.species_id = s.species_id
        GROUP BY s.species_name
        ORDER BY s.species_name;
    "

Check for transcripts that could not be matched to a gene (high numbers may
indicate an ID mismatch — see :doc:`troubleshooting`)::

    sqlite3 instance/orthofinder_new.db "
        SELECT s.species_name,
               COUNT(*) AS unmatched_transcripts
        FROM   transcripts t
        JOIN   species s USING (species_id)
        WHERE  t.gene_id IS NULL
        GROUP BY s.species_name;
    "

Complete example: adding one new species
-----------------------------------------

This example adds *Euprymna berryi* to an existing six-species study.

.. code-block:: bash

    # 1. Add the new protein FASTA alongside the existing ones
    cp /data/euprymna/Euprymna_berryi.pep.fa proteins/Euprymna_berryi.fa

    # 2. Re-run OrthoFinder with all seven species
    orthofinder -f proteins/ -t 16 -a 4 -n Mar25

    # 3. Update the OrthoFinder ingest config
    #    (edit config/my_run.json: input_dir, dataset_name,
    #     and add Euprymna_berryi to forced_clades["Cephalopods"])

    # 4. Rebuild the core database
    python scripts/ingest_orthofinder.py --config config/my_run.json

    # 5. Place annotation files for the new species
    mkdir -p annotations/Euprymna_berryi
    cp /data/euprymna/transcriptome.gtf     annotations/Euprymna_berryi/
    cp /data/euprymna/transcriptome.fa      annotations/Euprymna_berryi/
    cp /data/euprymna/interproscan.tsv      annotations/Euprymna_berryi/

    # 6. Update the annotations config
    #    (add Euprymna_berryi block to config/my_annotations.json)

    # 7. Rebuild annotations for all species
    #    (required because gene IDs changed in the new OrthoFinder run)
    python scripts/ingest_species_annotations.py \
        --config config/my_annotations.json \
        --mode rebuild

    # 8. Restart the web app to pick up the new database
    docker compose restart web

Quick-reference checklist
--------------------------

Use this as a checklist when preparing a new run.

**For every species (required for Stage 1):**

- [ ] Protein FASTA (amino acid sequences, one file per species)
- [ ] Filename is ``{exact_species_name}.fa`` with no spaces
- [ ] Sequence IDs within the file are unique
- [ ] No compressed (``.gz``) files in the OrthoFinder input directory

**For every species (optional, Stage 2):**

- [ ] GTF or GFF3 annotation file (``transcript`` and ``exon``/``CDS`` features)
- [ ] mRNA FASTA (one entry per transcript, matching ``transcript_id`` from GTF)
- [ ] InterProScan TSV (``--output-format TSV --goterms --pathways``)
- [ ] Pfam domtblout (``hmmscan --domtblout``) if running Pfam independently

**Config files:**

- [ ] ``orthofinder_ingest.json``: ``input_dir``, ``dataset_name``, ``mode``,
      ``forced_clades`` updated for new species
- [ ] ``species_annotations.json``: entry for every species with annotation
      files, using the exact ``species_name`` from OrthoFinder
- [ ] Both configs point to the same ``db_path``

**Verification:**

- [ ] ``ingest_runs`` table has a row with non-zero counts
- [ ] All species appear in the ``species`` table
- [ ] ``transcripts`` and ``protein_domains`` row counts are non-zero
- [ ] Unmatched-transcript query returns acceptably low counts
