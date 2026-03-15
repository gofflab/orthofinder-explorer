"""Tests for scripts/ingest_species_annotations.py.

Each test section covers a distinct subsystem so failures are easy to isolate.
All tests use in-memory SQLite databases (no filesystem writes needed for the
DB layer) and temporary files for FASTA / GTF / domain inputs.
"""

import json
import textwrap
import pytest
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Make repo root importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Base, Gene, Species, Transcript, TranscriptFeature, ProteinDomain
from scripts.ingest_species_annotations import (
    # FASTA
    fasta_generator,
    # GTF
    parse_gtf,
    _is_gff3,
    _parse_gtf_attributes,
    _parse_gff3_attributes,
    # ID matching
    build_gene_lookup,
    match_gene_id,
    # Domain
    parse_interproscan_tsv,
    parse_hmmer_domtblout,
    detect_domain_format,
    parse_domain_file,
    # DB helpers
    ensure_column,
    insert_in_batches,
    clear_species_annotations,
    # Ingestion
    ingest_gtf,
    ingest_mrna_fasta,
    ingest_domains,
    # Config
    load_config,
    merge_config,
    resolve_species_files,
    DEFAULTS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    """In-memory SQLite engine with all tables created."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture()
def seeded_session(session):
    """Session pre-populated with two species and a handful of genes."""
    sp1 = Species(species_id=1, species_name="Homo_sapiens")
    sp2 = Species(species_id=2, species_name="Doryteuthis_pealeii")
    session.add_all([sp1, sp2])

    genes = [
        Gene(gene_id="ENSG00000001", ortho_gene_id="ENSG00000001", species_id=1),
        Gene(gene_id="ENSG00000002", ortho_gene_id="ENSG00000002", species_id=1),
        Gene(gene_id="ENSG00000003.5", ortho_gene_id="ENSG00000003.5", species_id=1),
        Gene(gene_id="DPE_gene_0001", ortho_gene_id="DPE_gene_0001", species_id=2),
    ]
    session.add_all(genes)
    session.commit()
    return session


# ---------------------------------------------------------------------------
# FASTA parser
# ---------------------------------------------------------------------------

class TestFastaGenerator:
    def test_single_entry_single_line(self, tmp_path):
        fa = tmp_path / "test.fa"
        fa.write_text(">seq1\nACGT\n")
        results = list(fasta_generator(fa))
        assert len(results) == 1
        tid, desc, seq = results[0]
        assert tid == "seq1"
        assert seq == "ACGT"
        assert desc == ""

    def test_header_with_description(self, tmp_path):
        fa = tmp_path / "test.fa"
        fa.write_text(">ENST00000456328.2 cdna chromosome:GRCh38 gene:ENSG00000223972\nACGT\n")
        results = list(fasta_generator(fa))
        tid, desc, seq = results[0]
        assert tid == "ENST00000456328.2"
        assert "cdna chromosome:GRCh38" in desc

    def test_multiline_sequence(self, tmp_path):
        fa = tmp_path / "test.fa"
        fa.write_text(">seq1\nACGT\nTTTT\nGGGG\n")
        _, _, seq = list(fasta_generator(fa))[0]
        assert seq == "ACGTTTTTGGGG"

    def test_multiple_entries(self, tmp_path):
        fa = tmp_path / "test.fa"
        fa.write_text(">seq1\nAAAA\n>seq2\nCCCC\n>seq3\nGGGG\n")
        results = list(fasta_generator(fa))
        assert len(results) == 3
        assert results[0][0] == "seq1"
        assert results[1][2] == "CCCC"
        assert results[2][0] == "seq3"

    def test_empty_file(self, tmp_path):
        fa = tmp_path / "empty.fa"
        fa.write_text("")
        assert list(fasta_generator(fa)) == []

    def test_skips_empty_sequences(self, tmp_path):
        fa = tmp_path / "test.fa"
        fa.write_text(">seq1\n>seq2\nACGT\n")
        results = list(fasta_generator(fa))
        # seq1 has no sequence lines; fasta_generator yields it with empty seq
        # then ingest_mrna_fasta skips empty seqs — but generator still yields it
        assert len(results) == 2
        assert results[0][2] == ""
        assert results[1][2] == "ACGT"

    def test_no_trailing_newline(self, tmp_path):
        fa = tmp_path / "test.fa"
        fa.write_text(">seq1\nACGT")
        _, _, seq = list(fasta_generator(fa))[0]
        assert seq == "ACGT"


# ---------------------------------------------------------------------------
# GTF attribute parsing
# ---------------------------------------------------------------------------

class TestGtfAttributeParsing:
    def test_gtf_attributes(self):
        attr = 'gene_id "ENSG00000001"; transcript_id "ENST00000001.3"; gene_name "TP53";'
        result = _parse_gtf_attributes(attr)
        assert result["gene_id"] == "ENSG00000001"
        assert result["transcript_id"] == "ENST00000001.3"
        assert result["gene_name"] == "TP53"

    def test_gtf_attributes_empty(self):
        assert _parse_gtf_attributes("") == {}

    def test_gff3_attributes(self):
        attr = "ID=ENST00000001;Parent=ENSG00000001;biotype=protein_coding"
        result = _parse_gff3_attributes(attr)
        assert result["ID"] == "ENST00000001"
        assert result["Parent"] == "ENSG00000001"
        assert result["biotype"] == "protein_coding"

    def test_gff3_attributes_with_spaces(self):
        attr = "ID=tx1; Parent=gene1; Name=TP53"
        result = _parse_gff3_attributes(attr)
        assert result["ID"] == "tx1"


# ---------------------------------------------------------------------------
# GTF file format detection
# ---------------------------------------------------------------------------

class TestGff3Detection:
    def test_detects_gff3_pragma(self, tmp_path):
        f = tmp_path / "ann.gff3"
        f.write_text("##gff-version 3\nchr1\t.\tgene\t1\t100\t.\t+\t.\tID=gene1\n")
        assert _is_gff3(f) is True

    def test_detects_gtf(self, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text('chr1\t.\ttranscript\t1\t100\t.\t+\t.\tgene_id "G1"; transcript_id "T1";\n')
        assert _is_gff3(f) is False


# ---------------------------------------------------------------------------
# GTF parser: transcript and feature extraction
# ---------------------------------------------------------------------------

GTF_CONTENT = textwrap.dedent("""\
    chr1\tensembl\ttranscript\t1000\t5000\t.\t+\t.\tgene_id "ENSG00000001"; transcript_id "ENST00000001"; transcript_biotype "protein_coding";
    chr1\tensembl\texon\t1000\t1200\t.\t+\t.\tgene_id "ENSG00000001"; transcript_id "ENST00000001";
    chr1\tensembl\texon\t2000\t2500\t.\t+\t.\tgene_id "ENSG00000001"; transcript_id "ENST00000001";
    chr1\tensembl\tCDS\t1050\t1200\t.\t+\t0\tgene_id "ENSG00000001"; transcript_id "ENST00000001";
    chr1\tensembl\tCDS\t2000\t2400\t.\t+\t0\tgene_id "ENSG00000001"; transcript_id "ENST00000001";
    chr1\tensembl\ttranscript\t3000\t8000\t.\t-\t.\tgene_id "ENSG00000002"; transcript_id "ENST00000002"; transcript_biotype "lncRNA";
    chr1\tensembl\texon\t3000\t3300\t.\t-\t.\tgene_id "ENSG00000002"; transcript_id "ENST00000002";
""")

GFF3_CONTENT = textwrap.dedent("""\
    ##gff-version 3
    chr1\t.\tmRNA\t1000\t5000\t.\t+\t.\tID=ENST00000001;Parent=ENSG00000001;biotype=protein_coding
    chr1\t.\texon\t1000\t1200\t.\t+\t.\tParent=ENST00000001
    chr1\t.\tCDS\t1050\t1200\t.\t+\t0\tParent=ENST00000001
""")


class TestParseGtf:
    def test_parses_two_transcripts(self, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        results = list(parse_gtf(f))
        assert len(results) == 2

    def test_transcript_fields(self, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        results = {r[0]["transcript_id"]: r for r in parse_gtf(f)}

        t1 = results["ENST00000001"][0]
        assert t1["gtf_gene_id"] == "ENSG00000001"
        assert t1["biotype"] == "protein_coding"
        assert t1["strand"] == "+"
        assert t1["start"] == 1000
        assert t1["end"] == 5000
        assert t1["exon_count"] == 2

    def test_cds_length_summed(self, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        results = {r[0]["transcript_id"]: r for r in parse_gtf(f)}
        # CDS 1: 1200-1050+1 = 151; CDS 2: 2400-2000+1 = 401 → total 552
        assert results["ENST00000001"][0]["cds_length"] == 151 + 401

    def test_feature_list(self, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        results = {r[0]["transcript_id"]: r for r in parse_gtf(f)}
        feats = results["ENST00000001"][1]
        types = {feat["feature_type"] for feat in feats}
        assert "exon" in types
        assert "CDS" in types
        assert len(feats) == 4  # 2 exons + 2 CDS

    def test_feature_filtering(self, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        results = list(parse_gtf(f, feature_types=["exon"]))
        all_feats = [feat for _, feats in results for feat in feats]
        assert all(feat["feature_type"] == "exon" for feat in all_feats)

    def test_stub_created_without_transcript_row(self, tmp_path):
        """GTF with only exon rows (no transcript row) should still produce a transcript."""
        content = 'chr1\tensembl\texon\t1000\t2000\t.\t+\t.\tgene_id "G1"; transcript_id "T_stub";\n'
        f = tmp_path / "ann.gtf"
        f.write_text(content)
        results = list(parse_gtf(f))
        assert len(results) == 1
        assert results[0][0]["transcript_id"] == "T_stub"

    def test_attributes_stored_as_json(self, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        results = list(parse_gtf(f))
        attrs = json.loads(results[0][0]["attributes_json"])
        assert "transcript_id" in attrs

    def test_parses_gff3(self, tmp_path):
        f = tmp_path / "ann.gff3"
        f.write_text(GFF3_CONTENT)
        results = list(parse_gtf(f))
        assert len(results) == 1
        t = results[0][0]
        assert t["transcript_id"] == "ENST00000001"
        assert t["gtf_gene_id"] == "ENSG00000001"


# ---------------------------------------------------------------------------
# Gene ID matching
# ---------------------------------------------------------------------------

class TestGeneIdMatching:
    def test_exact_match(self, seeded_session):
        exact, prefix = build_gene_lookup(seeded_session, species_id=1)
        assert match_gene_id("ENSG00000001", exact, prefix) == "ENSG00000001"

    def test_version_stripped_match(self, seeded_session):
        """ENSG00000003.5 is in the DB; query ENSG00000003 should find it."""
        exact, prefix = build_gene_lookup(seeded_session, species_id=1)
        assert match_gene_id("ENSG00000003", exact, prefix) == "ENSG00000003.5"

    def test_query_with_version_matches_exact(self, seeded_session):
        """ENSG00000003.5 query should match ENSG00000003.5 exactly."""
        exact, prefix = build_gene_lookup(seeded_session, species_id=1)
        assert match_gene_id("ENSG00000003.5", exact, prefix) == "ENSG00000003.5"

    def test_query_with_version_matches_stripped_db_id(self, seeded_session):
        """Query ENSG00000001.12 where DB has ENSG00000001 (no version)."""
        exact, prefix = build_gene_lookup(seeded_session, species_id=1)
        result = match_gene_id("ENSG00000001.12", exact, prefix)
        assert result == "ENSG00000001"

    def test_no_match(self, seeded_session):
        exact, prefix = build_gene_lookup(seeded_session, species_id=1)
        assert match_gene_id("UNKNOWN_XYZ", exact, prefix) is None

    def test_wrong_species_no_match(self, seeded_session):
        """Species 2 genes should not match species 1 lookup."""
        exact, prefix = build_gene_lookup(seeded_session, species_id=1)
        assert match_gene_id("DPE_gene_0001", exact, prefix) is None

    def test_pipe_delimited_stripped(self, seeded_session):
        """gene_id|isoform1 → gene_id lookup."""
        exact, prefix = build_gene_lookup(seeded_session, species_id=1)
        result = match_gene_id("ENSG00000001|variant1", exact, prefix)
        assert result == "ENSG00000001"


# ---------------------------------------------------------------------------
# Domain file parsers
# ---------------------------------------------------------------------------

INTERPROSCAN_TSV = textwrap.dedent("""\
    ENSG00000001\tabcdef1234567890abcdef1234567890\t500\tPfam\tPF00001\tGlobin\t10\t150\t1.5e-20\tT\t15-03-2024\tIPR000001\tGlobin-like\tGO:0005488|GO:0006810\tReactome: R-HSA-1
    ENSG00000001\tabcdef1234567890abcdef1234567890\t500\tPANTHER\tPTHR11111\tPANTHER_FAMILY\t1\t500\t0.0\tT\t15-03-2024\t\t\t\t
    ENSG00000002\tdeadbeef12345678deadbeef12345678\t300\tPfam\tPF00002\tHemoglobin\t5\t200\t2.3e-10\tT\t15-03-2024\tIPR000002\tHemoglobin\t\t
""")

HMMER_DOMTBLOUT = textwrap.dedent("""\
    #                                                                            --- full sequence --- ------------ this domain ------------
    # target name        accession   tlen query name           accession   qlen   E-value  score  bias   #  of  c-Evalue  i-Evalue  score  bias  from    to    from    to    from    to    acc description of target
    # ------------------- ---------- ----- -------------------- ---------- ----- --------- ------ ----- --- --- --------- --------- ------ ----- ----- ----- ----- ----- ----- ----- ---- ---------------------
    Globin                PF00042.21   109 ENSG00000001         -            500   1.4e-27   94.3   0.2   1   1   1.9e-31   1.5e-27   94.0   0.2     1   109    11   116    10   118 0.98 Globin
    Hemoglobin_pi         PF09476.14    35 ENSG00000002         -            300   3.2e-11   40.7   0.0   1   1   4.3e-15   3.4e-11   40.4   0.0     1    35   275   309   274   310 0.97 Hemoglobin pi chain, N-terminal
""")


class TestInterProScanParser:
    def test_parses_three_rows(self, tmp_path):
        f = tmp_path / "ips.tsv"
        f.write_text(INTERPROSCAN_TSV)
        results = list(parse_interproscan_tsv(f))
        assert len(results) == 3

    def test_first_row_fields(self, tmp_path):
        f = tmp_path / "ips.tsv"
        f.write_text(INTERPROSCAN_TSV)
        hit = list(parse_interproscan_tsv(f))[0]
        assert hit["query_id"] == "ENSG00000001"
        assert hit["database"] == "Pfam"
        assert hit["domain_accession"] == "PF00001"
        assert hit["description"] == "Globin"
        assert hit["seq_start"] == 10
        assert hit["seq_end"] == 150
        assert abs(hit["evalue"] - 1.5e-20) < 1e-25
        assert hit["interpro_accession"] == "IPR000001"
        assert "GO:0005488" in hit["go_terms"]
        assert "Reactome" in hit["pathways"]

    def test_missing_optional_columns(self, tmp_path):
        """Row with only 9 columns should not crash."""
        f = tmp_path / "ips.tsv"
        f.write_text("ENSG1\tmd5\t500\tPfam\tPF00001\tGlobin\t10\t150\t1e-5\n")
        results = list(parse_interproscan_tsv(f))
        assert len(results) == 1
        assert results[0]["interpro_accession"] == ""

    def test_skips_comment_lines(self, tmp_path):
        f = tmp_path / "ips.tsv"
        f.write_text("# comment\n" + INTERPROSCAN_TSV)
        results = list(parse_interproscan_tsv(f))
        assert len(results) == 3


class TestHmmerParser:
    def test_parses_two_rows(self, tmp_path):
        f = tmp_path / "pfam.txt"
        f.write_text(HMMER_DOMTBLOUT)
        results = list(parse_hmmer_domtblout(f))
        assert len(results) == 2

    def test_first_row_fields(self, tmp_path):
        f = tmp_path / "pfam.txt"
        f.write_text(HMMER_DOMTBLOUT)
        hit = list(parse_hmmer_domtblout(f))[0]
        assert hit["query_id"] == "ENSG00000001"
        assert hit["database"] == "Pfam"
        assert hit["domain_name"] == "Globin"
        assert hit["domain_accession"] == "PF00042.21"
        assert hit["score"] == pytest.approx(94.0, abs=0.1)
        assert hit["evalue"] == pytest.approx(1.5e-27, rel=0.01)
        # env from/to = cols 19/20
        assert hit["seq_start"] == 10
        assert hit["seq_end"] == 118

    def test_description_captured(self, tmp_path):
        f = tmp_path / "pfam.txt"
        f.write_text(HMMER_DOMTBLOUT)
        hit = list(parse_hmmer_domtblout(f))[0]
        assert "Globin" in hit["description"]

    def test_skips_comment_and_blank_lines(self, tmp_path):
        f = tmp_path / "pfam.txt"
        f.write_text(HMMER_DOMTBLOUT)
        results = list(parse_hmmer_domtblout(f))
        assert len(results) == 2  # comment lines not counted


class TestDetectDomainFormat:
    def test_detects_interproscan(self, tmp_path):
        f = tmp_path / "ips.tsv"
        f.write_text(INTERPROSCAN_TSV)
        assert detect_domain_format(f) == "interproscan"

    def test_detects_hmmer(self, tmp_path):
        f = tmp_path / "pfam.txt"
        f.write_text(HMMER_DOMTBLOUT)
        assert detect_domain_format(f) == "hmmer"

    def test_interproscan_via_comment(self, tmp_path):
        f = tmp_path / "ips.tsv"
        f.write_text("# InterProScan output\n" + INTERPROSCAN_TSV)
        assert detect_domain_format(f) == "interproscan"

    def test_hmmer_via_comment(self, tmp_path):
        f = tmp_path / "pfam.txt"
        f.write_text("# hmmscan :: search a sequence database with a profile database\n" + HMMER_DOMTBLOUT)
        assert detect_domain_format(f) == "hmmer"


# ---------------------------------------------------------------------------
# ensure_column migration helper
# ---------------------------------------------------------------------------

class TestEnsureColumn:
    def test_adds_missing_column(self, engine):
        ensure_column(engine, "transcripts", "new_col", "TEXT")
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(transcripts)"))
            cols = {row[1] for row in result}
        assert "new_col" in cols

    def test_no_op_on_existing_column(self, engine):
        """Should not raise when the column already exists."""
        ensure_column(engine, "transcripts", "transcript_id", "TEXT")  # already there
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(transcripts)"))
            cols = [row[1] for row in result]
        assert cols.count("transcript_id") == 1  # no duplicate

    def test_adds_to_correct_table(self, engine):
        ensure_column(engine, "species", "genome_version", "TEXT")
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(species)"))
            cols = {row[1] for row in result}
        assert "genome_version" in cols
        # Should NOT be in transcripts
        result2 = engine.connect().execute(text("PRAGMA table_info(transcripts)"))
        other_cols = {row[1] for row in result2}
        assert "genome_version" not in other_cols


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    def test_load_config(self, tmp_path):
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text('{"db_path": "mydb.db", "mode": "rebuild"}')
        result = load_config(cfg_file)
        assert result["db_path"] == "mydb.db"

    def test_load_config_none_returns_empty(self):
        assert load_config(None) == {}

    def test_merge_config_override(self):
        merged = merge_config({"a": 1, "b": 2}, {"b": 99, "c": 3})
        assert merged == {"a": 1, "b": 99, "c": 3}

    def test_merge_config_skips_none(self):
        merged = merge_config({"a": 1, "b": 2}, {"b": None})
        assert merged["b"] == 2  # None does not override

    def test_resolve_species_files_per_species(self):
        cfg = {
            "species_annotations": {
                "Homo_sapiens": {
                    "gtf_file": "path/to/human.gtf",
                    "mrna_fasta": "path/to/human.fa",
                    "domain_predictions": ["path/to/human_ips.tsv"],
                }
            },
            "gtf_pattern": None,
            "domain_pattern": None,
            "mrna_pattern": None,
        }
        gtf, domains, mrna = resolve_species_files(cfg, "Homo_sapiens")
        assert gtf == "path/to/human.gtf"
        assert mrna == "path/to/human.fa"
        assert domains == ["path/to/human_ips.tsv"]

    def test_resolve_species_files_pattern_fallback(self):
        cfg = {
            "species_annotations": {},
            "gtf_pattern": "annotations/{species_name}/ann.gtf",
            "domain_pattern": None,
            "mrna_pattern": "annotations/{species_name}/mrna.fa",
        }
        gtf, domains, mrna = resolve_species_files(cfg, "Mus_musculus")
        assert gtf == "annotations/Mus_musculus/ann.gtf"
        assert mrna == "annotations/Mus_musculus/mrna.fa"
        assert domains == []

    def test_resolve_species_files_domain_string_wrapped_in_list(self):
        cfg = {
            "species_annotations": {
                "Homo_sapiens": {
                    "domain_predictions": "single/file.tsv",
                }
            },
            "gtf_pattern": None,
            "domain_pattern": None,
            "mrna_pattern": None,
        }
        _, domains, _ = resolve_species_files(cfg, "Homo_sapiens")
        assert domains == ["single/file.tsv"]


# ---------------------------------------------------------------------------
# Integration: GTF ingestion
# ---------------------------------------------------------------------------

class TestIngestGtf:
    def test_loads_transcripts(self, seeded_session, tmp_path, engine):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        t, feat = ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                              skip_features=False, feature_types=None)
        assert t == 2
        rows = seeded_session.query(Transcript).filter_by(species_id=1).all()
        assert len(rows) == 2

    def test_links_matched_gene(self, seeded_session, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                   skip_features=True, feature_types=None)
        t1 = seeded_session.query(Transcript).filter_by(
            transcript_id="ENST00000001").first()
        assert t1 is not None
        assert t1.gene_id == "ENSG00000001"

    def test_gene_id_null_for_unmatched(self, seeded_session, tmp_path):
        content = 'chr1\tensembl\ttranscript\t1\t100\t.\t+\t.\tgene_id "UNKNOWN_GENE"; transcript_id "TX_UNKNOWN";\n'
        f = tmp_path / "ann.gtf"
        f.write_text(content)
        ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                   skip_features=True, feature_types=None)
        tx = seeded_session.query(Transcript).filter_by(transcript_id="TX_UNKNOWN").first()
        assert tx is not None
        assert tx.gene_id is None

    def test_version_stripped_gene_id_linked(self, seeded_session, tmp_path):
        """GTF gene_id ENSG00000003 should match DB gene ENSG00000003.5."""
        content = 'chr1\tensembl\ttranscript\t1\t100\t.\t+\t.\tgene_id "ENSG00000003"; transcript_id "ENST00000003";\n'
        f = tmp_path / "ann.gtf"
        f.write_text(content)
        ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                   skip_features=True, feature_types=None)
        tx = seeded_session.query(Transcript).filter_by(transcript_id="ENST00000003").first()
        assert tx.gene_id == "ENSG00000003.5"

    def test_loads_features_when_not_skipped(self, seeded_session, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        _, feat_count = ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                                    skip_features=False, feature_types=None)
        assert feat_count > 0
        rows = seeded_session.query(TranscriptFeature).filter_by(species_id=1).all()
        assert len(rows) == feat_count

    def test_skips_features_when_flag_set(self, seeded_session, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        _, feat_count = ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                                    skip_features=True, feature_types=None)
        assert feat_count == 0
        assert seeded_session.query(TranscriptFeature).count() == 0

    def test_transcript_biotype_stored(self, seeded_session, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                   skip_features=True, feature_types=None)
        t1 = seeded_session.query(Transcript).filter_by(transcript_id="ENST00000001").first()
        assert t1.biotype == "protein_coding"
        t2 = seeded_session.query(Transcript).filter_by(transcript_id="ENST00000002").first()
        assert t2.biotype == "lncRNA"

    def test_exon_count_correct(self, seeded_session, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                   skip_features=True, feature_types=None)
        t1 = seeded_session.query(Transcript).filter_by(transcript_id="ENST00000001").first()
        assert t1.exon_count == 2


# ---------------------------------------------------------------------------
# Integration: mRNA FASTA ingestion
# ---------------------------------------------------------------------------

MRNA_FASTA = textwrap.dedent("""\
    >ENST00000001 description text
    ATGATGATG
    CCCCCCC
    >ENST00000002
    GGGGGGG
    >NOVEL_TX_001 novel transcript not in db
    TTTTTTTTT
""")


class TestIngestMrnaFasta:
    def _setup_transcripts(self, session):
        """Add two transcripts without sequences."""
        session.add_all([
            Transcript(transcript_id="ENST00000001", species_id=1,
                       gtf_gene_id="ENSG00000001", gene_id="ENSG00000001",
                       seqname="chr1", source="ensembl", strand="+",
                       start=1000, end=5000, exon_count=2, cds_length=0,
                       attributes_json="{}"),
            Transcript(transcript_id="ENST00000002", species_id=1,
                       gtf_gene_id="ENSG00000002", gene_id="ENSG00000002",
                       seqname="chr1", source="ensembl", strand="-",
                       start=3000, end=8000, exon_count=1, cds_length=0,
                       attributes_json="{}"),
        ])
        session.commit()

    def test_updates_existing_transcripts(self, seeded_session, engine, tmp_path):
        self._setup_transcripts(seeded_session)
        fa = tmp_path / "mrna.fa"
        fa.write_text(MRNA_FASTA)
        updated, inserted = ingest_mrna_fasta(seeded_session, engine, 1, fa)
        assert updated == 2

    def test_inserts_stub_for_novel_entry(self, seeded_session, engine, tmp_path):
        self._setup_transcripts(seeded_session)
        fa = tmp_path / "mrna.fa"
        fa.write_text(MRNA_FASTA)
        updated, inserted = ingest_mrna_fasta(seeded_session, engine, 1, fa)
        assert inserted == 1
        stub = seeded_session.query(Transcript).filter_by(
            transcript_id="NOVEL_TX_001").first()
        assert stub is not None
        assert stub.source == "mrna_fasta"
        assert stub.seqname is None

    def test_sequence_content_correct(self, seeded_session, engine, tmp_path):
        self._setup_transcripts(seeded_session)
        fa = tmp_path / "mrna.fa"
        fa.write_text(MRNA_FASTA)
        ingest_mrna_fasta(seeded_session, engine, 1, fa)
        seeded_session.expire_all()
        t1 = seeded_session.query(Transcript).filter_by(
            transcript_id="ENST00000001").first()
        assert t1.mrna_sequence == "ATGATGATGCCCCCCC"

    def test_version_stripped_id_matched(self, seeded_session, engine, tmp_path):
        """FASTA header ENST00000001.3 should update transcript ENST00000001."""
        self._setup_transcripts(seeded_session)
        fa = tmp_path / "mrna.fa"
        fa.write_text(">ENST00000001.3\nAAAAAAAA\n")
        updated, inserted = ingest_mrna_fasta(seeded_session, engine, 1, fa)
        assert updated == 1
        assert inserted == 0
        seeded_session.expire_all()
        t1 = seeded_session.query(Transcript).filter_by(
            transcript_id="ENST00000001").first()
        assert t1.mrna_sequence == "AAAAAAAA"

    def test_skips_empty_sequences(self, seeded_session, engine, tmp_path):
        self._setup_transcripts(seeded_session)
        fa = tmp_path / "mrna.fa"
        fa.write_text(">ENST00000001\n\n>ENST00000002\nGGGG\n")
        updated, inserted = ingest_mrna_fasta(seeded_session, engine, 1, fa)
        # ENST00000001 has empty seq → skipped; ENST00000002 updated
        assert updated == 1

    def test_standalone_fasta_no_gtf(self, seeded_session, engine, tmp_path):
        """mRNA FASTA with no prior GTF should insert all entries as stubs."""
        fa = tmp_path / "mrna.fa"
        fa.write_text(">TX_DENOVO_001\nACGTACGT\n>TX_DENOVO_002\nTTTTT\n")
        updated, inserted = ingest_mrna_fasta(seeded_session, engine, 1, fa)
        assert updated == 0
        assert inserted == 2
        tx = seeded_session.query(Transcript).filter_by(
            transcript_id="TX_DENOVO_001").first()
        assert tx.mrna_sequence == "ACGTACGT"
        assert tx.source == "mrna_fasta"


# ---------------------------------------------------------------------------
# Integration: domain ingestion
# ---------------------------------------------------------------------------

class TestIngestDomains:
    def _setup_transcripts(self, session):
        session.add_all([
            Transcript(transcript_id="ENST00000001", species_id=1,
                       gtf_gene_id="ENSG00000001", gene_id="ENSG00000001",
                       seqname="chr1", source="ensembl", strand="+",
                       start=1000, end=5000, exon_count=2, cds_length=0,
                       attributes_json="{}"),
        ])
        session.commit()

    def test_loads_interproscan_domains(self, seeded_session, tmp_path):
        self._setup_transcripts(seeded_session)
        f = tmp_path / "ips.tsv"
        f.write_text(INTERPROSCAN_TSV)
        count = ingest_domains(seeded_session, species_id=1, domain_path=f)
        assert count == 3
        rows = seeded_session.query(ProteinDomain).filter_by(species_id=1).all()
        assert len(rows) == 3

    def test_loads_hmmer_domains(self, seeded_session, tmp_path):
        self._setup_transcripts(seeded_session)
        f = tmp_path / "pfam.txt"
        f.write_text(HMMER_DOMTBLOUT)
        count = ingest_domains(seeded_session, species_id=1, domain_path=f)
        assert count == 2

    def test_domain_linked_to_gene(self, seeded_session, tmp_path):
        self._setup_transcripts(seeded_session)
        f = tmp_path / "ips.tsv"
        f.write_text(INTERPROSCAN_TSV)
        ingest_domains(seeded_session, species_id=1, domain_path=f)
        hit = seeded_session.query(ProteinDomain).filter_by(
            query_id="ENSG00000001").first()
        assert hit.gene_id == "ENSG00000001"

    def test_domain_linked_to_transcript(self, seeded_session, tmp_path):
        """Domain whose query_id matches a transcript_id gets transcript_id set."""
        self._setup_transcripts(seeded_session)
        content = (
            "ENST00000001\t" + "a" * 32 + "\t500\tPfam\tPF00001\tGlobin\t"
            "10\t150\t1e-10\tT\t15-03-2024\tIPR000001\tGlobin\t\t\n"
        )
        f = tmp_path / "ips.tsv"
        f.write_text(content)
        ingest_domains(seeded_session, species_id=1, domain_path=f)
        hit = seeded_session.query(ProteinDomain).first()
        assert hit.transcript_id == "ENST00000001"

    def test_unmatched_query_stored_with_null_ids(self, seeded_session, tmp_path):
        f = tmp_path / "ips.tsv"
        f.write_text(
            "UNKNOWN_SEQ\t" + "b" * 32 + "\t400\tPfam\tPF99999\tUnknown\t"
            "1\t50\t1e-5\tT\t15-03-2024\t\t\t\t\n"
        )
        ingest_domains(seeded_session, species_id=1, domain_path=f)
        hit = seeded_session.query(ProteinDomain).filter_by(
            query_id="UNKNOWN_SEQ").first()
        assert hit is not None
        assert hit.gene_id is None
        assert hit.transcript_id is None

    def test_go_terms_stored(self, seeded_session, tmp_path):
        self._setup_transcripts(seeded_session)
        f = tmp_path / "ips.tsv"
        f.write_text(INTERPROSCAN_TSV)
        ingest_domains(seeded_session, species_id=1, domain_path=f)
        hit = seeded_session.query(ProteinDomain).filter_by(
            domain_accession="PF00001").first()
        assert "GO:0005488" in hit.go_terms


# ---------------------------------------------------------------------------
# Integration: clear_species_annotations
# ---------------------------------------------------------------------------

class TestClearSpeciesAnnotations:
    def test_clears_transcripts_and_features(self, seeded_session, tmp_path):
        f = tmp_path / "ann.gtf"
        f.write_text(GTF_CONTENT)
        ingest_gtf(seeded_session, species_id=1, gtf_path=f,
                   skip_features=False, feature_types=None)

        assert seeded_session.query(Transcript).filter_by(species_id=1).count() > 0
        assert seeded_session.query(TranscriptFeature).filter_by(species_id=1).count() > 0

        clear_species_annotations(seeded_session, species_id=1)

        assert seeded_session.query(Transcript).filter_by(species_id=1).count() == 0
        assert seeded_session.query(TranscriptFeature).filter_by(species_id=1).count() == 0

    def test_clears_domains(self, seeded_session, tmp_path):
        f = tmp_path / "ips.tsv"
        f.write_text(INTERPROSCAN_TSV)
        ingest_domains(seeded_session, species_id=1, domain_path=f)
        assert seeded_session.query(ProteinDomain).filter_by(species_id=1).count() > 0

        clear_species_annotations(seeded_session, species_id=1)
        assert seeded_session.query(ProteinDomain).filter_by(species_id=1).count() == 0

    def test_does_not_affect_other_species(self, seeded_session, tmp_path):
        # Load data for species 2
        sp2_gtf = 'chr1\tensembl\ttranscript\t1\t100\t.\t+\t.\tgene_id "DPE_gene_0001"; transcript_id "DPE_TX_001"; transcript_biotype "protein_coding";\n'
        f = tmp_path / "dpe.gtf"
        f.write_text(sp2_gtf)
        ingest_gtf(seeded_session, species_id=2, gtf_path=f,
                   skip_features=True, feature_types=None)

        # Also load data for species 1
        f2 = tmp_path / "ann.gtf"
        f2.write_text(GTF_CONTENT)
        ingest_gtf(seeded_session, species_id=1, gtf_path=f2,
                   skip_features=True, feature_types=None)

        # Clear only species 1
        clear_species_annotations(seeded_session, species_id=1)

        assert seeded_session.query(Transcript).filter_by(species_id=1).count() == 0
        assert seeded_session.query(Transcript).filter_by(species_id=2).count() == 1


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """Full pipeline: GTF → mRNA FASTA → domains on the same species."""

    def test_full_pipeline(self, seeded_session, engine, tmp_path):
        # 1) GTF
        gtf_f = tmp_path / "ann.gtf"
        gtf_f.write_text(GTF_CONTENT)
        t, feat = ingest_gtf(seeded_session, species_id=1, gtf_path=gtf_f,
                              skip_features=False, feature_types=None)
        assert t == 2

        # 2) mRNA FASTA – updates the 2 loaded transcripts
        fa_f = tmp_path / "mrna.fa"
        fa_f.write_text(">ENST00000001\nATGATGATG\n>ENST00000002\nGGGGGGGG\n")
        upd, ins = ingest_mrna_fasta(seeded_session, engine, 1, fa_f)
        assert upd == 2
        assert ins == 0

        # 3) Domains
        dom_f = tmp_path / "ips.tsv"
        dom_f.write_text(INTERPROSCAN_TSV)
        d = ingest_domains(seeded_session, species_id=1, domain_path=dom_f)
        assert d == 3

        # Validate linked data
        seeded_session.expire_all()
        t1 = seeded_session.query(Transcript).filter_by(
            transcript_id="ENST00000001").first()
        assert t1.mrna_sequence == "ATGATGATG"
        assert t1.gene_id == "ENSG00000001"

        domains = seeded_session.query(ProteinDomain).filter_by(
            gene_id="ENSG00000001").all()
        assert len(domains) > 0
        assert any(d.database == "Pfam" for d in domains)
