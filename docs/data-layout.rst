Data Layout
===========

This page describes the directory structures and file formats expected by both
ingestion scripts.  For a step-by-step walkthrough of preparing and loading a
new dataset, see :doc:`adding-species`.

.. contents:: On this page
   :local:
   :depth: 2

OrthoFinder input files (Stage 1 prerequisite)
-----------------------------------------------

Before running OrthoFinder you must provide one protein FASTA file per species.

Protein FASTA format
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   proteins/
     Homo_sapiens.fa
     Mus_musculus.fa
     Danio_rerio.fa
     Doryteuthis_pealeii_20250213.fa

Requirements:

* Standard FASTA format — ``>`` header line followed by one or more sequence
  lines.
* **Amino acid sequences only.**  OrthoFinder does not accept nucleotide FASTAs
  as species input.
* Sequence IDs (first whitespace-delimited token of the header line) must be
  **unique within each file**.
* The **filename basename** (without extension) becomes the species name stored
  in the database.  Use underscores instead of spaces and avoid special
  characters.  Including a date or assembly version suffix is recommended for
  non-model organisms (e.g. ``Doryteuthis_pealeii_20250213``).
* Do **not** compress files (``.gz``) — OrthoFinder requires plain text input.
* Stop codon characters (``*``) should be removed; OrthoFinder may reject or
  mishandle them.

Example header lines::

    >TP53_HUMAN p53 tumour suppressor
    >gene_1234
    >TRINITY_DN12345_c0_g1_i1.p1 len=423

OrthoFinder output files (required by Stage 1 ingest)
------------------------------------------------------

OrthoFinder writes results to a timestamped subdirectory.  The ingest script
expects all of these files to be present under ``input_dir``:

.. code-block:: text

   Results_XXXX/
     WorkingDirectory/
       SpeciesIDs.txt
       SequenceIDs.txt
       Species0.fa
       Species1.fa
       ...
     Phylogenetic_Hierarchical_Orthogroups/
       N0.tsv
     Species_Tree/
       SpeciesTree_rooted.txt
     Gene_Trees/
       OG0000001_tree.txt
       OG0000002_tree.txt
       ...

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Path (relative to ``Results_XXXX/``)
     - Description
   * - ``WorkingDirectory/SpeciesIDs.txt``
     - Maps OrthoFinder's numeric species index to species names.
       Format: ``N: SpeciesName.fa`` one per line.
   * - ``WorkingDirectory/SequenceIDs.txt``
     - Maps OrthoFinder's ``{species_idx}_{gene_idx}`` tokens to original
       protein FASTA IDs.  Format: ``N_M: gene_id`` one per line.
   * - ``WorkingDirectory/Species{N}.fa``
     - Re-indexed protein FASTA for each species.  The ``{N}`` matches the
       numeric index in ``SpeciesIDs.txt``.
   * - ``Phylogenetic_Hierarchical_Orthogroups/N0.tsv``
     - Wide-format TSV: one row per orthogroup, one column per species,
       comma-separated gene lists in each cell.  This is the ``N0`` (root)
       level of the hierarchical orthogroups.
   * - ``Species_Tree/SpeciesTree_rooted.txt``
     - Rooted species phylogeny in Newick format.  Used to compute the
       clade-anchored species colour map.
   * - ``Gene_Trees/{OG}_tree.txt``
     - Per-orthogroup gene tree in Newick format.  One file per orthogroup.
       If this directory is empty, OrthoFinder's tree inference step did not
       complete.

Notes
~~~~~

- The orthogroup file defaults to ``Phylogenetic_Hierarchical_Orthogroups/N0.tsv``.
  Change ``orthogroups_file`` in the config to use a different level.
- ``Gene_Trees`` is the default gene tree directory.  To use reconciled trees,
  set ``gene_tree_dir`` to ``Resolved_Gene_Trees``.
- All file paths are configurable; the defaults listed above match a standard
  OrthoFinder run.  See :ref:`orthofinder-config-reference` in :doc:`ingest`
  for details.

Per-species annotation files (optional, Stage 2)
-------------------------------------------------

After running the Stage 1 ingest, each species can supply up to three
additional annotation file types.  These files live **outside** the OrthoFinder
results directory and are referenced from a separate config file.

Recommended layout::

    annotations/
      {Species_Name}/
        transcriptome.gtf          # GTF or GFF3 transcript annotation
        transcriptome.fa           # mRNA FASTA (spliced transcript sequences)
        interproscan.tsv           # InterProScan TSV output
        pfam_domtblout.txt         # Pfam hmmscan --domtblout (optional)

The ``{Species_Name}`` subdirectory name **must exactly match** the
``species_name`` stored in the database (i.e. the protein FASTA basename
supplied to OrthoFinder).

GTF / GFF3 annotation
~~~~~~~~~~~~~~~~~~~~~~

A transcript-level annotation file describing the genomic structure of each
isoform.  Both GTF 2.2 and GFF3 are accepted; the parser auto-detects the
format.

Required content:

* ``transcript`` (GTF) or ``mRNA`` (GFF3) feature rows with ``transcript_id``
  and ``gene_id`` attributes.
* ``exon`` and/or ``CDS`` feature rows linked to each transcript.

Ensembl GTF example::

    chr1  ensembl_havana  transcript  11869  14409  .  +  .  gene_id "ENSG00000223972"; transcript_id "ENST00000456328"; transcript_biotype "processed_transcript";
    chr1  ensembl_havana  exon        11869  12227  .  +  .  gene_id "ENSG00000223972"; transcript_id "ENST00000456328";

mRNA FASTA
~~~~~~~~~~

A FASTA file of spliced transcript nucleotide sequences.  The parser uses the
first whitespace-delimited token of each header line as the transcript ID::

    >ENST00000456328.2 cdna chromosome:GRCh38:1:11869:14409:1
    ACGT...

    >TRINITY_DN12345_c0_g1_i1 len=1487
    ACGT...

InterProScan TSV
~~~~~~~~~~~~~~~~

Standard 15-column TSV output from InterProScan (``--output-format TSV``).
Produces domain hits from multiple databases in a single file.

Pfam domtblout
~~~~~~~~~~~~~~

HMMER ``--domtblout`` output from a ``hmmscan`` run against Pfam-A.  Use this
when running Pfam searches independently.

See :doc:`species-annotations` for full format specifications, running
instructions, and the complete config reference.
