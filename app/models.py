#!usr/bin/env python
#from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, ForeignKey

Base = declarative_base()

class Orthogroup(Base):
    __tablename__ = 'orthogroups'
    orthogroup_id = Column(String, primary_key=True)
    gene_tree = Column(String)
    description = Column(String)

class Gene(Base):
    __tablename__ = 'genes'
    gene_id = Column(String, primary_key=True)
    ortho_gene_id = Column(String)
    orthogroup_id = Column(String, ForeignKey('orthogroups.orthogroup_id'))
    species_id = Column(String, ForeignKey('species.species_id'))
    gene_name = Column(String)
    description = Column(String)
    sequence = relationship('Sequence', back_populates='gene', uselist=False, cascade="all, delete-orphan")

class Sequence(Base):
    __tablename__ = 'sequences'
    sequence_idx = Column(String, primary_key=True)
    ortho_id = Column(String)
    species_id = Column(String, ForeignKey('species.species_id'))
    ortho_gene_id = Column(String)
    gene_id = Column(String, ForeignKey('genes.gene_id'))
    protein_sequence = Column(String)
    mrna_sequence = Column(String)
    
    gene = relationship('Gene', back_populates='sequence')

class Species(Base):
    __tablename__ = 'species'
    species_id = Column(Integer, primary_key=True)
    species_name = Column(String)

class GeneKeyLookup(Base):
    __tablename__ = 'gene_key_lookup'
    of_gene_id = Column(String, primary_key=True)
    species_id = Column(Integer, ForeignKey('species.species_id'))
    species_of_index = Column(Integer)
    gene_id = Column(String, ForeignKey('genes.gene_id'))

class IngestRun(Base):
    __tablename__ = 'ingest_runs'
    id = Column(Integer, primary_key=True)
    dataset_name = Column(String)
    input_dir = Column(String)
    created_at = Column(DateTime)
    orthogroups_count = Column(Integer)
    genes_count = Column(Integer)
    sequences_count = Column(Integer)
    gene_trees_count = Column(Integer)
    config_json = Column(Text)


class Transcript(Base):
    """Isoform-level gene records parsed from per-species GTF/GFF3 annotation files.

    Each row represents a single transcript (isoform) for a gene.  The
    ``gene_id`` foreign key links to the ``genes`` table when a match can be
    found; it is NULL for transcripts whose GTF gene identifier cannot be
    reconciled with an OrthoFinder gene ID.

    Genomic coordinates use 1-based inclusive intervals (GTF convention).
    """
    __tablename__ = 'transcripts'

    transcript_id = Column(String, primary_key=True)   # transcript ID from GTF attribute
    gene_id = Column(String, ForeignKey('genes.gene_id'), nullable=True)
    species_id = Column(Integer, ForeignKey('species.species_id'))
    gtf_gene_id = Column(String)         # gene_id attribute as written in the GTF
    transcript_name = Column(String)     # transcript_name attribute if present
    seqname = Column(String)             # chromosome / scaffold name
    source = Column(String)              # GTF source column
    biotype = Column(String)             # transcript_biotype attribute if present
    start = Column(Integer)              # 1-based start
    end = Column(Integer)                # 1-based end (inclusive)
    strand = Column(String(1))           # '+' or '-'
    exon_count = Column(Integer)         # number of exon features for this transcript
    cds_length = Column(Integer)         # summed length of CDS features (nt)
    attributes_json = Column(Text)       # full GTF attribute string stored as JSON

    gene = relationship('Gene', foreign_keys=[gene_id])
    features = relationship('TranscriptFeature', back_populates='transcript',
                            cascade='all, delete-orphan')
    domains = relationship('ProteinDomain', back_populates='transcript')


class TranscriptFeature(Base):
    """Individual exon / CDS / UTR features belonging to a transcript.

    Populated from GTF rows with feature types ``exon``, ``CDS``,
    ``five_prime_utr``, and ``three_prime_utr``.  Storing these as separate
    rows rather than JSON allows SQL range queries (e.g. "find all features
    overlapping position X on scaffold Y").

    Coordinates are 1-based inclusive (GTF convention).
    """
    __tablename__ = 'transcript_features'

    feature_id = Column(Integer, primary_key=True, autoincrement=True)
    transcript_id = Column(String, ForeignKey('transcripts.transcript_id'))
    species_id = Column(Integer, ForeignKey('species.species_id'))
    feature_type = Column(String)   # exon | CDS | five_prime_utr | three_prime_utr
    seqname = Column(String)
    start = Column(Integer)
    end = Column(Integer)
    strand = Column(String(1))
    frame = Column(String(1))       # 0, 1, 2, or '.' for non-CDS features
    score = Column(String)          # GTF score column (often '.')

    transcript = relationship('Transcript', back_populates='features')


class ProteinDomain(Base):
    """Protein domain / functional annotation predictions.

    Populated from InterProScan TSV output or Pfam/HMMER ``--domtblout``
    files.  The ``gene_id`` and ``transcript_id`` foreign keys are set when
    the query sequence ID can be matched to records already in the database;
    both may be NULL for unmatched queries.

    Protein coordinates (``seq_start`` / ``seq_end``) are 1-based inclusive
    (standard InterProScan / HMMER convention).
    """
    __tablename__ = 'protein_domains'

    domain_id = Column(Integer, primary_key=True, autoincrement=True)
    gene_id = Column(String, ForeignKey('genes.gene_id'), nullable=True)
    transcript_id = Column(String, ForeignKey('transcripts.transcript_id'), nullable=True)
    species_id = Column(Integer, ForeignKey('species.species_id'), nullable=True)
    query_id = Column(String)          # original sequence ID used in the domain search
    database = Column(String)          # Pfam | PANTHER | TIGRFAM | SUPERFAMILY | etc.
    domain_accession = Column(String)  # e.g. PF00001, IPR000001
    domain_name = Column(String)       # short domain name / family name
    description = Column(String)       # human-readable description
    seq_start = Column(Integer)        # hit start on the protein sequence
    seq_end = Column(Integer)          # hit end on the protein sequence
    score = Column(Float)              # domain score (bit-score for HMMER)
    evalue = Column(Float)             # e-value
    interpro_accession = Column(String)   # parent IPR accession (InterProScan only)
    interpro_description = Column(String) # parent IPR description (InterProScan only)
    go_terms = Column(Text)            # pipe-separated GO terms (InterProScan only)
    pathways = Column(Text)            # pipe-separated pathway annotations

    gene = relationship('Gene', foreign_keys=[gene_id])
    transcript = relationship('Transcript', back_populates='domains', foreign_keys=[transcript_id])
