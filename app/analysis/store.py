"""Cached access to the analysis building blocks.

The count matrix and annotation summaries are expensive relative to a page
view but change only when an ingest script runs.  :class:`AnalysisStore`
memoises them per process with a time-to-live, and drops everything as soon
as a cheap "signature" query shows that the database content has changed.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

import numpy as np
from sqlalchemy import func, text

from ..models import IngestRun, ProteinDomain, SpeciesTree, Transcript
from . import annotations, phylostrata, species_stats
from .matrix import build_count_matrix
from .newick import NewickError, leaf_names, parse_newick, prune_to_leaves

#: Seconds between checks of the ingest signature.
SIGNATURE_INTERVAL = 10.0


class TTLCache:
    """Small least-recently-used cache whose entries expire after a TTL.

    Args:
        ttl: Lifetime of an entry in seconds.
        max_entries: Maximum number of entries kept; the least recently used
            entry is evicted first.
    """

    def __init__(self, ttl, max_entries):
        """Create an empty cache (see the class docstring for the arguments)."""
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries = OrderedDict()

    def get(self, key):
        """Return a live cached value.

        Args:
            key: Hashable cache key.

        Returns:
            Tuple ``(hit, value)``; ``hit`` is False when the key is missing
            or expired.
        """
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        stored_at, value = entry
        if time.monotonic() - stored_at > self.ttl:
            del self._entries[key]
            return False, None
        self._entries.move_to_end(key)
        return True, value

    def set(self, key, value):
        """Store a value, evicting the least recently used entry if full.

        Args:
            key: Hashable cache key.
            value: Value to store.
        """
        self._entries[key] = (time.monotonic(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self):
        """Drop every entry."""
        self._entries.clear()


class AnalysisStore:
    """Per-process cache of matrices, trees and annotation summaries.

    Args:
        get_session: Zero-argument callable returning the active SQLAlchemy
            session (for Flask, ``lambda: db.session``).
        ttl: Cache lifetime in seconds.
    """

    def __init__(self, get_session, ttl=1800):
        """Set up empty caches (see the class docstring for the arguments)."""
        self._get_session = get_session
        self._lock = threading.RLock()
        # Light entries: matrix, tree, species table, strata assignments.
        self._light = TTLCache(ttl, max_entries=96)
        # Heavy entries: per-species domain tables (several MB each).
        self._heavy = TTLCache(ttl, max_entries=8)
        self._signature = None
        self._signature_checked = 0.0

    # -- cache plumbing -----------------------------------------------------

    @property
    def session(self):
        """The active SQLAlchemy session."""
        return self._get_session()

    def _read_signature(self):
        """Fingerprint the database content with index-only lookups.

        Returns:
            Tuple that changes whenever an OrthoFinder ingest, an annotation
            ingest or a species-tree load has modified the database.
        """
        session = self.session
        runs = session.query(func.count(IngestRun.id), func.max(IngestRun.created_at)).one()
        return (
            runs[0],
            runs[1],
            session.query(func.max(SpeciesTree.id)).scalar(),
            session.query(func.max(ProteinDomain.domain_id)).scalar(),
            # ``transcripts`` has a text primary key, so use SQLite's rowid.
            session.execute(text("SELECT MAX(rowid) FROM transcripts")).scalar(),
        )

    def _check_signature(self):
        """Invalidate caches when the database content has changed."""
        now = time.monotonic()
        if now - self._signature_checked < SIGNATURE_INTERVAL:
            return
        self._signature_checked = now
        signature = self._read_signature()
        if signature != self._signature:
            self._signature = signature
            self._light.clear()
            self._heavy.clear()

    def _cached(self, key, compute, heavy=False):
        """Return a cached value, computing and storing it on a miss.

        Args:
            key: Hashable cache key.
            compute: Zero-argument callable that produces the value.
            heavy: Store in the small cache reserved for large objects.

        Returns:
            The cached or freshly computed value.
        """
        cache = self._heavy if heavy else self._light
        with self._lock:
            self._check_signature()
            hit, value = cache.get(key)
            if not hit:
                value = compute()
                cache.set(key, value)
            return value

    def clear(self):
        """Drop all cached values (used by tests and after manual reloads)."""
        with self._lock:
            self._light.clear()
            self._heavy.clear()
            self._signature_checked = 0.0

    # -- dataset-level values -------------------------------------------------

    def matrix(self):
        """Return the cached orthogroup x species count matrix."""
        return self._cached("matrix", lambda: build_count_matrix(self.session))

    def dataset(self):
        """Describe the most recent ingest run.

        Returns:
            Dict with ``name`` and ISO-formatted ``created_at``, or None when
            no ingest has been recorded.
        """
        def compute():
            """Read the latest ingest run from the database."""
            run = self.session.query(IngestRun).order_by(IngestRun.id.desc()).first()
            if run is None:
                return None
            return {
                "name": run.dataset_name,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
        return self._cached("dataset", compute)

    def tree(self):
        """Return the species tree pruned to the species in the matrix.

        Returns:
            Nested dict tree, or None when no usable tree has been loaded.
        """
        def compute():
            """Load, parse and prune the most recent species tree."""
            row = self.session.query(SpeciesTree).order_by(SpeciesTree.id.desc()).first()
            if row is None or not row.newick:
                return None
            try:
                parsed = parse_newick(row.newick)
            except NewickError:
                return None
            pruned = prune_to_leaves(parsed, self.matrix().species_names)
            # A tree that shares fewer than two species with the data is useless.
            if not pruned or len(leaf_names(pruned)) < 2:
                return None
            return pruned
        return self._cached("tree", compute)

    def species_order(self):
        """Return species names in display order.

        Tree order is used when a tree is available (species missing from the
        tree are appended alphabetically); otherwise names are alphabetical.
        """
        names = list(self.matrix().species_names)
        tree = self.tree()
        if not tree:
            return names
        ordered = [n for n in leaf_names(tree) if n in names]
        return ordered + [n for n in names if n not in ordered]

    def protein_lengths(self):
        """Return cached protein lengths keyed by integer species id."""
        return self._cached(
            "protein_lengths",
            lambda: annotations.protein_lengths_by_species(self.session),
        )

    def annotation_counts(self):
        """Count Stage 2 annotation records per species.

        Returns:
            Dict with ``transcripts`` and ``domains``, each mapping integer
            species id to a record count.
        """
        def compute():
            """Count annotation records per species for both Stage 2 tables."""
            def counts(model):
                """Return ``{species_id: row count}`` for one annotation table."""
                rows = (
                    self.session.query(model.species_id, func.count())
                    .group_by(model.species_id)
                    .all()
                )
                return {int(sid): int(n) for sid, n in rows if sid is not None}
            return {"transcripts": counts(Transcript), "domains": counts(ProteinDomain)}
        return self._cached("annotation_counts", compute)

    def species_rows(self):
        """Return the per-species summary table in display order.

        Each row from :func:`species_stats.species_table` is extended with the
        median protein length and counts of transcript / domain records.
        """
        def compute():
            """Build the summary table and reorder it for display."""
            matrix = self.matrix()
            lengths = self.protein_lengths()
            counts = self.annotation_counts()
            table = species_stats.species_table(
                matrix, {sid: len(values) for sid, values in lengths.items()}
            )
            by_name = {}
            for row in table:
                values = lengths.get(row["species_id"])
                row["median_protein_length"] = (
                    float(np.median(values)) if values is not None and len(values) else None
                )
                row["transcripts"] = counts["transcripts"].get(row["species_id"], 0)
                row["domain_hits"] = counts["domains"].get(row["species_id"], 0)
                by_name[row["name"]] = row
            return [by_name[name] for name in self.species_order()]
        return self._cached("species_rows", compute)

    # -- species-level values -------------------------------------------------

    def strata(self, species_name):
        """Return phylostrata for a species.

        Args:
            species_name: Database species name.

        Returns:
            Tuple ``(strata, assignment)`` from
            :func:`phylostrata.lineage_strata` and
            :func:`phylostrata.assign_strata`; ``([], None)`` without a tree.
        """
        def compute():
            """Derive the strata and assign every orthogroup to one."""
            matrix = self.matrix()
            strata = phylostrata.lineage_strata(
                self.tree(), species_name, matrix.species_names
            )
            if not strata:
                return [], None
            assignment = phylostrata.assign_strata(
                matrix, matrix.column(species_name), strata
            )
            return strata, assignment
        return self._cached(("strata", species_name), compute)

    def transcript_stats(self, species_id):
        """Return cached transcript statistics for a species id."""
        return self._cached(
            ("transcripts", species_id),
            lambda: annotations.transcript_stats(self.session, species_id),
        )

    def domain_bundle(self, species_name):
        """Return cached protein-domain summaries for a species.

        Args:
            species_name: Database species name.

        Returns:
            Dict with ``summary`` and ``families`` (see
            :func:`annotations.domain_profile`) and ``coverage_by_class``;
            all three are None / empty when the species has no domain
            records.
        """
        def compute():
            """Aggregate the species' domain hits in a single streaming pass."""
            matrix = self.matrix()
            column = matrix.column(species_name)
            species_id = matrix.species_ids[column]
            lengths = self.protein_lengths().get(species_id)
            profile = annotations.domain_profile(
                annotations.iter_domain_hits(self.session, species_id),
                len(lengths) if lengths is not None else 0,
            )
            if profile["summary"] is None:
                return {"summary": None, "families": [], "coverage_by_class": []}
            return {
                "summary": profile["summary"],
                "families": profile["families"],
                "coverage_by_class": annotations.domain_coverage_by_class(
                    self.session, species_id, profile["annotated"], matrix, column
                ),
            }
        return self._cached(("domains", species_name), compute, heavy=True)
