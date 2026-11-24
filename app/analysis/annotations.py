"""Annotation statistics: proteins, transcripts, and protein domains.

These summaries describe the *quality and content* of a species' annotation
(Stage 2 tables), complementing the orthogroup-level statistics elsewhere in
the package.  Every function tolerates missing annotation data and returns
None (or an empty structure) rather than raising, because most species will
only have a subset of the optional files loaded.
"""

from __future__ import annotations

from array import array

import numpy as np
import pandas as pd
from sqlalchemy import case, func

from ..models import Gene, Orthogroup, ProteinDomain, Sequence, Transcript
from .species_stats import BREADTH_CLASSES, breadth_class_codes

#: Width (aa) of protein-length histogram bins and the start of the overflow bin.
LENGTH_BIN_WIDTH = 50
LENGTH_MAX = 2000

#: Proteins shorter than this are reported as likely fragments.
SHORT_PROTEIN_AA = 100

#: Pseudo-database name used for InterPro entries aggregated across member DBs.
INTERPRO = "InterPro"

#: Order in which domain databases are preferred when picking a default view
#: or a representative annotation for an orthogroup.
DATABASE_PREFERENCE = (INTERPRO, "Pfam")

#: Placeholder strings that mean "no value" in the domain tables (InterProScan
#: writes "-" for absent InterPro accessions, descriptions and GO terms).
MISSING_VALUES = ("", "-")

#: Rows fetched per round trip when streaming large result sets.
STREAM_BATCH = 20000

#: Upper bound on orthogroups annotated per request (keeps the IN list small).
MAX_ANNOTATION_IDS = 200


def _as_int(value):
    """Coerce a database species id to int.

    Legacy tables declare ``species_id`` as a string column, so SQLite hands
    back ``'5'`` where newer tables return ``5``.

    Args:
        value: Raw value from the database.

    Returns:
        Integer id, or None when the value cannot be interpreted.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Proteins
# ---------------------------------------------------------------------------

def protein_lengths_by_species(session):
    """Load the length of every protein, grouped by species.

    Args:
        session: SQLAlchemy session.

    Returns:
        Dict mapping integer ``species_id`` to a NumPy array of protein
        lengths (aa).  Species without sequences are absent.
    """
    # Stream the rows: there is one per protein in the whole dataset.
    rows = session.query(
        Sequence.species_id, func.length(Sequence.protein_sequence)
    ).yield_per(STREAM_BATCH)
    grouped = {}
    for species_id, length in rows:
        key = _as_int(species_id)
        if key is None:
            continue
        values = grouped.get(key)
        if values is None:
            values = grouped[key] = array("l")
        values.append(length or 0)
    return {key: np.asarray(values, dtype=np.int64) for key, values in grouped.items()}


def length_stats(lengths):
    """Summarise a protein-length distribution.

    Args:
        lengths: Array of protein lengths (aa); may be empty or None.

    Returns:
        Dict with ``count``, ``median``, ``mean``, ``p10``, ``p90``, ``max``,
        ``short_fraction`` (share below :data:`SHORT_PROTEIN_AA`) and
        ``histogram``, a list of ``{"x0", "x1", "count"}`` bins where the last
        bin is open-ended (``x1`` is None).  Returns None when there are no
        proteins.
    """
    if lengths is None or len(lengths) == 0:
        return None
    lengths = np.asarray(lengths)
    edges = np.arange(0, LENGTH_MAX + LENGTH_BIN_WIDTH, LENGTH_BIN_WIDTH)
    counts, _ = np.histogram(lengths[lengths < LENGTH_MAX], bins=edges)
    histogram = [
        {"x0": int(edges[i]), "x1": int(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]
    histogram.append(
        {"x0": LENGTH_MAX, "x1": None, "count": int((lengths >= LENGTH_MAX).sum())}
    )
    return {
        "count": int(lengths.size),
        "median": float(np.median(lengths)),
        "mean": float(lengths.mean()),
        "p10": float(np.percentile(lengths, 10)),
        "p90": float(np.percentile(lengths, 90)),
        "max": int(lengths.max()),
        "short_fraction": float((lengths < SHORT_PROTEIN_AA).mean()),
        "histogram": histogram,
    }


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------

def _binned_counts(values, bins):
    """Count integer values into labelled bins.

    Args:
        values: 1-D array-like of integers.
        bins: Sequence of ``(low, high, label)``; ``high`` None is open-ended.

    Returns:
        List of ``{"label", "count"}`` dicts in bin order.
    """
    values = np.asarray(values)
    result = []
    for low, high, label in bins:
        mask = values >= low
        if high is not None:
            mask &= values <= high
        result.append({"label": label, "count": int(mask.sum())})
    return result


ISOFORM_BINS = tuple((i, i, str(i)) for i in range(1, 6)) + ((6, 10, "6-10"), (11, None, ">10"))
EXON_BINS = tuple((i, i, str(i)) for i in range(1, 11)) + ((11, 20, "11-20"), (21, None, ">20"))


def transcript_stats(session, species_id):
    """Summarise transcript (isoform) annotations for one species.

    Args:
        session: SQLAlchemy session.
        species_id: Integer species id.

    Returns:
        Dict describing transcript counts, isoforms per gene, exon counts,
        CDS length, biotypes and mRNA sequence availability, or None when the
        species has no transcript records.
    """
    rows = (
        session.query(
            Transcript.gene_id,
            Transcript.gtf_gene_id,
            Transcript.biotype,
            Transcript.exon_count,
            Transcript.cds_length,
            case((Transcript.mrna_sequence.isnot(None), 1), else_=0),
        )
        .filter(Transcript.species_id == species_id)
        .all()
    )
    if not rows:
        return None
    frame = pd.DataFrame(
        rows, columns=["gene_id", "gtf_gene_id", "biotype", "exons", "cds", "has_mrna"]
    )
    # Group isoforms by the linked gene when available, else the raw GTF gene.
    gene_key = frame["gene_id"].where(frame["gene_id"].notna(), frame["gtf_gene_id"])
    isoforms = gene_key.dropna().value_counts()
    exons = frame["exons"].dropna()
    exons = exons[exons > 0]
    cds = frame["cds"].dropna()
    cds = cds[cds > 0]
    biotypes = (
        frame["biotype"].fillna("").replace("", "unspecified").value_counts().head(8)
    )
    return {
        "count": int(len(frame)),
        "genes": int(isoforms.size),
        "matched_genes": int(frame["gene_id"].dropna().nunique()),
        "unmatched_transcripts": int(frame["gene_id"].isna().sum()),
        "mean_isoforms": float(isoforms.mean()) if isoforms.size else None,
        "isoform_histogram": _binned_counts(isoforms.to_numpy(), ISOFORM_BINS),
        "with_structure": int(exons.size),
        "exon_histogram": _binned_counts(exons.to_numpy(), EXON_BINS),
        "mono_exonic_fraction": float((exons == 1).mean()) if exons.size else None,
        "median_exons": float(exons.median()) if exons.size else None,
        "coding_transcripts": int(cds.size),
        "median_cds_length": float(cds.median()) if cds.size else None,
        "biotypes": [{"label": str(k), "count": int(v)} for k, v in biotypes.items()],
        "with_mrna": int(frame["has_mrna"].sum()),
    }


# ---------------------------------------------------------------------------
# Protein domains
# ---------------------------------------------------------------------------

def _clean(value):
    """Normalise NULL and placeholder values from the domain tables.

    Args:
        value: Raw column value.

    Returns:
        Empty string for None or any of :data:`MISSING_VALUES`, else ``str``.
    """
    return "" if value is None or value in MISSING_VALUES else str(value)


def iter_domain_hits(session, species_id, batch_size=STREAM_BATCH):
    """Stream one species' protein-domain hits from the database.

    Rows are yielded in batches rather than loaded at once, because a single
    species can carry several hundred thousand InterProScan hits.

    Args:
        session: SQLAlchemy session.
        species_id: Integer species id.
        batch_size: Number of rows fetched per round trip.

    Yields:
        Tuples ``(gid, matched, database, accession, name, description, ipr,
        ipr_description, go_terms)`` where ``gid`` is the linked gene id
        (falling back to the raw query id) and ``matched`` is 1 when the hit
        is linked to a gene.
    """
    query = (
        session.query(
            func.coalesce(ProteinDomain.gene_id, ProteinDomain.query_id),
            case((ProteinDomain.gene_id.isnot(None), 1), else_=0),
            ProteinDomain.database,
            ProteinDomain.domain_accession,
            ProteinDomain.domain_name,
            ProteinDomain.description,
            ProteinDomain.interpro_accession,
            ProteinDomain.interpro_description,
            ProteinDomain.go_terms,
        )
        .filter(ProteinDomain.species_id == species_id)
        .yield_per(batch_size)
    )
    for row in query:
        yield tuple(row)


def domain_profile(rows, n_proteins):
    """Aggregate domain hits into coverage statistics and family sizes.

    Works in a single pass over ``rows`` and keeps only per-family gene sets
    in memory.  Member-database families (Pfam, PANTHER, ...) are reported
    under their own database; hits that carry an InterPro accession are
    additionally rolled up under the pseudo-database :data:`INTERPRO`, which
    gives a view that is comparable across member databases.  InterProScan's
    ``"-"`` placeholders are treated as missing.

    Args:
        rows: Iterable of tuples as produced by :func:`iter_domain_hits`.
        n_proteins: Number of proteins for the species (denominator for
            coverage); may be None or 0.

    Returns:
        Dict with:

        ``summary``
            None when there are no hits, else a dict with ``hits``,
            ``genes_with_domain``, ``coverage`` (share of proteins with >= 1
            hit), ``genes_with_go``, ``unmatched_hits`` and ``databases``
            (per-database ``hits`` and ``genes``, InterPro roll-up first).
        ``families``
            List of ``{"database", "accession", "name", "description",
            "genes"}`` sorted by descending gene count.
        ``annotated``
            Set of gene ids (or raw query ids) with at least one hit.
    """
    gene_index = {}            # gid -> small int, so sets hold ints not strings
    families = {}              # (database, accession) -> [name, description, {genes}]
    database_hits = {}         # database -> hit count
    database_genes = {}        # database -> {genes}
    go_genes = set()
    hits = 0
    unmatched = 0

    def add_family(database, accession, name, description, gene):
        """Record that ``gene`` carries the family ``(database, accession)``."""
        entry = families.get((database, accession))
        if entry is None:
            entry = families[(database, accession)] = [name, description, set()]
        else:
            # Keep the first non-empty name / description seen for the family.
            if not entry[0] and name:
                entry[0] = name
            if not entry[1] and description:
                entry[1] = description
        entry[2].add(gene)

    for gid, matched, database, accession, name, description, ipr, ipr_description, go in rows:
        hits += 1
        unmatched += 0 if matched else 1
        gene = gene_index.setdefault(gid, len(gene_index))
        database = _clean(database) or "unspecified"
        database_hits[database] = database_hits.get(database, 0) + 1
        database_genes.setdefault(database, set()).add(gene)
        accession = _clean(accession)
        if accession:
            add_family(database, accession, _clean(name), _clean(description), gene)
        ipr = _clean(ipr)
        if ipr:
            database_hits[INTERPRO] = database_hits.get(INTERPRO, 0) + 1
            database_genes.setdefault(INTERPRO, set()).add(gene)
            # InterPro entries have no separate short name; reuse the accession.
            add_family(INTERPRO, ipr, ipr, _clean(ipr_description), gene)
        if _clean(go):
            go_genes.add(gene)

    if not hits:
        return {"summary": None, "families": [], "annotated": set()}

    family_rows = sorted(
        (
            {
                "database": database,
                "accession": accession,
                "name": name,
                "description": description,
                "genes": len(genes),
            }
            for (database, accession), (name, description, genes) in families.items()
        ),
        key=lambda r: (-r["genes"], r["database"], r["accession"]),
    )
    databases = sorted(
        (
            {"name": name, "hits": database_hits[name], "genes": len(genes)}
            for name, genes in database_genes.items()
        ),
        # The InterPro roll-up leads; member databases follow by gene coverage.
        key=lambda d: (d["name"] != INTERPRO, -d["genes"], d["name"]),
    )
    summary = {
        "hits": hits,
        "genes_with_domain": len(gene_index),
        "coverage": (len(gene_index) / n_proteins) if n_proteins else None,
        "genes_with_go": len(go_genes),
        "unmatched_hits": unmatched,
        "databases": databases,
    }
    return {"summary": summary, "families": family_rows, "annotated": set(gene_index)}


def preferred_database(databases):
    """Choose the default domain database for display.

    Args:
        databases: Iterable of database names available for a species.

    Returns:
        The first of :data:`DATABASE_PREFERENCE` that is available, else the
        first available name, else None.
    """
    available = list(databases)
    for name in DATABASE_PREFERENCE:
        if name in available:
            return name
    return available[0] if available else None


def domain_coverage_by_class(session, species_id, annotated, matrix, column):
    """Measure domain coverage of genes by how conserved their family is.

    Young or lineage-restricted genes typically have fewer recognisable
    domains; a species-specific class with near-zero coverage is also the
    usual signature of spurious ORFs, so this doubles as a quality check.

    Args:
        session: SQLAlchemy session.
        species_id: Integer species id.
        annotated: Set of gene ids with at least one domain hit (the
            ``annotated`` entry of :func:`domain_profile`).
        matrix: The :class:`~app.analysis.matrix.CountMatrix`.
        column: Column index of the species in ``matrix``.

    Returns:
        List of dicts with ``class`` (one of the breadth classes or
        ``"unassigned"``), ``genes`` and ``with_domain``.
    """
    codes = breadth_class_codes(matrix)
    code_of = dict(zip(matrix.orthogroup_ids.tolist(), codes.tolist()))
    totals = {label: 0 for label in BREADTH_CLASSES}
    hits = {label: 0 for label in BREADTH_CLASSES}
    assigned = set()
    gene_rows = (
        session.query(Gene.gene_id, Gene.orthogroup_id)
        .filter(Gene.species_id == str(species_id))
        .all()
    )
    for gene_id, orthogroup_id in gene_rows:
        assigned.add(gene_id)
        code = code_of.get(orthogroup_id)
        if code is None:
            continue
        label = BREADTH_CLASSES[code]
        totals[label] += 1
        hits[label] += gene_id in annotated
    result = [
        {"class": label, "genes": totals[label], "with_domain": hits[label]}
        for label in BREADTH_CLASSES
    ]
    unassigned = [
        gene_id
        for (gene_id,) in session.query(Sequence.gene_id)
        .filter(Sequence.species_id == str(species_id))
        .all()
        if gene_id not in assigned
    ]
    result.append(
        {
            "class": "unassigned",
            "genes": len(unassigned),
            "with_domain": sum(1 for gene_id in unassigned if gene_id in annotated),
        }
    )
    return result


def orthogroup_annotations(session, orthogroup_ids, max_labels=3):
    """Pick representative domain annotations for a set of orthogroups.

    For each orthogroup the most common domain descriptions are returned,
    preferring InterPro entries, then Pfam, then any other database.

    Args:
        session: SQLAlchemy session.
        orthogroup_ids: Iterable of orthogroup ids (capped at
            :data:`MAX_ANNOTATION_IDS`).
        max_labels: Maximum number of annotations per orthogroup.

    Returns:
        Dict mapping orthogroup id to ``{"description", "labels"}`` where
        ``description`` is the curated orthogroup description (may be empty)
        and ``labels`` is a list of ``{"database", "accession", "label",
        "genes"}`` dicts.  Orthogroups without any information are omitted.
    """
    ids = list(dict.fromkeys(orthogroup_ids))[:MAX_ANNOTATION_IDS]
    if not ids:
        return {}
    result = {}
    for orthogroup_id, description in (
        session.query(Orthogroup.orthogroup_id, Orthogroup.description)
        .filter(Orthogroup.orthogroup_id.in_(ids))
        .all()
    ):
        if description:
            result[orthogroup_id] = {"description": description, "labels": []}

    rows = (
        session.query(
            Gene.orthogroup_id,
            ProteinDomain.database,
            ProteinDomain.domain_accession,
            ProteinDomain.domain_name,
            ProteinDomain.description,
            ProteinDomain.interpro_accession,
            ProteinDomain.interpro_description,
            func.count(func.distinct(ProteinDomain.gene_id)),
        )
        .join(ProteinDomain, ProteinDomain.gene_id == Gene.gene_id)
        .filter(Gene.orthogroup_id.in_(ids))
        .group_by(
            Gene.orthogroup_id,
            ProteinDomain.database,
            ProteinDomain.domain_accession,
            ProteinDomain.interpro_accession,
        )
        .all()
    )

    # candidates[og][(database, accession)] = [label, genes]
    candidates = {}
    for og, database, accession, name, description, ipr, ipr_description, genes in rows:
        per_og = candidates.setdefault(og, {})
        accession, name, description = _clean(accession), _clean(name), _clean(description)
        ipr, ipr_description = _clean(ipr), _clean(ipr_description)
        if ipr:
            entry = per_og.setdefault((INTERPRO, ipr), [ipr_description or ipr, 0])
            # Several member-database hits can map to one InterPro entry; the
            # largest single count is a safe lower bound on genes carrying it.
            entry[1] = max(entry[1], genes)
        if accession:
            label = description or name or accession
            entry = per_og.setdefault((database or "", accession), [label, 0])
            entry[1] = max(entry[1], genes)

    def rank(item):
        """Sort key: preferred databases first, then by gene count."""
        (database, accession), (_, genes) = item
        try:
            priority = DATABASE_PREFERENCE.index(database)
        except ValueError:
            priority = len(DATABASE_PREFERENCE)
        return (priority, -genes, accession)

    for og, per_og in candidates.items():
        ranked = sorted(per_og.items(), key=rank)
        # Stay within the best available database so labels are not redundant.
        best_db = ranked[0][0][0]
        labels = [
            {"database": db, "accession": acc, "label": label, "genes": int(genes)}
            for (db, acc), (label, genes) in ranked
            if db == best_db
        ][:max_labels]
        result.setdefault(og, {"description": "", "labels": []})["labels"] = labels
    return result
