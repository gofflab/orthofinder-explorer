#!usr/bin/env python
#from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, DateTime, Integer, String, Text, ForeignKey

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
