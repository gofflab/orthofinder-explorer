"""Orthogroup x species gene-count matrix.

Every comparative analysis in this package starts from the same table: how
many genes each species contributes to each orthogroup.  Building it requires a
single ``GROUP BY`` over the ``genes`` table, after which all downstream
statistics are vectorised NumPy operations.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import func

from ..models import Gene, Species


def species_label(name):
    """Convert a database species name into a human-readable label.

    Args:
        name: Species name as stored in the database (FASTA basename, e.g.
            ``Octopus_chierchiae``).

    Returns:
        The name with underscores replaced by spaces.
    """
    return (name or "").replace("_", " ").strip()


def species_short_label(name):
    """Abbreviate the genus so labels fit on chart axes.

    Args:
        name: Species name as stored in the database.

    Returns:
        ``"O. chierchiae"`` for ``"Octopus_chierchiae"``; any suffix tokens
        (assembly dates, annotation tags) are preserved.  Single-token names
        are returned unchanged.
    """
    parts = species_label(name).split(" ")
    if len(parts) < 2 or not parts[0]:
        return species_label(name)
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


@dataclass
class CountMatrix:
    """Gene counts per orthogroup (rows) and species (columns).

    Attributes:
        orthogroup_ids: 1-D array of orthogroup identifiers, one per row.
        species_ids: Database ``species_id`` for each column.
        species_names: Database ``species_name`` for each column.
        counts: ``(n_orthogroups, n_species)`` integer array of gene counts.
    """

    orthogroup_ids: np.ndarray
    species_ids: list
    species_names: list
    counts: np.ndarray
    _column_by_name: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        """Index species names so column lookups are O(1)."""
        self._column_by_name = {name: i for i, name in enumerate(self.species_names)}

    @property
    def n_orthogroups(self):
        """Number of orthogroup rows."""
        return int(self.counts.shape[0])

    @property
    def n_species(self):
        """Number of species columns."""
        return int(self.counts.shape[1])

    @property
    def presence(self):
        """Boolean ``(n_orthogroups, n_species)`` array: species has >= 1 gene."""
        return self.counts > 0

    @property
    def breadth(self):
        """Number of species represented in each orthogroup (1-D int array)."""
        return self.presence.sum(axis=1)

    def column(self, species_name):
        """Return the column index for a species name.

        Args:
            species_name: Database species name.

        Returns:
            Zero-based column index.

        Raises:
            KeyError: If the species is not part of the matrix.
        """
        return self._column_by_name[species_name]

    def other_columns(self, *focal, exclude=()):
        """List the reference columns for a comparison.

        Args:
            *focal: Column indices of the species under study.
            exclude: Additional column indices to leave out of the reference
                set (for example a duplicate annotation of the same species).

        Returns:
            Sorted list of the remaining column indices.
        """
        skip = set(focal) | set(exclude)
        return [i for i in range(self.n_species) if i not in skip]


def build_count_matrix(session):
    """Build the orthogroup x species count matrix from the database.

    Genes without an orthogroup assignment are ignored.  Species that have no
    assigned genes still receive an (all-zero) column so they remain visible in
    downstream summaries.

    Args:
        session: SQLAlchemy session bound to the OrthoFinder database.

    Returns:
        A populated :class:`CountMatrix`.
    """
    species_rows = (
        session.query(Species.species_id, Species.species_name)
        .order_by(Species.species_name)
        .all()
    )
    species_ids = [row[0] for row in species_rows]
    species_names = [row[1] for row in species_rows]
    column_of = {sid: i for i, sid in enumerate(species_ids)}

    rows = [
        tuple(row)
        for row in session.query(
            Gene.orthogroup_id, Gene.species_id, func.count(Gene.gene_id)
        )
        .filter(Gene.orthogroup_id.isnot(None))
        .group_by(Gene.orthogroup_id, Gene.species_id)
        .yield_per(20000)
    ]

    orthogroup_ids = sorted({row[0] for row in rows})
    row_of = {og: i for i, og in enumerate(orthogroup_ids)}
    counts = np.zeros((len(orthogroup_ids), len(species_ids)), dtype=np.int32)
    for orthogroup_id, species_id, n_genes in rows:
        # ``genes.species_id`` is declared as a string FK in the legacy model
        # but stores integers, so normalise before the lookup.
        col = column_of.get(species_id)
        if col is None:
            try:
                col = column_of.get(int(species_id))
            except (TypeError, ValueError):
                col = None
        if col is None:
            continue
        counts[row_of[orthogroup_id], col] = n_genes

    return CountMatrix(
        orthogroup_ids=np.array(orthogroup_ids, dtype=object),
        species_ids=species_ids,
        species_names=species_names,
        counts=counts,
    )


def reference_stats(matrix, reference_columns):
    """Summarise copy number across a set of reference species.

    The median is taken only over species that actually carry the family,
    which keeps a patchily distributed single-copy family from looking like an
    expansion in the species that happen to have it.

    Args:
        matrix: The :class:`CountMatrix`.
        reference_columns: Column indices that make up the reference set.

    Returns:
        Dict of 1-D arrays, one value per orthogroup:

        ``present``
            Number of reference species with >= 1 gene.
        ``median_present``
            Median copy number among reference species that have the family
            (0.0 when none do).
        ``mean``
            Mean copy number across all reference species, zeros included.
        ``max``
            Largest copy number in any reference species.
    """
    n = matrix.n_orthogroups
    if not reference_columns:
        zeros = np.zeros(n)
        return {
            "present": np.zeros(n, dtype=int),
            "median_present": zeros,
            "mean": zeros.copy(),
            "max": np.zeros(n, dtype=int),
        }
    ref = matrix.counts[:, reference_columns]
    present = (ref > 0).sum(axis=1)
    masked = np.where(ref > 0, ref, np.nan).astype(float)
    with warnings.catch_warnings():
        # Rows with no reference genes are all-NaN; they become 0.0 below.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        median_present = np.nanmedian(masked, axis=1)
    median_present = np.nan_to_num(median_present, nan=0.0)
    return {
        "present": present,
        "median_present": median_present,
        "mean": ref.mean(axis=1),
        "max": ref.max(axis=1),
    }


def log2_ratio(focal_counts, reference_counts):
    """Pseudocount-stabilised log2 copy-number ratio.

    Args:
        focal_counts: Array of gene counts in the focal species.
        reference_counts: Array of reference copy numbers (same shape).

    Returns:
        ``log2((focal + 1) / (reference + 1))`` as a float array.
    """
    focal = np.asarray(focal_counts, dtype=float)
    reference = np.asarray(reference_counts, dtype=float)
    return np.log2((focal + 1.0) / (reference + 1.0))
