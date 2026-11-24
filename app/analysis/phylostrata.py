"""Gene-age (phylostratigraphy) assignment along a species' lineage.

For a focal species, the species tree defines a series of nested clades from
the root down to the species itself.  Each orthogroup is assigned to the
*youngest* clade that still contains every species represented in the family,
i.e. the most recent common ancestor of the family's members.  Families at the
last stratum are species-specific; families at the first stratum predate the
root of the tree.

This is a presence/absence (Dollo-style) inference: it is sensitive to
incomplete annotations and to mis-clustered genes, so treat individual calls
as hypotheses and the overall distribution as the signal.
"""

from __future__ import annotations

import numpy as np

from .newick import lineage_clades, prune_to_leaves


def lineage_strata(tree, species_name, species_names):
    """Describe the phylostrata along one species' lineage.

    Args:
        tree: Parsed species tree (see :func:`app.analysis.newick.parse_newick`).
        species_name: Focal species.
        species_names: All species present in the count matrix; the tree is
            pruned to this set before strata are derived.

    Returns:
        List of strata ordered from oldest (root) to youngest (the species
        itself).  Each stratum is a dict with:

        ``index``
            Position in the list (0 = root).
        ``clade``
            Species names in the clade at this depth.
        ``joined``
            Species that are in this clade but not in the next, i.e. the
            sister lineage(s) that share families of this age.  Empty for the
            final, species-specific stratum.

        Returns an empty list when no tree is available or the species is not
        in it.
    """
    if not tree:
        return []
    pruned = prune_to_leaves(tree, species_names)
    if not pruned:
        return []
    clades = lineage_clades(pruned, species_name)
    strata = []
    for index, clade in enumerate(clades):
        younger = set(clades[index + 1]) if index + 1 < len(clades) else set()
        joined = [name for name in clade if name not in younger] if younger else []
        strata.append({"index": index, "clade": list(clade), "joined": joined})
    return strata


def assign_strata(matrix, column, strata):
    """Assign each orthogroup containing the focal species to a stratum.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column: Column index of the focal species.
        strata: Output of :func:`lineage_strata`.

    Returns:
        Integer array with one entry per orthogroup: the stratum index for
        orthogroups that contain the focal species, and -1 otherwise (or when
        ``strata`` is empty).
    """
    assignment = np.full(matrix.n_orthogroups, -1, dtype=int)
    if not strata:
        return assignment
    presence = matrix.presence
    has_focal = presence[:, column]
    # Clades are nested, so "family fits inside clade i" is monotone in i and
    # the number of clades a family fits inside gives its stratum directly.
    fits = np.zeros(matrix.n_orthogroups, dtype=int)
    for stratum in strata:
        inside = np.zeros(matrix.n_species, dtype=bool)
        for name in stratum["clade"]:
            inside[matrix.column(name)] = True
        outside_present = presence[:, ~inside].any(axis=1)
        fits += (~outside_present).astype(int)
    assignment[has_focal] = fits[has_focal] - 1
    return assignment


def summarize_strata(matrix, column, strata, assignment):
    """Count orthogroups and genes per stratum for the focal species.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column: Column index of the focal species.
        strata: Output of :func:`lineage_strata`.
        assignment: Output of :func:`assign_strata`.

    Returns:
        List of dicts (oldest first) with ``index``, ``clade_size``,
        ``joined`` (species names), ``orthogroups`` and ``genes``.
    """
    focal = matrix.counts[:, column]
    summary = []
    for stratum in strata:
        mask = assignment == stratum["index"]
        summary.append(
            {
                "index": stratum["index"],
                "clade_size": len(stratum["clade"]),
                "joined": stratum["joined"],
                "orthogroups": int(mask.sum()),
                "genes": int(focal[mask].sum()),
            }
        )
    return summary
