"""Per-species summaries derived from the orthogroup count matrix.

All functions here are pure: they take a
:class:`~app.analysis.matrix.CountMatrix` (plus plain Python values) and return
JSON-serialisable structures, which keeps them easy to test and to cache.
"""

from __future__ import annotations

import math

import numpy as np

from .matrix import log2_ratio, reference_stats, species_label, species_short_label

#: Share of the *other* species that must carry a family for it to count as
#: "core" when estimating how complete a species' gene set is.
NEAR_UNIVERSAL_FRACTION = 0.9

#: Families found in at most this share of all species are called "narrow".
NARROW_FRACTION = 1.0 / 3.0

#: Conservation classes, ordered from youngest/narrowest to broadest.
BREADTH_CLASSES = ("specific", "narrow", "intermediate", "broad")

#: Copy-number bins as (low, high, label); ``high`` of None means open-ended.
COPY_BINS = (
    (1, 1, "1"),
    (2, 2, "2"),
    (3, 3, "3"),
    (4, 4, "4"),
    (5, 5, "5"),
    (6, 10, "6-10"),
    (11, 20, "11-20"),
    (21, 50, "21-50"),
    (51, None, ">50"),
)

#: Categories accepted by :func:`notable_orthogroups`.
NOTABLE_CATEGORIES = ("specific", "expanded", "contracted", "absent", "stratum")


def breadth_class_codes(matrix):
    """Classify every orthogroup by how widely it is shared across species.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.

    Returns:
        Integer array indexing into :data:`BREADTH_CLASSES`:
        0 = one species only, 1 = narrow (<= 1/3 of species),
        2 = intermediate, 3 = broad (>= 90% of species).
    """
    breadth = matrix.breadth
    fraction = breadth / max(matrix.n_species, 1)
    codes = np.full(matrix.n_orthogroups, 2, dtype=int)
    codes[fraction <= NARROW_FRACTION] = 1
    codes[fraction >= NEAR_UNIVERSAL_FRACTION] = 3
    codes[breadth <= 1] = 0
    return codes


def _core_coverage(matrix, column):
    """Estimate gene-set completeness from near-universal families.

    A family is "core" for the focal species when at least
    :data:`NEAR_UNIVERSAL_FRACTION` of the *other* species carry it.  The
    share of those families that the focal species also carries is a
    BUSCO-like proxy that needs no external lineage dataset.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column: Column index of the focal species.

    Returns:
        Tuple ``(core_total, core_present)``; ``(0, 0)`` when there are no
        other species to define a core set.
    """
    n_other = matrix.n_species - 1
    if n_other < 1:
        return 0, 0
    presence = matrix.presence
    present_other = matrix.breadth - presence[:, column]
    threshold = max(1, math.ceil(NEAR_UNIVERSAL_FRACTION * n_other))
    core = present_other >= threshold
    return int(core.sum()), int((core & presence[:, column]).sum())


def species_table(matrix, protein_counts=None):
    """Summarise every species in the dataset.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        protein_counts: Optional mapping of ``species_id`` to the number of
            input proteins.  When given, unassigned-gene counts are derived
            from it; otherwise those fields are None.

    Returns:
        List of dicts, one per species (matrix column order), with identity
        fields (``name``, ``label``, ``short_label``, ``species_id``), gene and
        orthogroup counts, core-family coverage, and per-class gene counts
        under ``classes``.
    """
    protein_counts = protein_counts or {}
    presence = matrix.presence
    breadth = matrix.breadth
    codes = breadth_class_codes(matrix)
    rows = []
    for column, name in enumerate(matrix.species_names):
        focal = matrix.counts[:, column]
        has = presence[:, column]
        specific = has & (breadth == 1)
        assigned = int(focal.sum())
        proteins = protein_counts.get(matrix.species_ids[column])
        # Guard against a sequences table that is smaller than the gene table.
        total = max(proteins, assigned) if proteins is not None else None
        core_total, core_present = _core_coverage(matrix, column)
        rows.append(
            {
                "name": name,
                "label": species_label(name),
                "short_label": species_short_label(name),
                "species_id": matrix.species_ids[column],
                "proteins": total,
                "assigned_genes": assigned,
                "unassigned_genes": (total - assigned) if total is not None else None,
                "pct_assigned": (assigned / total) if total else None,
                "orthogroups": int(has.sum()),
                "species_specific_orthogroups": int(specific.sum()),
                "species_specific_genes": int(focal[specific].sum()),
                "single_copy_orthogroups": int((focal == 1).sum()),
                "multi_copy_orthogroups": int((focal > 1).sum()),
                "largest_family": int(focal.max()) if focal.size else 0,
                "core_total": core_total,
                "core_present": core_present,
                "core_coverage": (core_present / core_total) if core_total else None,
                "classes": {
                    label: int(focal[codes == code].sum())
                    for code, label in enumerate(BREADTH_CLASSES)
                },
            }
        )
    return rows


def breadth_histogram(matrix, column):
    """Count a species' families by how many species share them.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column: Column index of the focal species.

    Returns:
        List of dicts for ``n_species`` = 1..N with the number of
        ``orthogroups`` and focal-species ``genes`` at that breadth.
    """
    focal = matrix.counts[:, column]
    has = focal > 0
    breadth = matrix.breadth
    return [
        {
            "n_species": k,
            "orthogroups": int((has & (breadth == k)).sum()),
            "genes": int(focal[has & (breadth == k)].sum()),
        }
        for k in range(1, matrix.n_species + 1)
    ]


def copy_number_histogram(matrix, column):
    """Bin a species' families by their copy number in that species.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column: Column index of the focal species.

    Returns:
        List of dicts with ``label``, ``orthogroups`` and ``genes`` for each
        bin in :data:`COPY_BINS`.
    """
    focal = matrix.counts[:, column]
    result = []
    for low, high, label in COPY_BINS:
        mask = focal >= low
        if high is not None:
            mask &= focal <= high
        result.append(
            {
                "label": label,
                "orthogroups": int(mask.sum()),
                "genes": int(focal[mask].sum()),
            }
        )
    return result


def shared_with_others(matrix, column):
    """Count families shared between the focal species and each other species.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column: Column index of the focal species.

    Returns:
        List of dicts (matrix column order, focal species omitted) with
        ``shared`` orthogroups, those found only in the focal species
        (``focal_only``) or only in the other (``other_only``) within the
        pair, and the Jaccard index of the two family sets.
    """
    presence = matrix.presence
    has = presence[:, column]
    rows = []
    for other, name in enumerate(matrix.species_names):
        if other == column:
            continue
        other_has = presence[:, other]
        shared = int((has & other_has).sum())
        union = int((has | other_has).sum())
        rows.append(
            {
                "name": name,
                "label": species_label(name),
                "short_label": species_short_label(name),
                "shared": shared,
                "focal_only": int((has & ~other_has).sum()),
                "other_only": int((~has & other_has).sum()),
                "jaccard": (shared / union) if union else 0.0,
            }
        )
    return rows


def shared_matrix(matrix, order=None):
    """Pairwise shared-orthogroup counts for every pair of species.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        order: Optional list of species names giving the row/column order
            (typically species-tree order).  Defaults to matrix order.

    Returns:
        Dict with ``names``, ``labels``, ``short_labels`` and ``counts``, a
        square list-of-lists whose diagonal holds each species' own
        orthogroup count.
    """
    names = [n for n in (order or matrix.species_names) if n in matrix.species_names]
    columns = [matrix.column(n) for n in names]
    presence = matrix.presence[:, columns].astype(np.int64)
    counts = presence.T @ presence
    return {
        "names": names,
        "labels": [species_label(n) for n in names],
        "short_labels": [species_short_label(n) for n in names],
        "counts": counts.tolist(),
    }


def notable_orthogroups(
    matrix,
    column,
    category,
    min_other=3,
    limit=50,
    exclude=(),
    assignment=None,
    stratum=None,
):
    """Rank the orthogroups that stand out for one species.

    Copy number in the focal species is compared against the *reference set*
    (all other species, minus ``exclude``).  The reference copy number is the
    median among reference species that carry the family.

    Categories:

    ``specific``
        Present only in the focal species; ranked by size.
    ``expanded``
        Shared with at least ``min_other`` reference species and at least two
        copies above the reference median; ranked by log2 ratio.
    ``contracted``
        Shared with at least ``min_other`` reference species and at least two
        copies below the reference median; ranked by log2 ratio (ascending).
    ``absent``
        Missing from the focal species but present in at least ``min_other``
        reference species; ranked by how many reference species carry it.
    ``stratum``
        Families assigned to phylostratum ``stratum`` (requires
        ``assignment``); ranked by size.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column: Column index of the focal species.
        category: One of :data:`NOTABLE_CATEGORIES`.
        min_other: Minimum number of reference species that must carry the
            family (ignored for ``specific`` and ``stratum``).
        limit: Maximum number of rows to return.
        exclude: Column indices to drop from the reference set.
        assignment: Per-orthogroup stratum indices (for ``stratum`` only).
        stratum: Stratum index to list (for ``stratum`` only).

    Returns:
        Dict with ``total`` (number of orthogroups matching the category),
        ``n_reference`` (reference set size) and ``rows``, a ranked list of
        dicts describing each orthogroup.

    Raises:
        ValueError: If ``category`` is not recognised.
    """
    if category not in NOTABLE_CATEGORIES:
        raise ValueError(f"Unknown category: {category}")

    reference = matrix.other_columns(column, exclude=exclude)
    stats = reference_stats(matrix, reference)
    focal = matrix.counts[:, column]
    median = stats["median_present"]
    present = stats["present"]
    ratio = log2_ratio(focal, median)
    totals = matrix.counts.sum(axis=1)

    if category == "specific":
        mask = (focal > 0) & (present == 0)
        order = np.lexsort((matrix.orthogroup_ids.astype(str), -focal))
    elif category == "expanded":
        mask = (focal - median >= 2) & (present >= min_other)
        order = np.lexsort((-focal, -ratio))
    elif category == "contracted":
        mask = (focal > 0) & (median - focal >= 2) & (present >= min_other)
        order = np.lexsort((-median, ratio))
    elif category == "absent":
        mask = (focal == 0) & (present >= max(min_other, 1))
        order = np.lexsort((-median, -present))
    else:
        if assignment is None or stratum is None:
            mask = np.zeros(matrix.n_orthogroups, dtype=bool)
        else:
            mask = assignment == stratum
        order = np.lexsort((matrix.orthogroup_ids.astype(str), -focal))

    ranked = order[mask[order]][: max(int(limit), 0)]
    breadth = matrix.breadth
    rows = [
        {
            "orthogroup_id": str(matrix.orthogroup_ids[i]),
            "n_focal": int(focal[i]),
            "n_total": int(totals[i]),
            "n_species": int(breadth[i]),
            "present_other": int(present[i]),
            "median_other": float(median[i]),
            "mean_other": float(stats["mean"][i]),
            "max_other": int(stats["max"][i]),
            "log2_ratio": float(ratio[i]),
            "share": float(focal[i] / totals[i]) if totals[i] else 0.0,
        }
        for i in ranked
    ]
    return {"total": int(mask.sum()), "n_reference": len(reference), "rows": rows}


def orthogroup_profile(matrix, orthogroup_id, order=None):
    """Return one orthogroup's copy number in every species.

    Args:
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        orthogroup_id: Orthogroup identifier.
        order: Optional species-name order for the result (tree order).

    Returns:
        List of dicts with ``name``, ``label``, ``short_label`` and ``count``,
        or None when the orthogroup is not in the matrix.
    """
    matches = np.nonzero(matrix.orthogroup_ids == orthogroup_id)[0]
    if matches.size == 0:
        return None
    row = matrix.counts[matches[0]]
    names = [n for n in (order or matrix.species_names) if n in matrix.species_names]
    return [
        {
            "name": name,
            "label": species_label(name),
            "short_label": species_short_label(name),
            "count": int(row[matrix.column(name)]),
        }
        for name in names
    ]
