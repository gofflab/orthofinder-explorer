Data Layout
===========

OrthoFinder outputs (required)
-------------------------------

Expected Orthofinder output layout under your results directory:

.. code-block:: text

   Results_XXXX/
     Gene_Trees/
     Phylogenetic_Hierarchical_Orthogroups/N0.tsv
     Species_Tree/SpeciesTree_rooted.txt
     WorkingDirectory/SpeciesIDs.txt
     WorkingDirectory/SequenceIDs.txt
     WorkingDirectory/Species{species_id}.fa

Notes
~~~~~

- The ingestor reads ``Phylogenetic_Hierarchical_Orthogroups/N0.tsv`` by default.
  If you use a different orthogroup file, update ``orthogroups_file``.
- ``Species{species_id}.fa`` must match IDs in ``SpeciesIDs.txt``.
- ``Gene_Trees`` is expected by default. To use ``Resolved_Gene_Trees``, override
  ``gene_tree_dir`` in the config.

Per-species annotation files (optional)
-----------------------------------------

After the OrthoFinder ingest, each species can supply additional annotation
files loaded by ``ingest_species_annotations.py``.  These files live outside
the OrthoFinder results directory and are referenced from a separate config
file (see :doc:`species-annotations`).

Recommended layout::

   annotations/
     {Species_Name}/
       transcriptome_annotated.gtf      # GTF or GFF3 transcript annotation
       interproscan.tsv                 # InterProScan TSV output (optional)
       pfam_domtblout.txt               # Pfam hmmscan --domtblout (optional)

The ``{Species_Name}`` directory names must match the ``species_name`` values
stored in the database (i.e. the names from ``SpeciesIDs.txt``).

For pattern-based path resolution use the ``gtf_pattern`` and
``domain_pattern`` config keys with a ``{species_name}`` placeholder::

    "gtf_pattern": "annotations/{species_name}/transcriptome.gtf"

See :doc:`species-annotations` for full details on formats, ingestion options,
and planned future extensions.
