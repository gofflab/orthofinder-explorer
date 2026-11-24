"""Pairwise species comparison: gene-family expansions and contractions.

The comparison is reported per orthogroup as three numbers: copies in species
A, copies in species B, and a *reference* copy number taken from every other
species.  The reference lets the client polarise a difference between A and B:
"more copies in A than in B" can be a gain on A's lineage (A exceeds the
reference) or a loss on B's lineage (B falls short of it).
"""

from __future__ import annotations

import numpy as np

from .matrix import reference_stats, species_label, species_short_label


def orthology_classes(a, b):
    """Summarise orthology relationship classes between two species.

    Args:
        a: Array of per-orthogroup gene counts in species A.
        b: Array of per-orthogroup gene counts in species B.

    Returns:
        Dict of class name to a dict with ``orthogroups``, ``genes_a`` and
        ``genes_b``.  Classes are ``one_to_one``, ``one_to_many`` (one in A,
        several in B), ``many_to_one``, ``many_to_many``, ``a_only`` and
        ``b_only``.
    """
    masks = {
        "one_to_one": (a == 1) & (b == 1),
        "one_to_many": (a == 1) & (b > 1),
        "many_to_one": (a > 1) & (b == 1),
        "many_to_many": (a > 1) & (b > 1),
        "a_only": (a > 0) & (b == 0),
        "b_only": (a == 0) & (b > 0),
    }
    return {
        name: {
            "orthogroups": int(mask.sum()),
            "genes_a": int(a[mask].sum()),
            "genes_b": int(b[mask].sum()),
        }
        for name, mask in masks.items()
    }


def compare_species(matrix, column_a, column_b, exclude=()):
    """Compare gene-family copy number between two species.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column_a: Column index of species A.
        column_b: Column index of species B.
        exclude: Column indices to leave out of the reference set.

    Returns:
        Dict with:

        ``a`` / ``b``
            Identity (``name``, ``label``, ``short_label``) plus the number of
            ``orthogroups`` and assigned ``genes`` for each species.
        ``n_reference``
            Number of species in the reference set.
        ``summary``
            Shared / union orthogroup counts and :func:`orthology_classes`.
        ``orthogroups``
            Column-oriented arrays restricted to families present in A or B:
            ``ids``, ``a``, ``b``, ``ref`` (median copy number among reference
            species carrying the family) and ``ref_present`` (how many
            reference species carry it).
    """
    a = matrix.counts[:, column_a]
    b = matrix.counts[:, column_b]
    reference = matrix.other_columns(column_a, column_b, exclude=exclude)
    stats = reference_stats(matrix, reference)
    keep = (a > 0) | (b > 0)

    def describe(column, counts):
        """Build the identity/size block for one species."""
        name = matrix.species_names[column]
        return {
            "name": name,
            "label": species_label(name),
            "short_label": species_short_label(name),
            "orthogroups": int((counts > 0).sum()),
            "genes": int(counts.sum()),
        }

    shared = (a > 0) & (b > 0)
    return {
        "a": describe(column_a, a),
        "b": describe(column_b, b),
        "n_reference": len(reference),
        "summary": {
            "shared": int(shared.sum()),
            "union": int(keep.sum()),
            "genes_a_shared": int(a[shared].sum()),
            "genes_b_shared": int(b[shared].sum()),
            "classes": orthology_classes(a, b),
        },
        "orthogroups": {
            "ids": [str(og) for og in matrix.orthogroup_ids[keep]],
            "a": a[keep].tolist(),
            "b": b[keep].tolist(),
            # Medians of integers are multiples of 0.5; rounding keeps the
            # JSON compact without losing information.
            "ref": np.round(stats["median_present"][keep], 1).tolist(),
            "ref_present": stats["present"][keep].tolist(),
        },
    }


def compare_domain_tables(table_a, table_b, database):
    """Compare protein-domain family sizes between two species.

    Args:
        table_a: Domain family table for species A, as produced by
            :func:`app.analysis.annotations.domain_family_table`.
        table_b: Same for species B.
        database: Domain database to compare (e.g. ``"Pfam"``).

    Returns:
        List of dicts with ``accession``, ``name``, ``description`` and the
        number of genes carrying the domain in each species (``a``, ``b``),
        sorted by total gene count.
    """
    merged = {}
    for key, table in (("a", table_a), ("b", table_b)):
        for row in table:
            if row["database"] != database:
                continue
            entry = merged.setdefault(
                row["accession"],
                {
                    "accession": row["accession"],
                    "name": row["name"],
                    "description": row["description"],
                    "a": 0,
                    "b": 0,
                },
            )
            entry[key] = row["genes"]
            # Prefer whichever species supplies a non-empty description.
            if not entry["description"] and row["description"]:
                entry["description"] = row["description"]
            if not entry["name"] and row["name"]:
                entry["name"] = row["name"]
    return sorted(merged.values(), key=lambda r: (-(r["a"] + r["b"]), r["accession"]))
