#!/usr/bin/env python
"""Build a small synthetic explorer database for local UI development.

The real database is produced from OrthoFinder output and is far too large to
ship with the repository.  This script fabricates a plausible stand-in (same
schema, same species names, a realistic species tree, and a few deliberately
planted gene-family expansions) so the Species and Species Comparison pages
can be exercised without access to production data.

Nothing here is biological data: gene identifiers, sequences and domain hits
are random.  Planted signals (for example a cephalopod protocadherin
expansion) exist only so the plots have something recognisable to show.

Usage
-----
::

    python scripts/build_demo_db.py --db instance/demo.db
    ORTHOFINDER_DB_PATH=$PWD/instance/demo.db python run.py
"""

import argparse
import random
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, insert

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.analysis.newick import leaf_names, parse_newick
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

#: Plausible topology for the species in ``app/static/species_colors.json``.
DEMO_TREE = (
    "(Amphimedon_queenslandica:0.9,(Hydra_vulgaris:0.8,(Hofstenia_miamia:0.7,"
    "((((Caenorhabditis_elegans:0.2,Caenorhabditis_remanei:0.2)N5:0.5,"
    "Drosophila_melanogaster:0.6)N4:0.1,"
    "(((Octopus_bimaculoides:0.08,(Octopus_sinensis:0.05,Octopus_chierchiae:0.06)N10:0.03)N9:0.2,"
    "(Euprymna_berryi:0.2,(Doryteuthis_pealeii_20250213:0.01,Doryteuthis_pealeii_gert:0.01)N12:0.2)N11:0.1)N8:0.3,"
    "(Aplysia_californica:0.4,((Crassostrea_virginica:0.3,Mizuhopecten_yessoensis:0.3)N15:0.05,"
    "Mercenaria_mercenaria:0.35)N14:0.1)N13:0.1)N7:0.2)N3:0.1,"
    "((Danio_rerio:0.3,(Oncorhynchus_tshawytscha:0.1,Salmo_salar:0.1)N18:0.2)N17:0.1,"
    "(Homo_sapiens:0.1,Mus_musculus:0.12)N19:0.3)N16:0.3)N2:0.1)N1:0.1)N0:0.1);"
)

#: Species that receive transcript and protein-domain annotations.
ANNOTATED = ("Homo_sapiens", "Octopus_chierchiae", "Octopus_bimaculoides", "Danio_rerio")

#: Planted families: (description, domain, clade members, copies inside, copies outside).
CEPHALOPODS = (
    "Octopus_bimaculoides", "Octopus_sinensis", "Octopus_chierchiae",
    "Euprymna_berryi", "Doryteuthis_pealeii_20250213", "Doryteuthis_pealeii_gert",
)
MAMMALS = ("Homo_sapiens", "Mus_musculus")
PLANTED = (
    ("Protocadherin", ("PF00028", "Cadherin", "Cadherin domain"), CEPHALOPODS, (60, 150), (4, 14)),
    ("C2H2 zinc finger", ("PF00096", "zf-C2H2", "Zinc finger, C2H2 type"), CEPHALOPODS, (90, 220), (15, 60)),
    ("KRAB zinc finger", ("PF01352", "KRAB", "KRAB box"), MAMMALS, (120, 260), (0, 1)),
    ("Olfactory receptor", ("PF13853", "7tm_4", "Olfactory receptor"), MAMMALS, (180, 420), (0, 3)),
    ("Reflectin", ("PF21055", "Reflectin", "Reflectin"), CEPHALOPODS, (6, 30), (0, 0)),
    ("Sulfotransferase", ("PF00685", "Sulfotransfer_1", "Sulfotransferase domain"), ("Octopus_chierchiae",), (38, 39), (2, 6)),
)

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


def collect_clades(node, clades):
    """Collect the leaf sets of every node in a parsed tree.

    Args:
        node: Tree node from :func:`app.analysis.newick.parse_newick`.
        clades: List that receives one tuple of leaf names per node.
    """
    clades.append(tuple(leaf_names(node)))
    for child in node["children"]:
        collect_clades(child, clades)


def random_protein(rng, median_length):
    """Generate a random protein sequence with a skewed length distribution.

    Args:
        rng: ``random.Random`` instance.
        median_length: Approximate median length in amino acids.

    Returns:
        Sequence string starting with methionine.
    """
    length = max(30, int(rng.lognormvariate(0, 0.6) * median_length))
    return "M" + "".join(rng.choice(AMINO_ACIDS) for _ in range(length - 1))


def build(db_path, n_orthogroups=4000, seed=7):
    """Create the demo database.

    Args:
        db_path: Destination SQLite file (overwritten if it exists).
        n_orthogroups: Number of random orthogroups besides the planted ones.
        seed: Random seed, so repeated builds are identical.

    Returns:
        Dict of record counts keyed by table name.
    """
    rng = random.Random(seed)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    tree = parse_newick(DEMO_TREE)
    species = sorted(leaf_names(tree))
    species_id = {name: i for i, name in enumerate(species)}
    clades = []
    collect_clades(tree, clades)
    # Older (larger) clades originate more families, as in real datasets.
    weights = [len(clade) ** 1.5 if len(clade) > 1 else 6 for clade in clades]
    # Transcriptome-derived proteomes are more fragmented than model genomes.
    median_length = {name: (260 if name in CEPHALOPODS else 380) for name in species}

    genes, sequences, orthogroups, domains, transcripts = [], [], [], [], []
    gene_counter = {name: 0 for name in species}
    tree_leaves = {}   # orthogroup id -> gene-tree leaf labels ("Species_gene")

    def add_gene(name, orthogroup_id):
        """Register one gene (and its protein) for a species; return its id."""
        gene_counter[name] += 1
        prefix = "".join(part[0] for part in name.split("_")[:2]).upper()
        gene_id = f"{prefix}{species_id[name]:02d}_g{gene_counter[name]:06d}"
        if orthogroup_id is not None:
            genes.append({"gene_id": gene_id, "orthogroup_id": orthogroup_id,
                          "species_id": species_id[name]})
            tree_leaves.setdefault(orthogroup_id, []).append(f"{name}_{gene_id}")
        sequences.append({
            "sequence_idx": str(len(sequences)),
            "ortho_id": f"{species_id[name]}_{gene_counter[name]}",
            "species_id": species_id[name],
            "ortho_gene_id": str(gene_counter[name]),
            "gene_id": gene_id,
            "protein_sequence": random_protein(rng, median_length[name]),
        })
        return gene_id

    def annotate(name, gene_id, domain, extra_go=True):
        """Attach Pfam (and matching InterPro) hits to a gene of an annotated species."""
        if name not in ANNOTATED or domain is None:
            return
        accession, short, description = domain
        ipr = "IPR" + accession[2:].zfill(6)
        domains.append({
            "gene_id": gene_id, "species_id": species_id[name], "query_id": gene_id,
            "database": "Pfam", "domain_accession": accession, "domain_name": short,
            "description": description, "seq_start": 10, "seq_end": 120,
            "score": None, "evalue": 1e-20, "interpro_accession": ipr,
            "interpro_description": f"{description} superfamily",
            "go_terms": "GO:0005515" if extra_go else "-", "pathways": "-",
        })
        domains.append({
            "gene_id": gene_id, "species_id": species_id[name], "query_id": gene_id,
            "database": "PANTHER", "domain_accession": "PTHR" + accession[2:],
            "domain_name": "PTHR" + accession[2:], "description": f"{short} family member",
            "seq_start": 1, "seq_end": 200, "score": None, "evalue": 1e-30,
            "interpro_accession": "-", "interpro_description": "-",
            "go_terms": "-", "pathways": "-",
        })

    og_index = 0

    def new_orthogroup(description=None):
        """Allocate the next orthogroup id and register the row."""
        nonlocal og_index
        orthogroup_id = f"OG{og_index:07d}"
        og_index += 1
        orthogroups.append({"orthogroup_id": orthogroup_id, "description": description,
                            "gene_tree": None})
        return orthogroup_id

    # Planted, recognisable families.
    for description, domain, inside, in_range, out_range in PLANTED:
        orthogroup_id = new_orthogroup(description)
        for name in species:
            low, high = in_range if name in inside else out_range
            for _ in range(rng.randint(low, high)):
                annotate(name, add_gene(name, orthogroup_id), domain)

    # Random families: born in a random clade, with losses and duplications.
    for i in range(n_orthogroups):
        clade = rng.choices(clades, weights)[0]
        orthogroup_id = new_orthogroup()
        base = 1 + (rng.random() < 0.25) * rng.randint(1, 4)
        loss = rng.choice((0.0, 0.05, 0.15, 0.4))
        # Older families are more likely to carry a recognisable domain.
        has_domain = rng.random() < min(0.9, 0.25 + 0.04 * len(clade))
        domain = (f"PF{10000 + i:05d}", f"Dom{i}", f"Demo domain {i}") if has_domain else None
        boosted = rng.choice(species) if rng.random() < 0.04 else None
        for name in clade:
            if len(clade) > 1 and rng.random() < loss:
                continue
            copies = base + (rng.random() < 0.2) * rng.randint(1, 3)
            if name == boosted:
                copies += rng.randint(4, 25)
            for _ in range(copies):
                annotate(name, add_gene(name, orthogroup_id), domain, rng.random() < 0.6)

    # Unassigned genes (present in the proteome, absent from every orthogroup).
    for name in species:
        for _ in range(rng.randint(150, 900) if name in CEPHALOPODS else rng.randint(40, 200)):
            add_gene(name, None)

    # A flat (star) gene tree per family, so orthogroup pages render in the demo.
    for orthogroup in orthogroups:
        leaves = tree_leaves.get(orthogroup["orthogroup_id"], [])
        if len(leaves) >= 2:
            orthogroup["gene_tree"] = "(" + ",".join(
                f"{leaf}:{rng.uniform(0.05, 0.6):.3f}" for leaf in leaves
            ) + ");"

    # Transcript isoforms for the annotated species.
    gene_ids_by_species = {}
    for gene in genes:
        gene_ids_by_species.setdefault(gene["species_id"], []).append(gene["gene_id"])
    for name in ANNOTATED:
        for gene_id in gene_ids_by_species.get(species_id[name], []):
            for isoform in range(1 + (rng.random() < 0.35) * rng.randint(1, 5)):
                exons = max(1, int(rng.lognormvariate(1.6, 0.7)))
                transcripts.append({
                    "transcript_id": f"{gene_id}.t{isoform + 1}", "gene_id": gene_id,
                    "species_id": species_id[name], "gtf_gene_id": gene_id,
                    "seqname": f"scaffold_{rng.randint(1, 30)}", "source": "demo",
                    "biotype": "protein_coding" if rng.random() < 0.92 else "lncRNA",
                    "start": 1, "end": 1000 * exons, "strand": rng.choice("+-"),
                    "exon_count": exons, "cds_length": 3 * rng.randint(60, 900),
                    "mrna_sequence": "ACGT" * 5 if rng.random() < 0.8 else None,
                })

    with engine.begin() as conn:
        conn.execute(insert(Species), [
            {"species_id": species_id[name], "species_name": name} for name in species
        ])
        conn.execute(insert(Orthogroup), orthogroups)
        conn.execute(insert(Gene), genes)
        conn.execute(insert(Sequence), sequences)
        conn.execute(insert(Transcript), transcripts)
        conn.execute(insert(ProteinDomain), domains)
        conn.execute(insert(SpeciesTree), [
            {"newick": DEMO_TREE, "source": "demo", "created_at": datetime.utcnow()}
        ])
        conn.execute(insert(IngestRun), [{
            "dataset_name": "Synthetic demo (not real data)", "input_dir": "demo",
            "created_at": datetime.utcnow(), "orthogroups_count": len(orthogroups),
            "genes_count": len(genes), "sequences_count": len(sequences),
            "gene_trees_count": 0, "config_json": "{}",
        }])
    return {
        "species": len(species), "orthogroups": len(orthogroups), "genes": len(genes),
        "sequences": len(sequences), "transcripts": len(transcripts),
        "protein_domains": len(domains),
    }


def main(argv=None):
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).
    """
    parser = argparse.ArgumentParser(description="Build a synthetic demo database.")
    parser.add_argument("--db", default="instance/demo.db", help="Output SQLite path.")
    parser.add_argument("--orthogroups", type=int, default=4000,
                        help="Number of random orthogroups to generate.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed.")
    args = parser.parse_args(argv)
    counts = build(args.db, n_orthogroups=args.orthogroups, seed=args.seed)
    print(f"Wrote {args.db}")
    for table, count in counts.items():
        print(f"  {table:16s} {count:>8,}")


if __name__ == "__main__":
    main()
