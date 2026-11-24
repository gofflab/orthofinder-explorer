"""Tests for the comparative analyses behind the Species pages.

Most tests run on a tiny hand-built count matrix whose expected statistics can
be worked out by eye (see ``COUNTS`` below).  Database-backed helpers are
tested against an in-memory SQLite session, matching the style of
``test_species_annotations.py``.
"""

import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis import annotations, compare, phylostrata, species_stats
from app.analysis.matrix import (
    CountMatrix,
    build_count_matrix,
    log2_ratio,
    reference_stats,
    species_label,
    species_short_label,
)
from app.analysis.newick import (
    NewickError,
    leaf_names,
    lineage_clades,
    parse_newick,
    prune_to_leaves,
)
from app.analysis.store import AnalysisStore, TTLCache
from app.models import (
    Base,
    Gene,
    IngestRun,
    Orthogroup,
    ProteinDomain,
    Sequence,
    Species,
    SpeciesTree,
    Transcript,
)
from app.schema import ensure_indexes

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SPECIES = ["Sp_a", "Sp_b", "Sp_c", "Sp_d"]
TREE = "(((Sp_a:1,Sp_b:1):1,Sp_c:2):1,Sp_d:3);"

#: Gene counts per orthogroup (rows) for Sp_a, Sp_b, Sp_c, Sp_d (columns).
COUNTS = {
    "OG1": [1, 1, 1, 1],    # universal single copy
    "OG2": [10, 1, 1, 2],   # expanded in Sp_a
    "OG3": [3, 0, 0, 0],    # specific to Sp_a
    "OG4": [0, 2, 2, 1],    # missing from Sp_a, present everywhere else
    "OG5": [1, 6, 5, 7],    # contracted in Sp_a
    "OG6": [2, 3, 0, 0],    # restricted to the Sp_a + Sp_b clade
    "OG7": [0, 0, 4, 0],    # specific to Sp_c
}


@pytest.fixture()
def matrix():
    """Count matrix built directly from ``COUNTS``."""
    return CountMatrix(
        orthogroup_ids=np.array(list(COUNTS), dtype=object),
        species_ids=[0, 1, 2, 3],
        species_names=list(SPECIES),
        counts=np.array(list(COUNTS.values()), dtype=np.int32),
    )


@pytest.fixture()
def engine():
    """In-memory SQLite engine with all tables created."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    """Session populated with the ``COUNTS`` dataset plus annotations.

    Sp_a additionally has one unassigned protein, transcripts for two genes
    and domain hits (including InterProScan-style "-" placeholders).
    """
    sess = sessionmaker(bind=engine)()
    for species_id, name in enumerate(SPECIES):
        sess.add(Species(species_id=species_id, species_name=name))
    sequence_index = 0
    for orthogroup_id, row in COUNTS.items():
        sess.add(Orthogroup(orthogroup_id=orthogroup_id))
        for species_id, n_genes in enumerate(row):
            for copy in range(n_genes):
                gene_id = f"{SPECIES[species_id]}_{orthogroup_id}_{copy}"
                sess.add(Gene(gene_id=gene_id, orthogroup_id=orthogroup_id, species_id=species_id))
                sess.add(Sequence(
                    sequence_idx=str(sequence_index), species_id=species_id,
                    gene_id=gene_id, protein_sequence="M" * (100 * (copy + 1)),
                ))
                sequence_index += 1
    # One Sp_a protein that OrthoFinder left out of every orthogroup.
    sess.add(Sequence(sequence_idx=str(sequence_index), species_id=0,
                      gene_id="Sp_a_orphan", protein_sequence="M" * 50))

    sess.add_all([
        Transcript(transcript_id="t1", gene_id="Sp_a_OG1_0", species_id=0, gtf_gene_id="g1",
                   biotype="protein_coding", exon_count=1, cds_length=300, mrna_sequence="ACGT"),
        Transcript(transcript_id="t2", gene_id="Sp_a_OG1_0", species_id=0, gtf_gene_id="g1",
                   biotype="protein_coding", exon_count=4, cds_length=600),
        Transcript(transcript_id="t3", gene_id="Sp_a_OG2_0", species_id=0, gtf_gene_id="g2",
                   biotype="", exon_count=3, cds_length=900),
        Transcript(transcript_id="t4", gene_id=None, species_id=0, gtf_gene_id="g_unmatched",
                   biotype="lncRNA", exon_count=2, cds_length=0),
    ])

    def hit(gene_id, database, accession, description, ipr="-", ipr_description="-", go="-",
            species_id=0, query_id=None):
        """Build one protein-domain row."""
        return ProteinDomain(
            gene_id=gene_id, species_id=species_id, query_id=query_id or gene_id,
            database=database, domain_accession=accession, domain_name=accession,
            description=description, interpro_accession=ipr,
            interpro_description=ipr_description, go_terms=go, pathways="-",
        )

    sess.add_all([
        hit("Sp_a_OG2_0", "Pfam", "PF00001", "7tm receptor", "IPR000001", "GPCR", "GO:0004930"),
        hit("Sp_a_OG2_1", "Pfam", "PF00001", "7tm receptor", "IPR000001", "GPCR"),
        hit("Sp_a_OG2_1", "PANTHER", "PTHR1", "GPCR family"),
        hit("Sp_a_OG1_0", "Pfam", "PF00002", "Kinase", "IPR000002", "Kinase-like"),
        hit(None, "Pfam", "PF00003", "Orphan domain", query_id="unmatched_query"),
        hit("Sp_b_OG2_0", "Pfam", "PF00001", "7tm receptor", "IPR000001", "GPCR", species_id=1),
    ])
    sess.add(SpeciesTree(newick=TREE, source="test", created_at=datetime(2025, 1, 1)))
    sess.add(IngestRun(dataset_name="test", created_at=datetime(2025, 1, 1)))
    sess.commit()
    yield sess
    sess.close()


# ---------------------------------------------------------------------------
# Newick
# ---------------------------------------------------------------------------

class TestNewick:
    """Newick parsing, pruning and lineage extraction."""

    def test_parses_names_lengths_and_internal_labels(self):
        tree = parse_newick("((A:0.1,B:0.2)N1:0.3,C:0.4)root;")
        assert tree["name"] == "root"
        assert leaf_names(tree) == ["A", "B", "C"]
        clade = tree["children"][0]
        assert clade["name"] == "N1"
        assert clade["length"] == pytest.approx(0.3)
        assert clade["children"][1]["length"] == pytest.approx(0.2)

    def test_handles_quotes_comments_and_missing_semicolon(self):
        tree = parse_newick("('Homo sapiens':1[&support=1],Mus_musculus:1)")
        assert leaf_names(tree) == ["Homo sapiens", "Mus_musculus"]

    def test_support_values_do_not_break_topology(self):
        tree = parse_newick("((A,B)0.98,(C,D)1)")
        assert leaf_names(tree) == ["A", "B", "C", "D"]

    @pytest.mark.parametrize("bad", ["", "   ", "((A,B)", "A,B);"])
    def test_rejects_malformed_input(self, bad):
        with pytest.raises(NewickError):
            parse_newick(bad)

    def test_prune_collapses_unary_nodes(self):
        tree = parse_newick(TREE)
        pruned = prune_to_leaves(tree, ["Sp_a", "Sp_d"])
        assert leaf_names(pruned) == ["Sp_a", "Sp_d"]
        assert len(pruned["children"]) == 2
        # Sp_a's branch absorbs the two collapsed internal branches.
        assert pruned["children"][0]["length"] == pytest.approx(3.0)

    def test_prune_returns_none_without_matches(self):
        assert prune_to_leaves(parse_newick(TREE), ["Unknown"]) is None

    def test_lineage_clades_are_nested_root_to_leaf(self):
        clades = lineage_clades(parse_newick(TREE), "Sp_a")
        assert [len(clade) for clade in clades] == [4, 3, 2, 1]
        assert clades[-1] == ["Sp_a"]
        assert lineage_clades(parse_newick(TREE), "Missing") == []


# ---------------------------------------------------------------------------
# Count matrix
# ---------------------------------------------------------------------------

class TestMatrix:
    """Count-matrix construction and reference statistics."""

    def test_labels(self):
        assert species_label("Octopus_chierchiae") == "Octopus chierchiae"
        assert species_short_label("Octopus_chierchiae") == "O. chierchiae"
        assert species_short_label("Doryteuthis_pealeii_gert") == "D. pealeii gert"
        assert species_short_label("Hydra") == "Hydra"

    def test_build_from_database_matches_expected_counts(self, session):
        built = build_count_matrix(session)
        assert built.species_names == SPECIES
        assert list(built.orthogroup_ids) == sorted(COUNTS)
        for i, orthogroup_id in enumerate(built.orthogroup_ids):
            assert built.counts[i].tolist() == COUNTS[orthogroup_id]

    def test_species_without_genes_keeps_a_column(self, session):
        session.add(Species(species_id=9, species_name="Sp_empty"))
        session.commit()
        built = build_count_matrix(session)
        assert built.counts[:, built.column("Sp_empty")].sum() == 0

    def test_unassigned_genes_are_ignored(self, session):
        session.add(Gene(gene_id="loose", orthogroup_id=None, species_id=0))
        session.commit()
        assert build_count_matrix(session).counts.sum() == sum(map(sum, COUNTS.values()))

    def test_breadth_and_other_columns(self, matrix):
        assert matrix.breadth.tolist() == [4, 4, 1, 3, 4, 2, 1]
        assert matrix.other_columns(0) == [1, 2, 3]
        assert matrix.other_columns(0, 1, exclude=[3]) == [2]
        with pytest.raises(KeyError):
            matrix.column("Nope")

    def test_reference_median_ignores_absent_species(self, matrix):
        stats = reference_stats(matrix, [1, 2, 3])
        by_og = dict(zip(COUNTS, stats["median_present"].tolist()))
        assert by_og["OG2"] == 1.0          # median of 1, 1, 2
        assert by_og["OG6"] == 3.0          # only Sp_b carries it
        assert by_og["OG3"] == 0.0          # nobody else carries it
        assert dict(zip(COUNTS, stats["present"].tolist()))["OG6"] == 1
        assert dict(zip(COUNTS, stats["max"].tolist()))["OG5"] == 7

    def test_reference_stats_with_empty_reference(self, matrix):
        stats = reference_stats(matrix, [])
        assert stats["present"].sum() == 0
        assert stats["median_present"].sum() == 0

    def test_log2_ratio_uses_pseudocount(self):
        assert log2_ratio([3], [0])[0] == pytest.approx(2.0)
        assert log2_ratio([0], [1])[0] == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# Species statistics
# ---------------------------------------------------------------------------

class TestSpeciesStats:
    """Per-species summaries and notable-orthogroup rankings."""

    def test_species_table_for_focal_species(self, matrix):
        row = species_stats.species_table(matrix, {0: 18})[0]
        assert row["name"] == "Sp_a"
        assert row["assigned_genes"] == 17
        assert row["proteins"] == 18
        assert row["unassigned_genes"] == 1
        assert row["pct_assigned"] == pytest.approx(17 / 18)
        assert row["orthogroups"] == 5
        assert row["species_specific_orthogroups"] == 1
        assert row["species_specific_genes"] == 3
        assert row["single_copy_orthogroups"] == 2
        assert row["multi_copy_orthogroups"] == 3
        assert row["largest_family"] == 10
        # Core families are those present in all three other species.
        assert (row["core_total"], row["core_present"]) == (4, 3)
        assert row["core_coverage"] == pytest.approx(0.75)
        assert row["classes"] == {"specific": 3, "narrow": 0, "intermediate": 2, "broad": 12}

    def test_species_table_without_protein_counts(self, matrix):
        row = species_stats.species_table(matrix)[1]
        assert row["proteins"] is None
        assert row["pct_assigned"] is None
        assert row["unassigned_genes"] is None

    def test_class_gene_counts_sum_to_assigned(self, matrix):
        for row in species_stats.species_table(matrix):
            assert sum(row["classes"].values()) == row["assigned_genes"]

    def test_breadth_histogram(self, matrix):
        hist = species_stats.breadth_histogram(matrix, 0)
        assert [h["orthogroups"] for h in hist] == [1, 1, 0, 3]
        assert [h["genes"] for h in hist] == [3, 2, 0, 12]

    def test_copy_number_histogram(self, matrix):
        hist = {h["label"]: h for h in species_stats.copy_number_histogram(matrix, 0)}
        assert hist["1"]["orthogroups"] == 2
        assert hist["2"]["orthogroups"] == 1
        assert hist["3"]["orthogroups"] == 1
        assert hist["6-10"] == {"label": "6-10", "orthogroups": 1, "genes": 10}
        assert sum(h["genes"] for h in hist.values()) == 17

    def test_shared_with_others(self, matrix):
        rows = {r["name"]: r for r in species_stats.shared_with_others(matrix, 0)}
        assert set(rows) == {"Sp_b", "Sp_c", "Sp_d"}
        assert rows["Sp_b"]["shared"] == 4
        assert rows["Sp_b"]["focal_only"] == 1
        assert rows["Sp_b"]["other_only"] == 1
        assert rows["Sp_b"]["jaccard"] == pytest.approx(4 / 6)

    def test_shared_matrix_is_symmetric_and_ordered(self, matrix):
        result = species_stats.shared_matrix(matrix, ["Sp_d", "Sp_a"])
        assert result["names"] == ["Sp_d", "Sp_a"]
        assert result["counts"] == [[4, 3], [3, 5]]

    def test_expanded(self, matrix):
        result = species_stats.notable_orthogroups(matrix, 0, "expanded", min_other=3)
        assert [r["orthogroup_id"] for r in result["rows"]] == ["OG2"]
        row = result["rows"][0]
        assert row["n_focal"] == 10
        assert row["median_other"] == 1.0
        assert row["log2_ratio"] == pytest.approx(math.log2(11 / 2))
        assert row["present_other"] == 3
        assert row["share"] == pytest.approx(10 / 14)
        assert result["n_reference"] == 3

    def test_contracted_and_absent(self, matrix):
        contracted = species_stats.notable_orthogroups(matrix, 0, "contracted", min_other=3)
        assert [r["orthogroup_id"] for r in contracted["rows"]] == ["OG5"]
        absent = species_stats.notable_orthogroups(matrix, 0, "absent", min_other=3)
        assert [r["orthogroup_id"] for r in absent["rows"]] == ["OG4"]
        # Lowering the breadth requirement also admits the Sp_c-only family.
        loose = species_stats.notable_orthogroups(matrix, 0, "absent", min_other=1)
        assert [r["orthogroup_id"] for r in loose["rows"]] == ["OG4", "OG7"]

    def test_specific_respects_reference_exclusions(self, matrix):
        strict = species_stats.notable_orthogroups(matrix, 0, "specific")
        assert [r["orthogroup_id"] for r in strict["rows"]] == ["OG3"]
        # With Sp_b left out, the clade-restricted family counts as specific.
        relaxed = species_stats.notable_orthogroups(matrix, 0, "specific", exclude=[1])
        assert [r["orthogroup_id"] for r in relaxed["rows"]] == ["OG3", "OG6"]
        assert relaxed["n_reference"] == 2

    def test_limit_and_total(self, matrix):
        result = species_stats.notable_orthogroups(matrix, 0, "absent", min_other=1, limit=1)
        assert result["total"] == 2
        assert len(result["rows"]) == 1

    def test_unknown_category(self, matrix):
        with pytest.raises(ValueError):
            species_stats.notable_orthogroups(matrix, 0, "bogus")

    def test_orthogroup_profile(self, matrix):
        profile = species_stats.orthogroup_profile(matrix, "OG2", ["Sp_d", "Sp_a", "Sp_b", "Sp_c"])
        assert [(p["name"], p["count"]) for p in profile] == [
            ("Sp_d", 2), ("Sp_a", 10), ("Sp_b", 1), ("Sp_c", 1),
        ]
        assert species_stats.orthogroup_profile(matrix, "missing") is None


# ---------------------------------------------------------------------------
# Phylostrata
# ---------------------------------------------------------------------------

class TestPhylostrata:
    """Gene-age strata along a species' lineage."""

    def test_strata_follow_the_lineage(self):
        strata = phylostrata.lineage_strata(parse_newick(TREE), "Sp_a", SPECIES)
        assert [len(s["clade"]) for s in strata] == [4, 3, 2, 1]
        assert [s["joined"] for s in strata] == [["Sp_d"], ["Sp_c"], ["Sp_b"], []]

    def test_assignment_dates_each_family(self, matrix):
        strata = phylostrata.lineage_strata(parse_newick(TREE), "Sp_a", SPECIES)
        assignment = dict(zip(COUNTS, phylostrata.assign_strata(matrix, 0, strata).tolist()))
        assert assignment == {
            "OG1": 0, "OG2": 0, "OG5": 0,   # span the root split
            "OG6": 2,                       # Sp_a + Sp_b only
            "OG3": 3,                       # Sp_a only
            "OG4": -1, "OG7": -1,           # Sp_a absent
        }

    def test_summary_counts(self, matrix):
        strata = phylostrata.lineage_strata(parse_newick(TREE), "Sp_a", SPECIES)
        assignment = phylostrata.assign_strata(matrix, 0, strata)
        summary = phylostrata.summarize_strata(matrix, 0, strata, assignment)
        assert [s["orthogroups"] for s in summary] == [3, 0, 1, 1]
        assert [s["genes"] for s in summary] == [12, 0, 2, 3]
        assert sum(s["genes"] for s in summary) == 17

    def test_missing_tree_or_species_gives_no_strata(self, matrix):
        assert phylostrata.lineage_strata(None, "Sp_a", SPECIES) == []
        assert phylostrata.lineage_strata(parse_newick("(X,Y);"), "Sp_a", SPECIES) == []
        assert (phylostrata.assign_strata(matrix, 0, []) == -1).all()

    def test_strata_ignore_species_absent_from_matrix(self):
        tree = parse_newick("(((Sp_a,Sp_b),(Sp_c,Extra)),Sp_d);")
        strata = phylostrata.lineage_strata(tree, "Sp_a", SPECIES)
        assert [len(s["clade"]) for s in strata] == [4, 3, 2, 1]

    def test_stratum_category_lists_members(self, matrix):
        strata = phylostrata.lineage_strata(parse_newick(TREE), "Sp_a", SPECIES)
        assignment = phylostrata.assign_strata(matrix, 0, strata)
        result = species_stats.notable_orthogroups(
            matrix, 0, "stratum", assignment=assignment, stratum=0
        )
        assert [r["orthogroup_id"] for r in result["rows"]] == ["OG2", "OG1", "OG5"]


# ---------------------------------------------------------------------------
# Pairwise comparison
# ---------------------------------------------------------------------------

class TestCompare:
    """Pairwise orthogroup and domain-family comparison."""

    def test_summary_and_classes(self, matrix):
        result = compare.compare_species(matrix, 0, 1)
        assert result["a"]["name"] == "Sp_a" and result["b"]["name"] == "Sp_b"
        assert result["a"]["genes"] == 17 and result["b"]["genes"] == 13
        assert result["n_reference"] == 2
        summary = result["summary"]
        assert (summary["shared"], summary["union"]) == (4, 6)
        classes = {name: c["orthogroups"] for name, c in summary["classes"].items()}
        assert classes == {
            "one_to_one": 1, "one_to_many": 1, "many_to_one": 1,
            "many_to_many": 1, "a_only": 1, "b_only": 1,
        }
        assert summary["classes"]["many_to_one"] == {"orthogroups": 1, "genes_a": 10, "genes_b": 1}

    def test_columnar_orthogroups(self, matrix):
        og = compare.compare_species(matrix, 0, 1)["orthogroups"]
        assert og["ids"] == ["OG1", "OG2", "OG3", "OG4", "OG5", "OG6"]   # OG7 absent from both
        rows = {i: (a, b, ref, n) for i, a, b, ref, n in
                zip(og["ids"], og["a"], og["b"], og["ref"], og["ref_present"])}
        assert rows["OG2"] == (10, 1, 1.5, 2)     # reference median of Sp_c=1, Sp_d=2
        assert rows["OG3"] == (3, 0, 0.0, 0)
        assert rows["OG6"] == (2, 3, 0.0, 0)
        assert rows["OG4"] == (0, 2, 1.5, 2)

    def test_exclusion_shrinks_the_reference(self, matrix):
        og = compare.compare_species(matrix, 0, 1, exclude=[3])
        assert og["n_reference"] == 1
        rows = dict(zip(og["orthogroups"]["ids"], og["orthogroups"]["ref"]))
        assert rows["OG2"] == 1.0

    def test_compare_domain_tables(self):
        table_a = [
            {"database": "Pfam", "accession": "PF1", "name": "a", "description": "", "genes": 5},
            {"database": "Pfam", "accession": "PF2", "name": "b", "description": "B dom", "genes": 1},
            {"database": "PANTHER", "accession": "PT1", "name": "p", "description": "", "genes": 9},
        ]
        table_b = [
            {"database": "Pfam", "accession": "PF1", "name": "a", "description": "A dom", "genes": 2},
            {"database": "Pfam", "accession": "PF3", "name": "c", "description": "C dom", "genes": 4},
        ]
        rows = compare.compare_domain_tables(table_a, table_b, "Pfam")
        assert [(r["accession"], r["a"], r["b"]) for r in rows] == [
            ("PF1", 5, 2), ("PF3", 0, 4), ("PF2", 1, 0),
        ]
        # A description missing in one species is filled from the other.
        assert rows[0]["description"] == "A dom"


# ---------------------------------------------------------------------------
# Annotation statistics
# ---------------------------------------------------------------------------

class TestAnnotations:
    """Protein, transcript and protein-domain statistics."""

    def test_protein_lengths_by_species(self, session):
        lengths = annotations.protein_lengths_by_species(session)
        assert set(lengths) == {0, 1, 2, 3}
        assert len(lengths[0]) == 18            # 17 assigned + 1 orphan
        assert lengths[0].min() == 50

    def test_length_stats(self):
        stats = annotations.length_stats(np.array([50, 150, 250, 2500]))
        assert stats["count"] == 4
        assert stats["median"] == 200
        assert stats["max"] == 2500
        assert stats["short_fraction"] == pytest.approx(0.25)
        histogram = stats["histogram"]
        assert histogram[0] == {"x0": 0, "x1": 50, "count": 0}
        assert histogram[1]["count"] == 1
        assert histogram[-1] == {"x0": 2000, "x1": None, "count": 1}
        assert sum(b["count"] for b in histogram) == 4

    def test_length_stats_empty(self):
        assert annotations.length_stats(None) is None
        assert annotations.length_stats(np.array([])) is None

    def test_transcript_stats(self, session):
        stats = annotations.transcript_stats(session, 0)
        assert stats["count"] == 4
        assert stats["genes"] == 3
        assert stats["matched_genes"] == 2
        assert stats["unmatched_transcripts"] == 1
        assert stats["mean_isoforms"] == pytest.approx(4 / 3)
        assert {b["label"]: b["count"] for b in stats["isoform_histogram"]}["2"] == 1
        assert stats["mono_exonic_fraction"] == pytest.approx(0.25)
        assert stats["coding_transcripts"] == 3
        assert stats["median_cds_length"] == 600
        assert stats["with_mrna"] == 1
        assert {b["label"]: b["count"] for b in stats["biotypes"]} == {
            "protein_coding": 2, "unspecified": 1, "lncRNA": 1,
        }

    def test_transcript_stats_absent(self, session):
        assert annotations.transcript_stats(session, 3) is None

    def test_domain_summary_treats_dash_as_missing(self, session):
        rows = list(annotations.iter_domain_hits(session, 0))
        assert len(rows) == 5
        profile = annotations.domain_profile(rows, n_proteins=18)
        assert profile["annotated"] == {"Sp_a_OG2_0", "Sp_a_OG2_1", "Sp_a_OG1_0", "unmatched_query"}
        summary = profile["summary"]
        assert summary["hits"] == 5
        assert summary["genes_with_domain"] == 4       # three genes + one unmatched query
        assert summary["coverage"] == pytest.approx(4 / 18)
        assert summary["genes_with_go"] == 1           # "-" is not a GO term
        assert summary["unmatched_hits"] == 1
        databases = {d["name"]: d for d in summary["databases"]}
        assert databases["InterPro"]["genes"] == 3     # "-" accessions are skipped
        assert databases["Pfam"]["hits"] == 4
        assert summary["databases"][0]["name"] == "InterPro"

    def test_domain_profile_absent(self, session):
        profile = annotations.domain_profile(annotations.iter_domain_hits(session, 3), 5)
        assert profile == {"summary": None, "families": [], "annotated": set()}

    def test_domain_profile_without_protein_count(self, session):
        profile = annotations.domain_profile(annotations.iter_domain_hits(session, 0), 0)
        assert profile["summary"]["coverage"] is None

    def test_domain_family_table(self, session):
        families = annotations.domain_profile(annotations.iter_domain_hits(session, 0), 18)["families"]
        by_key = {(f["database"], f["accession"]): f for f in families}
        assert by_key[("Pfam", "PF00001")]["genes"] == 2
        assert by_key[("InterPro", "IPR000001")]["description"] == "GPCR"
        assert by_key[("InterPro", "IPR000001")]["genes"] == 2
        assert ("InterPro", "-") not in by_key
        assert ("InterPro", "") not in by_key
        assert families[0]["genes"] >= families[-1]["genes"]

    def test_preferred_database(self):
        assert annotations.preferred_database(["PANTHER", "Pfam", "InterPro"]) == "InterPro"
        assert annotations.preferred_database(["PANTHER", "Pfam"]) == "Pfam"
        assert annotations.preferred_database(["PANTHER"]) == "PANTHER"
        assert annotations.preferred_database([]) is None

    def test_domain_coverage_by_class(self, session, matrix):
        annotated = annotations.domain_profile(
            annotations.iter_domain_hits(session, 0), 18)["annotated"]
        coverage = {c["class"]: c for c in annotations.domain_coverage_by_class(
            session, 0, annotated, matrix, 0)}
        assert coverage["broad"] == {"class": "broad", "genes": 12, "with_domain": 3}
        assert coverage["specific"]["genes"] == 3 and coverage["specific"]["with_domain"] == 0
        assert coverage["unassigned"] == {"class": "unassigned", "genes": 1, "with_domain": 0}

    def test_orthogroup_annotations_prefer_interpro(self, session):
        session.query(Orthogroup).filter_by(orthogroup_id="OG3").update({"description": "Curated"})
        session.commit()
        result = annotations.orthogroup_annotations(session, ["OG2", "OG1", "OG3", "OG7"])
        assert result["OG2"]["labels"][0] == {
            "database": "InterPro", "accession": "IPR000001", "label": "GPCR", "genes": 3,
        }
        assert all(label["database"] == "InterPro" for label in result["OG2"]["labels"])
        assert result["OG1"]["labels"][0]["label"] == "Kinase-like"
        assert result["OG3"] == {"description": "Curated", "labels": []}
        assert "OG7" not in result

    def test_orthogroup_annotations_fall_back_to_member_database(self, session):
        session.add(ProteinDomain(
            gene_id="Sp_c_OG7_0", species_id=2, query_id="q", database="Pfam",
            domain_accession="PF00009", domain_name="Thing", description="-",
            interpro_accession="-", interpro_description="-", go_terms="-",
        ))
        session.commit()
        result = annotations.orthogroup_annotations(session, ["OG7"])
        # With no usable description the short name is shown.
        assert result["OG7"]["labels"] == [
            {"database": "Pfam", "accession": "PF00009", "label": "Thing", "genes": 1}
        ]

    def test_orthogroup_annotations_empty_input(self, session):
        assert annotations.orthogroup_annotations(session, []) == {}


# ---------------------------------------------------------------------------
# Cache and store
# ---------------------------------------------------------------------------

class TestStore:
    """TTL cache behaviour and AnalysisStore invalidation."""

    def test_ttl_cache_expires_and_evicts(self):
        cache = TTLCache(ttl=0.05, max_entries=2)
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.get("a") == (True, 1)
        cache.set("c", 3)                       # evicts "b", the least recently used
        assert cache.get("b") == (False, None)
        assert cache.get("c") == (True, 3)
        time.sleep(0.06)
        assert cache.get("a") == (False, None)

    def test_store_caches_and_orders_by_tree(self, session):
        store = AnalysisStore(lambda: session)
        assert store.matrix() is store.matrix()
        assert store.species_order() == SPECIES
        assert leaf_names(store.tree()) == SPECIES
        rows = store.species_rows()
        assert [r["name"] for r in rows] == SPECIES
        assert rows[0]["proteins"] == 18
        assert rows[0]["median_protein_length"] is not None
        assert rows[0]["transcripts"] == 4 and rows[0]["domain_hits"] == 5
        assert rows[3]["transcripts"] == 0
        assert store.dataset()["name"] == "test"

    def test_store_without_tree_is_alphabetical(self, session):
        session.query(SpeciesTree).delete()
        session.commit()
        store = AnalysisStore(lambda: session)
        assert store.tree() is None
        assert store.species_order() == SPECIES
        assert store.strata("Sp_a") == ([], None)

    def test_store_ignores_unparseable_or_unrelated_tree(self, session):
        session.add(SpeciesTree(newick="((broken", source="bad"))
        session.commit()
        assert AnalysisStore(lambda: session).tree() is None
        session.add(SpeciesTree(newick="(X,Y);", source="other"))
        session.commit()
        assert AnalysisStore(lambda: session).tree() is None

    def test_store_strata_and_domain_bundle(self, session):
        store = AnalysisStore(lambda: session)
        strata, assignment = store.strata("Sp_a")
        assert len(strata) == 4 and (assignment >= -1).all()
        bundle = store.domain_bundle("Sp_a")
        assert bundle["summary"]["hits"] == 5
        assert bundle["families"]
        assert store.domain_bundle("Sp_d") == {
            "summary": None, "families": [], "coverage_by_class": [],
        }

    def test_annotation_ingest_invalidates_cache(self, session):
        store = AnalysisStore(lambda: session)
        assert store.domain_bundle("Sp_d")["summary"] is None
        session.add(ProteinDomain(gene_id="Sp_d_OG1_0", species_id=3, query_id="q",
                                  database="Pfam", domain_accession="PF1"))
        session.commit()
        store._signature_checked = 0.0          # skip the polling interval
        assert store.domain_bundle("Sp_d")["summary"]["hits"] == 1

    def test_new_ingest_run_invalidates_cache(self, session):
        store = AnalysisStore(lambda: session)
        first = store.matrix()
        session.add(Gene(gene_id="new_gene", orthogroup_id="OG1", species_id=0))
        session.add(IngestRun(dataset_name="second", created_at=datetime(2025, 6, 1)))
        session.commit()
        store._signature_checked = 0.0          # skip the polling interval
        second = store.matrix()
        assert second is not first
        assert second.counts.sum() == first.counts.sum() + 1


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

class TestSchema:
    """Index upkeep and the database upgrade script."""

    def test_ensure_indexes_upgrades_an_old_database(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP INDEX ix_genes_orthogroup_id"))
            conn.execute(text("DROP INDEX ix_domains_gene_id"))
        created = ensure_indexes(engine)
        assert created == ["ix_genes_orthogroup_id", "ix_domains_gene_id"]
        names = {ix["name"] for ix in inspect(engine).get_indexes("genes")}
        assert "ix_genes_orthogroup_id" in names
        assert ensure_indexes(engine) == []     # idempotent

    def test_upgrade_script_loads_tree_and_reports_missing(self, session, tmp_path):
        from scripts.upgrade_db import load_species_tree

        tree_file = tmp_path / "SpeciesTree_rooted.txt"
        tree_file.write_text("((Sp_a,Sp_b),Sp_c);\n")
        matched, missing = load_species_tree(session, tree_file)
        assert (matched, missing) == (3, ["Sp_d"])
        latest = session.query(SpeciesTree).order_by(SpeciesTree.id.desc()).first()
        assert latest.newick == "((Sp_a,Sp_b),Sp_c);"
        # The newest tree wins; the species it lacks is listed last.
        store = AnalysisStore(lambda: session)
        assert store.species_order() == ["Sp_a", "Sp_b", "Sp_c", "Sp_d"]
        assert leaf_names(store.tree()) == ["Sp_a", "Sp_b", "Sp_c"]
