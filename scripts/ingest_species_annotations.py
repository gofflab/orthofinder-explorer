#!/usr/bin/env python
"""Ingest per-species annotation files into the orthofinder-explorer database.

This script is a companion to ``ingest_orthofinder.py``.  It reads annotation
files that exist *outside* the OrthoFinder results directory — primarily:

* **GTF/GFF3 transcriptome annotations** (isoform-level gene structure)
* **Protein domain predictions** (InterProScan TSV or Pfam/HMMER domtblout)

and loads them into the ``transcripts``, ``transcript_features``, and
``protein_domains`` tables.

The database must already be populated by ``ingest_orthofinder.py`` before
running this script.  Species names in the config must match the
``species_name`` values stored in the ``species`` table.

Usage
-----
::

    python scripts/ingest_species_annotations.py \\
        --config config/species_annotations.json \\
        [--db path/to/orthofinder.db] \\
        [--species Homo_sapiens Danio_rerio ...] \\
        [--skip-features] \\
        [--mode rebuild|append]

See ``config/species_annotations.example.json`` for config format details.
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.models import (
    Base,
    Gene,
    ProteinDomain,
    Species,
    Transcript,
    TranscriptFeature,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

DEFAULTS = {
    "db_path": "instance/orthofinder_new.db",
    "mode": "append",
    "skip_features": False,
    "skip_mrna": False,
    "feature_types": ["exon", "CDS", "five_prime_utr", "three_prime_utr"],
    "species_annotations": {},
    # Pattern-based fallbacks (use {species_name} placeholder)
    "gtf_pattern": None,
    "domain_pattern": None,
    "mrna_pattern": None,
}


def load_config(path):
    if not path:
        return {}
    with open(path) as fh:
        return json.load(fh)


def merge_config(base, override):
    merged = dict(base)
    for key, value in override.items():
        if value is not None:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# GTF parsing
# ---------------------------------------------------------------------------

_GTF_ATTR_RE = re.compile(r'(\w+)\s+"([^"]*)"')
_GFF3_ATTR_SPLIT = re.compile(r"[;=]")


def _parse_gtf_attributes(attr_str):
    """Return a dict of key→value pairs from a GTF attribute column."""
    return dict(_GTF_ATTR_RE.findall(attr_str))


def _parse_gff3_attributes(attr_str):
    """Return a dict of key→value pairs from a GFF3 attribute column."""
    parts = [p.strip() for p in attr_str.split(";") if p.strip()]
    result = {}
    for part in parts:
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result


def _is_gff3(path):
    """Peek at the first non-comment line to detect GFF3 vs GTF."""
    with open(path) as fh:
        for line in fh:
            if line.startswith("##gff-version"):
                return True
            if not line.startswith("#"):
                # GTF attribute values are always quoted
                return '="' not in line and "=" in line
    return False


def parse_gtf(gtf_path, feature_types=None, max_rows=None):
    """Parse a GTF or GFF3 file and yield transcript/feature records.

    Yields dicts with keys matching the ``Transcript`` and
    ``TranscriptFeature`` model columns, grouped at the transcript level.

    Parameters
    ----------
    gtf_path:
        Path to a GTF or GFF3 file.
    feature_types:
        Set of feature types to keep for ``TranscriptFeature`` rows.
        Defaults to ``{"exon", "CDS", "five_prime_utr", "three_prime_utr"}``.
    max_rows:
        Optional row limit for testing.

    Yields
    ------
    tuple of (transcript_dict, list[feature_dict])
        One tuple per transcript.  ``feature_dict`` entries correspond to
        ``TranscriptFeature`` columns.
    """
    if feature_types is None:
        feature_types = {"exon", "CDS", "five_prime_utr", "three_prime_utr"}
    else:
        feature_types = set(feature_types)

    is_gff = _is_gff3(gtf_path)
    attr_parser = _parse_gff3_attributes if is_gff else _parse_gtf_attributes

    # Accumulate features per transcript_id
    transcripts = {}   # transcript_id -> transcript dict
    features = {}      # transcript_id -> list of feature dicts
    row_count = 0

    with open(gtf_path) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            if max_rows and row_count >= max_rows:
                break
            row_count += 1

            cols = line.rstrip("\n").split("\t")
            if len(cols) < 9:
                continue

            seqname, source, feature_type, start, end, score, strand, frame, attr_str = cols
            attrs = attr_parser(attr_str)

            # ---- transcript row ------------------------------------------------
            if feature_type == "transcript" or (is_gff and feature_type == "mRNA"):
                tid = attrs.get("transcript_id") or attrs.get("ID", "")
                if not tid:
                    continue
                transcripts[tid] = {
                    "transcript_id": tid,
                    "gtf_gene_id": attrs.get("gene_id") or attrs.get("Parent", ""),
                    "transcript_name": attrs.get("transcript_name", ""),
                    "seqname": seqname,
                    "source": source,
                    "biotype": attrs.get("transcript_biotype")
                              or attrs.get("transcript_type")
                              or attrs.get("biotype", ""),
                    "start": int(start),
                    "end": int(end),
                    "strand": strand,
                    "exon_count": 0,
                    "cds_length": 0,
                    "attributes_json": json.dumps(attrs),
                }
                features.setdefault(tid, [])
                continue

            # ---- feature rows (exon / CDS / UTR) ------------------------------
            if feature_type not in feature_types:
                continue

            tid = attrs.get("transcript_id") or attrs.get("Parent", "")
            if not tid:
                continue

            # Create a stub transcript if we haven't seen a 'transcript' row yet
            # (some GTFs omit the transcript feature line)
            if tid not in transcripts:
                gene_id = attrs.get("gene_id") or attrs.get("gene_id", "")
                transcripts[tid] = {
                    "transcript_id": tid,
                    "gtf_gene_id": gene_id,
                    "transcript_name": attrs.get("transcript_name", ""),
                    "seqname": seqname,
                    "source": source,
                    "biotype": attrs.get("transcript_biotype", ""),
                    "start": int(start),
                    "end": int(end),
                    "strand": strand,
                    "exon_count": 0,
                    "cds_length": 0,
                    "attributes_json": json.dumps(attrs),
                }
                features[tid] = []
            else:
                # Expand transcript bounds if needed
                t = transcripts[tid]
                t["start"] = min(t["start"], int(start))
                t["end"] = max(t["end"], int(end))

            t = transcripts[tid]
            feat_len = int(end) - int(start) + 1

            if feature_type == "exon":
                t["exon_count"] += 1
            if feature_type == "CDS":
                t["cds_length"] += feat_len

            features[tid].append({
                "feature_type": feature_type,
                "seqname": seqname,
                "start": int(start),
                "end": int(end),
                "strand": strand,
                "frame": frame,
                "score": score,
            })

    for tid, t_dict in transcripts.items():
        yield t_dict, features.get(tid, [])


# ---------------------------------------------------------------------------
# mRNA FASTA parsing
# ---------------------------------------------------------------------------

def fasta_generator(fasta_path):
    """Stream sequences from a FASTA file without loading it all into memory.

    Yields (transcript_id, description, sequence) tuples where ``transcript_id``
    is the first whitespace-delimited token of the header line (after ``>``) and
    ``description`` is the remainder of the header line (may be empty).

    Handles both standard single-line and multi-line (wrapped) FASTA.
    """
    current_id = None
    current_desc = ""
    buf = []

    with open(fasta_path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if current_id is not None:
                    yield current_id, current_desc, "".join(buf)
                header = line[1:].strip()
                parts = header.split(None, 1)
                current_id = parts[0]
                current_desc = parts[1] if len(parts) > 1 else ""
                buf = []
            elif line:
                buf.append(line)

    if current_id is not None:
        yield current_id, current_desc, "".join(buf)


# ---------------------------------------------------------------------------
# Domain prediction parsing
# ---------------------------------------------------------------------------

def parse_interproscan_tsv(path):
    """Parse an InterProScan TSV output file (--output-format TSV).

    Yields one dict per line with keys matching ``ProteinDomain`` columns.

    InterProScan TSV columns (tab-separated, 15 fields):
    0  Protein accession
    1  Sequence MD5
    2  Sequence length
    3  Analysis (database name: Pfam, PANTHER, etc.)
    4  Signature accession
    5  Signature description
    6  Start location
    7  Stop location
    8  Score (e-value)
    9  Status (T=true positive)
    10 Date
    11 InterPro accession (optional)
    12 InterPro description (optional)
    13 GO annotations (optional, pipe-separated)
    14 Pathways (optional, pipe-separated)
    """
    with open(path) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 9:
                continue

            def _safe_float(val):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            yield {
                "query_id": cols[0],
                "database": cols[3] if len(cols) > 3 else "",
                "domain_accession": cols[4] if len(cols) > 4 else "",
                "domain_name": cols[4] if len(cols) > 4 else "",
                "description": cols[5] if len(cols) > 5 else "",
                "seq_start": int(cols[6]) if len(cols) > 6 and cols[6].isdigit() else None,
                "seq_end": int(cols[7]) if len(cols) > 7 and cols[7].isdigit() else None,
                "evalue": _safe_float(cols[8]) if len(cols) > 8 else None,
                "score": None,
                "interpro_accession": cols[11] if len(cols) > 11 else "",
                "interpro_description": cols[12] if len(cols) > 12 else "",
                "go_terms": cols[13] if len(cols) > 13 else "",
                "pathways": cols[14] if len(cols) > 14 else "",
            }


def parse_hmmer_domtblout(path):
    """Parse a Pfam/HMMER ``--domtblout`` tabular output file.

    Yields one dict per domain hit with keys matching ``ProteinDomain``
    columns.  Fields follow the ``hmmscan --domtblout`` format:

    Columns (whitespace-separated):
    0   target name (domain/HMM)
    1   target accession
    2   tlen
    3   query name (protein)
    4   query accession
    5   qlen
    6   full-seq E-value
    7   full-seq score
    8   full-seq bias
    9   domain number
    10  total domains
    11  domain c-Evalue
    12  domain i-Evalue
    13  domain score
    14  domain bias
    15  hmm from
    16  hmm to
    17  ali from
    18  ali to
    19  env from
    20  env to
    21  acc
    22+ description (remainder of line)
    """
    with open(path) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.split()
            if len(cols) < 22:
                continue

            def _safe_float(val):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            description = " ".join(cols[22:]) if len(cols) > 22 else ""
            yield {
                "query_id": cols[3],
                "database": "Pfam",
                "domain_accession": cols[1],
                "domain_name": cols[0],
                "description": description,
                "seq_start": int(cols[19]) if cols[19].isdigit() else None,  # env from
                "seq_end": int(cols[20]) if cols[20].isdigit() else None,    # env to
                "score": _safe_float(cols[13]),
                "evalue": _safe_float(cols[12]),
                "interpro_accession": "",
                "interpro_description": "",
                "go_terms": "",
                "pathways": "",
            }


def detect_domain_format(path):
    """Return 'interproscan' or 'hmmer' based on file content."""
    with open(path) as fh:
        for line in fh:
            if line.startswith("#"):
                if "InterProScan" in line:
                    return "interproscan"
                if "hmmscan" in line or "hmmsearch" in line or "HMMER" in line:
                    return "hmmer"
                continue
            # Heuristic: InterProScan TSV has MD5 in column 1
            cols = line.split("\t")
            if len(cols) >= 4 and len(cols[1]) == 32:
                return "interproscan"
            # HMMER domtblout uses space-delimited columns
            return "hmmer"
    return "interproscan"


def parse_domain_file(path):
    """Auto-detect format and yield domain hit dicts."""
    fmt = detect_domain_format(path)
    log.info("  Detected domain file format: %s", fmt)
    if fmt == "interproscan":
        yield from parse_interproscan_tsv(path)
    else:
        yield from parse_hmmer_domtblout(path)


# ---------------------------------------------------------------------------
# Gene ID matching
# ---------------------------------------------------------------------------

def build_gene_lookup(session, species_id):
    """Return two lookup dicts for a species' genes.

    Returns
    -------
    exact : dict[gene_id -> gene_id]
        Exact match (identity map for quick membership test).
    prefix : dict[gene_id_prefix -> gene_id]
        Maps stripped version IDs (e.g. "ENSG00000001") to full gene_id.
        The prefix is the gene_id up to the first dot or pipe character.
    """
    genes = session.query(Gene.gene_id).filter(Gene.species_id == species_id).all()
    exact = {g.gene_id for g in genes}
    prefix = {}
    for g in genes:
        key = re.split(r"[.|]", g.gene_id)[0]
        prefix[key] = g.gene_id
    return exact, prefix


def match_gene_id(query, exact, prefix):
    """Attempt to map a GTF/domain query ID to a gene_id in the database.

    Tries, in order:
    1. Exact match
    2. Strip version suffix (``gene.1`` → ``gene``)
    3. Strip pipe-delimited suffix (``gene|isoform1`` → ``gene``)

    Returns the matched gene_id string or None.
    """
    if query in exact:
        return query
    stripped = re.split(r"[.|]", query)[0]
    if stripped in prefix:
        return prefix[stripped]
    if stripped in exact:
        return stripped
    return None


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def get_or_create_species(session, species_name):
    sp = session.query(Species).filter_by(species_name=species_name).first()
    if sp is None:
        raise ValueError(
            f"Species '{species_name}' not found in database. "
            "Run ingest_orthofinder.py first and make sure species names match."
        )
    return sp.species_id


def insert_in_batches(session, objects, batch_size=2000, label="records"):
    total = 0
    batch = []
    for obj in objects:
        batch.append(obj)
        if len(batch) >= batch_size:
            session.bulk_save_objects(batch)
            session.commit()
            total += len(batch)
            log.info("  Inserted %d %s so far…", total, label)
            batch = []
    if batch:
        session.bulk_save_objects(batch)
        session.commit()
        total += len(batch)
    return total


def ensure_column(engine, table, column, col_type="TEXT"):
    """Add *column* to *table* if it does not already exist.

    SQLite supports ``ALTER TABLE ADD COLUMN`` for nullable columns, so this
    lets us extend an existing database without a full rebuild.  The function
    is a no-op when the column is already present.
    """
    with engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result}
    if column not in existing:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            conn.commit()
        log.info("Added column %s.%s to existing database.", table, column)


def clear_species_annotations(session, species_id):
    """Delete existing annotation rows for a species (for rebuild mode)."""
    # Delete in dependency order
    tids = [
        row[0]
        for row in session.execute(
            text("SELECT transcript_id FROM transcripts WHERE species_id = :sid"),
            {"sid": species_id},
        )
    ]
    if tids:
        for i in range(0, len(tids), 500):
            chunk = tids[i : i + 500]
            session.execute(
                text(
                    "DELETE FROM transcript_features WHERE transcript_id IN ("
                    + ",".join(f"'{t}'" for t in chunk)
                    + ")"
                )
            )
        session.execute(
            text("DELETE FROM transcripts WHERE species_id = :sid"), {"sid": species_id}
        )
    session.execute(
        text("DELETE FROM protein_domains WHERE species_id = :sid"), {"sid": species_id}
    )
    session.commit()
    log.info("  Cleared existing annotation rows for species_id=%s", species_id)


# ---------------------------------------------------------------------------
# Per-species ingestion
# ---------------------------------------------------------------------------

def ingest_gtf(session, species_id, gtf_path, skip_features, feature_types):
    """Load transcripts (and optionally features) from a GTF file."""
    log.info("Parsing GTF: %s", gtf_path)

    exact, prefix = build_gene_lookup(session, species_id)

    transcript_objs = []
    feature_objs = []
    unmatched = 0

    for t_dict, feat_list in parse_gtf(gtf_path, feature_types=feature_types):
        gid_match = match_gene_id(t_dict["gtf_gene_id"], exact, prefix)
        if gid_match is None:
            unmatched += 1

        transcript_objs.append(
            Transcript(
                transcript_id=t_dict["transcript_id"],
                gene_id=gid_match,
                species_id=species_id,
                gtf_gene_id=t_dict["gtf_gene_id"],
                transcript_name=t_dict.get("transcript_name", ""),
                seqname=t_dict["seqname"],
                source=t_dict.get("source", ""),
                biotype=t_dict.get("biotype", ""),
                start=t_dict["start"],
                end=t_dict["end"],
                strand=t_dict["strand"],
                exon_count=t_dict.get("exon_count", 0),
                cds_length=t_dict.get("cds_length", 0),
                attributes_json=t_dict.get("attributes_json", "{}"),
            )
        )

        if not skip_features:
            for f in feat_list:
                feature_objs.append(
                    TranscriptFeature(
                        transcript_id=t_dict["transcript_id"],
                        species_id=species_id,
                        feature_type=f["feature_type"],
                        seqname=f["seqname"],
                        start=f["start"],
                        end=f["end"],
                        strand=f["strand"],
                        frame=f.get("frame", "."),
                        score=f.get("score", "."),
                    )
                )

    t_count = insert_in_batches(session, transcript_objs, label="transcripts")
    f_count = insert_in_batches(session, feature_objs, label="transcript_features")

    log.info(
        "  Loaded %d transcripts, %d features (%d transcripts with no gene match)",
        t_count, f_count, unmatched,
    )
    return t_count, f_count


def ingest_domains(session, species_id, domain_path):
    """Load protein domain predictions from an InterProScan or HMMER file."""
    log.info("Parsing domain file: %s", domain_path)

    # Build lookup: query_id -> (gene_id, transcript_id)
    exact_genes, prefix_genes = build_gene_lookup(session, species_id)
    transcript_map = {
        row[0]: row[0]
        for row in session.execute(
            text("SELECT transcript_id FROM transcripts WHERE species_id = :sid"),
            {"sid": species_id},
        )
    }

    domain_objs = []
    unmatched = 0

    for hit in parse_domain_file(domain_path):
        qid = hit["query_id"]
        gene_match = match_gene_id(qid, exact_genes, prefix_genes)
        tx_match = transcript_map.get(qid) or transcript_map.get(
            re.split(r"[.|]", qid)[0], None
        )
        if gene_match is None and tx_match is None:
            unmatched += 1

        domain_objs.append(
            ProteinDomain(
                gene_id=gene_match,
                transcript_id=tx_match,
                species_id=species_id,
                query_id=qid,
                database=hit.get("database", ""),
                domain_accession=hit.get("domain_accession", ""),
                domain_name=hit.get("domain_name", ""),
                description=hit.get("description", ""),
                seq_start=hit.get("seq_start"),
                seq_end=hit.get("seq_end"),
                score=hit.get("score"),
                evalue=hit.get("evalue"),
                interpro_accession=hit.get("interpro_accession", ""),
                interpro_description=hit.get("interpro_description", ""),
                go_terms=hit.get("go_terms", ""),
                pathways=hit.get("pathways", ""),
            )
        )

    d_count = insert_in_batches(session, domain_objs, label="protein_domains")
    log.info(
        "  Loaded %d domain hits (%d queries with no gene/transcript match)",
        d_count, unmatched,
    )
    return d_count


# ---------------------------------------------------------------------------
# mRNA sequence ingestion
# ---------------------------------------------------------------------------

def _build_transcript_lookup(session, species_id):
    """Return (exact_set, prefix_map) for transcript_ids of a species.

    ``prefix_map`` maps the version-stripped ID to the full transcript_id
    (e.g. ``"ENST00000456328"`` → ``"ENST00000456328.2"``).
    """
    rows = session.execute(
        text("SELECT transcript_id FROM transcripts WHERE species_id = :sid"),
        {"sid": species_id},
    ).fetchall()
    exact = {row[0] for row in rows}
    prefix = {}
    for tid in exact:
        key = re.split(r"[.|]", tid)[0]
        prefix.setdefault(key, tid)
    return exact, prefix


def ingest_mrna_fasta(session, engine, species_id, fasta_path):
    """Load mRNA sequences from a FASTA file into the ``transcripts`` table.

    For each FASTA entry:

    * **Matched transcript** – updates the existing ``Transcript`` row's
      ``mrna_sequence`` field.
    * **Unmatched entry** – inserts a minimal stub ``Transcript`` row
      (coordinates NULL) so the sequence is not silently discarded.  This
      handles *de novo* transcriptomes where no GTF was available.

    The FASTA header's first token is used as the transcript ID.  Version
    suffixes are stripped on a best-effort basis (``ENST00000456328.2`` →
    ``ENST00000456328``) before falling back to stub insertion.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    engine:
        SQLAlchemy engine (used for bulk UPDATE).
    species_id:
        ``species.species_id`` for the target species.
    fasta_path:
        Path to the mRNA FASTA file.

    Returns
    -------
    tuple of (updated_count, inserted_count)
    """
    log.info("Parsing mRNA FASTA: %s", fasta_path)

    exact, prefix = _build_transcript_lookup(session, species_id)

    updates = []   # list of {"tid": ..., "seq": ...}
    stubs = []     # Transcript objects to insert

    for raw_id, desc, seq in fasta_generator(fasta_path):
        if not seq:
            continue

        # Try exact match first, then version-stripped
        if raw_id in exact:
            matched_tid = raw_id
        else:
            stripped = re.split(r"[.|]", raw_id)[0]
            matched_tid = prefix.get(stripped)

        if matched_tid:
            updates.append({"tid": matched_tid, "seq": seq})
        else:
            # Insert a stub transcript so the sequence is preserved
            stubs.append(
                Transcript(
                    transcript_id=raw_id,
                    gene_id=None,
                    species_id=species_id,
                    gtf_gene_id="",
                    transcript_name=desc[:255] if desc else "",
                    seqname=None,
                    source="mrna_fasta",
                    biotype="",
                    start=None,
                    end=None,
                    strand=None,
                    exon_count=0,
                    cds_length=0,
                    attributes_json="{}",
                    mrna_sequence=seq,
                )
            )

    # Bulk update existing transcripts
    BATCH = 500
    updated = 0
    with engine.connect() as conn:
        for i in range(0, len(updates), BATCH):
            chunk = updates[i : i + BATCH]
            conn.execute(
                text(
                    "UPDATE transcripts SET mrna_sequence = :seq "
                    "WHERE transcript_id = :tid"
                ),
                chunk,
            )
            conn.commit()
            updated += len(chunk)
            if updated % 5000 == 0:
                log.info("  Updated %d transcript sequences so far…", updated)

    # Insert stubs for unmatched entries
    inserted = insert_in_batches(session, stubs, label="mrna stub transcripts")

    log.info(
        "  mRNA FASTA: %d sequences updated, %d stub transcripts inserted.",
        updated, inserted,
    )
    return updated, inserted


# ---------------------------------------------------------------------------
# Config resolution: per-species annotation file paths
# ---------------------------------------------------------------------------

def resolve_species_files(cfg, species_name):
    """Return (gtf_path_or_None, list_of_domain_paths, mrna_fasta_or_None) for a species."""
    per_species = cfg.get("species_annotations", {}).get(species_name, {})

    # GTF
    gtf = per_species.get("gtf_file") or (
        cfg["gtf_pattern"].format(species_name=species_name)
        if cfg.get("gtf_pattern")
        else None
    )

    # Domain predictions (may be a single path or a list)
    domain_raw = per_species.get("domain_predictions") or (
        [cfg["domain_pattern"].format(species_name=species_name)]
        if cfg.get("domain_pattern")
        else []
    )
    if isinstance(domain_raw, str):
        domain_raw = [domain_raw]

    # mRNA FASTA
    mrna = per_species.get("mrna_fasta") or (
        cfg["mrna_pattern"].format(species_name=species_name)
        if cfg.get("mrna_pattern")
        else None
    )

    return gtf, domain_raw, mrna


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Ingest per-species GTF and domain annotation files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", "-c", help="Path to species_annotations JSON config")
    parser.add_argument("--db", help="Override db_path from config")
    parser.add_argument(
        "--mode",
        choices=["rebuild", "append"],
        help="rebuild: delete existing annotations first; append: add to existing",
    )
    parser.add_argument(
        "--species", nargs="*", metavar="SPECIES",
        help="Restrict processing to these species (use species_name values from the DB)",
    )
    parser.add_argument(
        "--skip-features", action="store_true",
        help="Parse GTF transcripts but skip loading individual exon/CDS features",
    )
    parser.add_argument(
        "--skip-mrna", action="store_true",
        help="Skip loading mRNA sequences even if mrna_fasta is configured",
    )
    args = parser.parse_args(argv)

    cfg = merge_config(DEFAULTS, load_config(args.config))
    if args.db:
        cfg["db_path"] = args.db
    if args.mode:
        cfg["mode"] = args.mode
    if args.skip_features:
        cfg["skip_features"] = True
    if args.skip_mrna:
        cfg["skip_mrna"] = True

    db_path = Path(cfg["db_path"])
    if not db_path.exists():
        log.error("Database not found: %s", db_path)
        log.error("Run ingest_orthofinder.py first.")
        sys.exit(1)

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)   # create new tables if not present
    # Migrate existing databases that predate the mrna_sequence column
    ensure_column(engine, "transcripts", "mrna_sequence", "TEXT")
    Session = sessionmaker(bind=engine)
    session = Session()

    # Determine which species to process
    all_species = {
        row[0]: row[1]
        for row in session.execute(text("SELECT species_id, species_name FROM species"))
    }
    if args.species:
        wanted = set(args.species)
        unknown = wanted - set(all_species.values())
        if unknown:
            log.warning("Species not found in database (will be skipped): %s", unknown)
    else:
        # Use all species that appear in the config
        wanted = set(cfg.get("species_annotations", {}).keys())
        if cfg.get("gtf_pattern") or cfg.get("domain_pattern"):
            wanted = set(all_species.values())

    # Reverse map: species_name -> species_id
    name_to_id = {v: k for k, v in all_species.items()}

    total_transcripts = 0
    total_features = 0
    total_domains = 0
    total_mrna_updated = 0
    total_mrna_inserted = 0

    for species_name in sorted(wanted):
        if species_name not in name_to_id:
            log.warning("Skipping unknown species: %s", species_name)
            continue

        species_id = name_to_id[species_name]
        log.info("=== Processing species: %s (id=%s) ===", species_name, species_id)

        gtf_path, domain_paths, mrna_path = resolve_species_files(cfg, species_name)

        if not gtf_path and not domain_paths and not mrna_path:
            log.warning("  No annotation files configured for %s, skipping.", species_name)
            continue

        if cfg["mode"] == "rebuild":
            clear_species_annotations(session, species_id)

        if gtf_path:
            p = Path(gtf_path)
            if not p.exists():
                log.warning("  GTF file not found, skipping: %s", p)
            else:
                t, f = ingest_gtf(
                    session, species_id, p,
                    skip_features=cfg["skip_features"],
                    feature_types=cfg.get("feature_types"),
                )
                total_transcripts += t
                total_features += f

        if mrna_path and not cfg.get("skip_mrna"):
            p = Path(mrna_path)
            if not p.exists():
                log.warning("  mRNA FASTA not found, skipping: %s", p)
            else:
                upd, ins = ingest_mrna_fasta(session, engine, species_id, p)
                total_mrna_updated += upd
                total_mrna_inserted += ins
                total_transcripts += ins   # stubs count as new transcripts

        for dp in domain_paths:
            p = Path(dp)
            if not p.exists():
                log.warning("  Domain file not found, skipping: %s", p)
                continue
            d = ingest_domains(session, species_id, p)
            total_domains += d

    log.info(
        "Done.  Loaded %d transcripts (%d mRNA-only stubs), %d features, "
        "%d domain hits; %d existing transcripts had mRNA sequences added.",
        total_transcripts, total_mrna_inserted,
        total_features, total_domains, total_mrna_updated,
    )
    session.close()


if __name__ == "__main__":
    main()
