Data Layout
===========

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
-----

- The ingestor reads ``Phylogenetic_Hierarchical_Orthogroups/N0.tsv`` by default.
  If you use a different orthogroup file, update ``orthogroups_file``.
- ``Species{species_id}.fa`` must match IDs in ``SpeciesIDs.txt``.
- ``Gene_Trees`` is expected by default. To use ``Resolved_Gene_Trees``, override
  ``gene_tree_dir`` in the config.
