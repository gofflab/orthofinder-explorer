#!/usr/bin/env python
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from ete3 import Tree
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.models import Base, Orthogroup, Gene, Sequence, Species, IngestRun

DEFAULTS = {
    "orthogroups_file": "Phylogenetic_Hierarchical_Orthogroups/N0.tsv",
    "species_file": "WorkingDirectory/SpeciesIDs.txt",
    "sequence_ids_file": "WorkingDirectory/SequenceIDs.txt",
    "protein_fasta_pattern": "WorkingDirectory/Species{species_id}.fa",
    "gene_tree_dir": "Gene_Trees",
    "species_tree_file": "Species_Tree/SpeciesTree_rooted.txt",
    "species_colors_output": "app/static/species_colors.json",
    "clade_min_count": 5,
    "clade_max_count": 8,
    "clade_target_count": None,
    "clade_anchor_depth": None,
    "clade_distance_metric": "topology",
    "clade_color_steps": 5,
    "forced_clades": {},
    "db_path": "instance/orthofinder_new.db",
    "mode": "rebuild",
    "normalize_dpe_tree_labels": True,
}

DPE_FRAME_RE = re.compile(r"__([^_]+)__")


def load_config(path):
    """Load a JSON config file into a dict.

    Args:
        path: Path to a JSON config file or None.

    Returns:
        Dict of config values, or an empty dict when path is None.
    """
    if not path:
        return {}
    with open(path, "r") as handle:
        return json.load(handle)


def merge_config(base, override):
    """Merge two config dictionaries, skipping None overrides.

    Args:
        base: Base config dict.
        override: Overrides dict where None values are ignored.

    Returns:
        A merged dict with override values applied.
    """
    merged = dict(base)
    for key, value in override.items():
        if value is not None:
            merged[key] = value
    return merged


def require_path(path, label):
    """Ensure a filesystem path exists.

    Args:
        path: Path object to validate.
        label: Human-readable label for error messages.

    Raises:
        FileNotFoundError: When the path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def fasta_generator(fasta_file):
    """Yield FASTA headers and sequences from a file.

    Args:
        fasta_file: Path to a multi-sequence FASTA file.

    Yields:
        Tuples of (header, sequence) with header stripped of leading '>'.
    """
    with open(fasta_file, "r") as handle:
        header = None
        sequence = ""
        for line in handle:
            if line.startswith(">"):
                if header:
                    yield header, sequence
                header = line.strip().lstrip(">")
                sequence = ""
            else:
                sequence += line.strip()
        if header:
            yield header, sequence


def parse_orthogroups(orthogroups_file):
    """Parse Orthofinder orthogroups into a normalized DataFrame.

    Args:
        orthogroups_file: Path to the orthogroups TSV file.

    Returns:
        Pandas DataFrame with orthogroup, species, and gene lists.
    """
    orthogroups_df = pd.read_csv(orthogroups_file, sep="\t", dtype=str)
    orthogroups_df = orthogroups_df.melt(
        id_vars=["HOG", "OG", "Gene Tree Parent Clade"],
        var_name="species",
        value_name="genes",
    )
    orthogroups_df["genes"] = orthogroups_df["genes"].fillna("").str.split(",")

    def normalize_gene_list(genes):
        if not isinstance(genes, list):
            return []
        cleaned = []
        for gene in genes:
            gene = gene.strip()
            if gene:
                cleaned.append(gene)
        return cleaned

    orthogroups_df["genes"] = orthogroups_df["genes"].apply(normalize_gene_list)
    orthogroups_df = orthogroups_df[orthogroups_df["genes"].map(bool)]
    orthogroups_df = orthogroups_df.rename(
        columns={
            "HOG": "hierarchical_orthogroup",
            "OG": "orthogroup",
            "Gene Tree Parent Clade": "parent_clade",
        }
    )
    return orthogroups_df


def parse_species_file(species_file):
    """Parse species IDs and names from Orthofinder metadata.

    Args:
        species_file: Path to SpeciesIDs.txt.

    Returns:
        Pandas DataFrame with species_id and species name columns.
    """
    species_df = pd.read_csv(
        species_file, sep=r":\s+", header=None, engine="python", dtype=str
    )
    species_df.columns = ["species_id", "species"]
    species_df["species"] = species_df["species"].apply(
        lambda value: os.path.splitext(value)[0]
    )
    return species_df


def parse_sequence_ids(sequence_ids_file):
    """Parse SequenceIDs.txt into ortho and gene identifiers.

    Args:
        sequence_ids_file: Path to SequenceIDs.txt.

    Returns:
        Pandas DataFrame with ortho_id, gene_id, species_id, and ortho_gene_id.
    """
    sequence_ids = pd.read_csv(
        sequence_ids_file, sep=r":\s+", header=None, engine="python", dtype=str
    )
    sequence_ids.columns = ["ortho_id", "gene_id"]
    sequence_ids[["species_id", "ortho_gene_id"]] = sequence_ids[
        "ortho_id"
    ].str.split("_", n=1, expand=True)
    return sequence_ids


def parse_protein_sequence_file(protein_sequence_file):
    """Parse a single species protein FASTA file into records.

    Args:
        protein_sequence_file: Path to a Species{N}.fa file.

    Returns:
        List of tuples: (species_id, ortho_gene_id, protein_sequence).
    """
    protein_sequences = []
    for header, sequence in fasta_generator(protein_sequence_file):
        species_id, ortho_gene_id = header.split("_", 1)
        protein_sequences.append((species_id, ortho_gene_id, sequence))
    return protein_sequences


def get_protein_sequences(species_df, input_dir, protein_fasta_pattern, verbose=False):
    """Load protein sequences for all species listed in species_df.

    Args:
        species_df: DataFrame with species_id and species columns.
        input_dir: Base Orthofinder results directory.
        protein_fasta_pattern: Pattern for per-species FASTA files.
        verbose: Whether to print progress messages.

    Returns:
        Pandas DataFrame with species_id, ortho_gene_id, protein_sequence.
    """
    sequences = []
    for _, row in species_df.iterrows():
        species_of_id = row["species_id"]
        if verbose:
            print(f"\tFetching {row['species']}")
        protein_sequence_file = input_dir / protein_fasta_pattern.format(
            species_id=species_of_id
        )
        require_path(protein_sequence_file, "Protein sequence file")
        protein_sequences = parse_protein_sequence_file(protein_sequence_file)
        protein_sequences_df = pd.DataFrame(
            protein_sequences, columns=["species_id", "ortho_gene_id", "protein_sequence"]
        )
        sequences.append(protein_sequences_df)
    sequences_df = pd.concat(sequences)
    sequences_df.reset_index(drop=True, inplace=True)
    return sequences_df


def normalize_dpe_gene_id(gene_id):
    """Normalize Dpe gene IDs from tree labels to DB identifiers.

    Args:
        gene_id: Raw gene ID string from a tree label.

    Returns:
        Normalized gene ID with gert_ stripped and frame tokens converted.
    """
    if gene_id.startswith("gert_"):
        gene_id = gene_id[5:]
    if gene_id.startswith("Dpe") and "__" in gene_id:
        gene_id = DPE_FRAME_RE.sub(r"_[$1]_", gene_id)
    return gene_id


def normalize_tree_label(label):
    """Normalize a full tree leaf label if it matches Doryteuthis format.

    Args:
        label: Leaf label from a Newick tree.

    Returns:
        Possibly normalized label with Dpe gene IDs rewritten.
    """
    prefix = "Doryteuthis_pealeii_"
    if label.startswith(prefix):
        rest = label[len(prefix) :]
        normalized = normalize_dpe_gene_id(rest)
        if normalized != rest:
            return prefix + normalized
    return label


def hex_to_rgb(hex_color):
    """Convert a hex color string to normalized RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    """Convert normalized RGB tuple to a hex color string."""
    return "#{:02x}{:02x}{:02x}".format(
        int(max(0, min(1, rgb[0])) * 255),
        int(max(0, min(1, rgb[1])) * 255),
        int(max(0, min(1, rgb[2])) * 255),
    )


def topology_distance(node, leaf):
    """Return edge count between node and leaf using topology-only distance."""
    if node == leaf:
        return 0
    return node.get_distance(leaf, topology_only=True) + 1


def build_anchor_clades(tree, min_clades=5, max_clades=8):
    """Select anchor clades by depth, then normalize to a clade count range."""
    return build_anchor_clades_by_depth(tree, min_clades, max_clades, None)


def get_node_depth(node):
    """Return the depth (edge count) of a node from the root."""
    depth = 0
    while node.up is not None:
        depth += 1
        node = node.up
    return depth


def collect_clades_at_depth(tree, depth):
    """Return nodes that sit exactly at a target depth from the root."""
    clades = []
    for node in tree.traverse("preorder"):
        if get_node_depth(node) == depth:
            clades.append(node)
    return clades


def build_anchor_clades_by_depth(tree, min_clades, max_clades, anchor_depth):
    """Select anchor clades using depth cuts, then merge/split to fit range."""
    min_clades = max(1, int(min_clades))
    max_clades = max(min_clades, int(max_clades))
    max_depth = max(get_node_depth(leaf) for leaf in tree.iter_leaves())

    if anchor_depth is None:
        depth = 1
        clades = collect_clades_at_depth(tree, depth)
        while len(clades) < min_clades and depth < max_depth:
            depth += 1
            clades = collect_clades_at_depth(tree, depth)
    else:
        depth = max(1, min(int(anchor_depth), max_depth))
        clades = collect_clades_at_depth(tree, depth)

    while len(clades) < min_clades:
        candidates = [c for c in clades if not c.is_leaf()]
        if not candidates:
            break
        largest = max(candidates, key=lambda n: len(n.get_leaf_names()))
        clades.remove(largest)
        clades.extend(largest.children)

    if len(clades) > max_clades:
        if max_clades == 1:
            clades = [{"label": "Other", "leaves": tree.get_leaf_names()}]
        else:
            clades = sorted(clades, key=lambda n: len(n.get_leaf_names()), reverse=True)
            keep = clades[: max_clades - 1]
            merged = clades[max_clades - 1 :]
            merged_leaves = []
            for node in merged:
                merged_leaves.extend(node.get_leaf_names())
            clades = keep + [{"label": "Other", "leaves": merged_leaves}]

    anchor_clades = []
    for idx, node in enumerate(clades):
        if isinstance(node, dict):
            anchor_clades.append(
                {
                    "label": node["label"],
                    "node": None,
                    "leaves": node["leaves"],
                }
            )
        else:
            anchor_clades.append(
                {
                    "label": f"clade_{idx + 1}",
                    "node": node,
                    "leaves": node.get_leaf_names(),
                }
            )
    return anchor_clades


def compute_species_color_map(
    tree,
    species_names,
    steps=5,
    min_clades=5,
    max_clades=8,
    anchor_depth=None,
    distance_metric="topology",
    forced_clades=None,
):
    """Compute a clade-anchored color map from a species tree."""
    base_palette = [
        "#1b9e77",
        "#d95f02",
        "#7570b3",
        "#e7298a",
        "#66a61e",
        "#e6ab02",
        "#a6761d",
        "#666666",
    ]
    forced_clades = forced_clades or {}
    tree_leaf_names = set(tree.get_leaf_names())
    color_map = {}
    palette_index = 0

    for label, species_list in forced_clades.items():
        present = [name for name in species_list if name in tree_leaf_names]
        if not present:
            continue
        if len(present) == 1:
            node = tree&present[0]
        else:
            node = tree.get_common_ancestor(present)
        leaves = [name for name in node.get_leaf_names() if name in species_names]
        if not leaves:
            continue
        base_color = base_palette[palette_index % len(base_palette)]
        palette_index += 1
        base_rgb = hex_to_rgb(base_color)
        import colorsys

        h, l, s = colorsys.rgb_to_hls(*base_rgb)
        distances = {}
        for name in leaves:
            leaf = tree&name
            if distance_metric == "branch":
                dist = node.get_distance(leaf)
            else:
                dist = topology_distance(node, leaf)
            distances[name] = dist
        max_dist = max(distances.values()) or 1.0
        for name in leaves:
            ratio = distances[name] / max_dist
            bucket = int(round(ratio * (steps - 1)))
            offset = (steps // 2 - bucket) * 0.06
            new_l = min(0.85, max(0.25, l + offset))
            new_rgb = colorsys.hls_to_rgb(h, new_l, s)
            color_map[name] = rgb_to_hex(new_rgb)

    anchor_clades = build_anchor_clades_by_depth(
        tree, min_clades, max_clades, anchor_depth
    )

    for idx, clade in enumerate(anchor_clades):
        base_color = base_palette[(palette_index + idx) % len(base_palette)]
        base_rgb = hex_to_rgb(base_color)
        import colorsys

        h, l, s = colorsys.rgb_to_hls(*base_rgb)
        leaves = [
            name
            for name in clade["leaves"]
            if name in species_names and name not in color_map
        ]
        if not leaves:
            continue
        distances = {}
        for name in leaves:
            leaf = tree&name
            if clade["node"] is not None:
                if distance_metric == "branch":
                    dist = clade["node"].get_distance(leaf)
                else:
                    dist = topology_distance(clade["node"], leaf)
            else:
                if distance_metric == "branch":
                    dist = tree.get_tree_root().get_distance(leaf)
                else:
                    dist = topology_distance(tree.get_tree_root(), leaf)
            distances[name] = dist
        max_dist = max(distances.values()) or 1.0

        for name in leaves:
            ratio = distances[name] / max_dist
            bucket = int(round(ratio * (steps - 1)))
            offset = (steps // 2 - bucket) * 0.06
            new_l = min(0.85, max(0.25, l + offset))
            new_rgb = colorsys.hls_to_rgb(h, new_l, s)
            color_map[name] = rgb_to_hex(new_rgb)

    for name in species_names:
        if name not in color_map:
            color_map[name] = "#888888"
    return color_map


def load_gene_trees(
    session, orthogroups, gene_tree_dir, normalize_dpe_tree_labels, verbose=False
):
    """Load gene trees into the orthogroups table.

    Args:
        session: SQLAlchemy session.
        orthogroups: Iterable of orthogroup IDs.
        gene_tree_dir: Directory containing {orthogroup}_tree.txt files.
        normalize_dpe_tree_labels: Whether to normalize Dpe labels in trees.
        verbose: Whether to print warnings for missing trees.

    Returns:
        Count of gene trees loaded.
    """
    gene_trees_loaded = 0
    for orthogroup_id in orthogroups:
        gene_tree_file = gene_tree_dir / f"{orthogroup_id}_tree.txt"
        if not gene_tree_file.exists():
            if verbose:
                print(f"Warning: Gene tree not found: {gene_tree_file}")
            continue
        with open(gene_tree_file, "r") as handle:
            gene_tree = handle.read().strip()
        tree = Tree(gene_tree)
        if normalize_dpe_tree_labels:
            for leaf in tree.iter_leaves():
                leaf.name = normalize_tree_label(leaf.name)
        orthogroup = session.query(Orthogroup).filter_by(
            orthogroup_id=orthogroup_id
        ).first()
        if orthogroup is None:
            orthogroup = Orthogroup(
                orthogroup_id=orthogroup_id, gene_tree=tree.write()
            )
            session.add(orthogroup)
        else:
            orthogroup.gene_tree = tree.write()
        gene_trees_loaded += 1
    session.commit()
    return gene_trees_loaded


def insert_in_batches(session, objects, batch_size=5000):
    """Insert ORM objects in batches with commits.

    Args:
        session: SQLAlchemy session.
        objects: Iterable of ORM objects to persist.
        batch_size: Number of objects per batch.

    Returns:
        Count of inserted objects.
    """
    batch = []
    count = 0
    for obj in objects:
        batch.append(obj)
        if len(batch) >= batch_size:
            session.bulk_save_objects(batch)
            session.commit()
            count += len(batch)
            batch = []
    if batch:
        session.bulk_save_objects(batch)
        session.commit()
        count += len(batch)
    return count


def main():
    """CLI entry point for Orthofinder ingestion."""
    parser = argparse.ArgumentParser(
        description="Ingest Orthofinder outputs into the explorer database."
    )
    parser.add_argument("--config", help="Path to a JSON config file.")
    parser.add_argument("--input-dir", help="Path to Orthofinder results directory.")
    parser.add_argument("--db-path", help="SQLite DB path (default: instance/orthofinder_new.db).")
    parser.add_argument(
        "--mode", choices=["rebuild", "append"], help="Ingestion mode."
    )
    parser.add_argument("--orthogroups-file", help="Relative path to orthogroups TSV.")
    parser.add_argument("--species-file", help="Relative path to SpeciesIDs.txt.")
    parser.add_argument(
        "--sequence-ids-file", help="Relative path to SequenceIDs.txt."
    )
    parser.add_argument(
        "--protein-fasta-pattern",
        help="Relative path pattern for species FASTA files.",
    )
    parser.add_argument(
        "--species-tree-file",
        help="Relative path to the rooted species tree file.",
    )
    parser.add_argument("--gene-tree-dir", help="Relative path to gene trees directory.")
    parser.add_argument(
        "--species-colors-output",
        help="Path to write species color mapping JSON.",
    )
    parser.add_argument(
        "--clade-target-count",
        type=int,
        help="Target number of clade anchors to use for coloring.",
    )
    parser.add_argument(
        "--clade-min-count",
        type=int,
        help="Minimum number of clade anchors to use for coloring.",
    )
    parser.add_argument(
        "--clade-max-count",
        type=int,
        help="Maximum number of clade anchors to use for coloring.",
    )
    parser.add_argument(
        "--clade-anchor-depth",
        type=int,
        help="Depth from the root for clade anchors (edge count).",
    )
    parser.add_argument(
        "--clade-distance-metric",
        choices=["topology", "branch"],
        help="Distance metric for within-clade shading.",
    )
    parser.add_argument(
        "--clade-color-steps",
        type=int,
        help="Number of discrete lightness steps within each clade.",
    )
    parser.add_argument("--dataset-name", help="Name for this dataset.")
    parser.add_argument(
        "--no-normalize-dpe-tree-labels",
        action="store_true",
        help="Disable Dpe label normalization in gene trees.",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging.")
    args = parser.parse_args()

    config = load_config(args.config)
    config = merge_config(DEFAULTS, config)
    config = merge_config(
        config,
        {
            "input_dir": args.input_dir,
            "db_path": args.db_path,
            "mode": args.mode,
            "orthogroups_file": args.orthogroups_file,
            "species_file": args.species_file,
            "sequence_ids_file": args.sequence_ids_file,
            "protein_fasta_pattern": args.protein_fasta_pattern,
            "species_tree_file": args.species_tree_file,
            "gene_tree_dir": args.gene_tree_dir,
            "species_colors_output": args.species_colors_output,
            "clade_target_count": args.clade_target_count,
            "clade_min_count": args.clade_min_count,
            "clade_max_count": args.clade_max_count,
            "clade_anchor_depth": args.clade_anchor_depth,
            "clade_distance_metric": args.clade_distance_metric,
            "clade_color_steps": args.clade_color_steps,
            "dataset_name": args.dataset_name,
        },
    )

    if not config.get("input_dir"):
        raise ValueError("input_dir is required (set via --input-dir or config).")

    input_dir = Path(config["input_dir"]).expanduser().resolve()
    orthogroups_file = input_dir / config["orthogroups_file"]
    species_file = input_dir / config["species_file"]
    sequence_ids_file = input_dir / config["sequence_ids_file"]
    gene_tree_dir = input_dir / config["gene_tree_dir"]
    species_tree_file = input_dir / config["species_tree_file"]
    protein_fasta_pattern = config["protein_fasta_pattern"]
    species_colors_output = Path(config["species_colors_output"]).expanduser().resolve()

    require_path(input_dir, "Input directory")
    require_path(orthogroups_file, "Orthogroups file")
    require_path(species_file, "Species IDs file")
    require_path(sequence_ids_file, "Sequence IDs file")
    require_path(gene_tree_dir, "Gene tree directory")
    require_path(species_tree_file, "Species tree file")

    if args.verbose:
        print("Parsing orthogroups...")
    orthogroups_df = parse_orthogroups(orthogroups_file)
    orthogroup_list = orthogroups_df["orthogroup"].dropna().unique()

    if args.verbose:
        print("Parsing species metadata...")
    species_df = parse_species_file(species_file)

    if args.verbose:
        print("Merging orthogroups and species...")
    orthogroups_df = orthogroups_df.merge(species_df, on="species", how="left")
    if orthogroups_df["species_id"].isna().any():
        missing = orthogroups_df[orthogroups_df["species_id"].isna()]["species"].unique()
        raise ValueError(f"Missing species IDs for: {', '.join(sorted(missing))}")

    if args.verbose:
        print("Parsing sequence IDs...")
    sequence_ids = parse_sequence_ids(sequence_ids_file)

    if args.verbose:
        print("Parsing protein sequences...")
    sequences_df = get_protein_sequences(
        species_df, input_dir, protein_fasta_pattern, verbose=args.verbose
    )
    sequences_df = sequences_df.merge(
        sequence_ids, on=["species_id", "ortho_gene_id"], how="inner"
    )

    if args.verbose:
        print("Computing species color palette...")
    with open(species_tree_file, "r") as handle:
        species_tree = handle.read().strip()
    species_tree = Tree(species_tree)
    species_names = set(species_df["species"].tolist())
    clade_min_count = int(config.get("clade_min_count", 5))
    clade_max_count = int(config.get("clade_max_count", 8))
    clade_target_count = config.get("clade_target_count")
    if clade_target_count is not None:
        clade_min_count = int(clade_target_count)
        clade_max_count = int(clade_target_count)
    clade_anchor_depth = config.get("clade_anchor_depth")
    clade_distance_metric = config.get("clade_distance_metric", "topology")
    clade_color_steps = int(config.get("clade_color_steps", 5))
    forced_clades = config.get("forced_clades") or {}
    species_color_map = compute_species_color_map(
        species_tree,
        species_names,
        steps=clade_color_steps,
        min_clades=clade_min_count,
        max_clades=clade_max_count,
        anchor_depth=clade_anchor_depth,
        distance_metric=clade_distance_metric,
        forced_clades=forced_clades,
    )
    species_colors_output.parent.mkdir(parents=True, exist_ok=True)
    with open(species_colors_output, "w") as handle:
        json.dump(species_color_map, handle, indent=2, sort_keys=True)

    db_path = Path(config["db_path"]).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")

    if config["mode"] == "rebuild":
        print("Rebuilding database...")
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    else:
        print("Appending to existing database...")
        Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    print("Loading orthogroups...")
    insert_in_batches(
        session, (Orthogroup(orthogroup_id=og) for og in orthogroup_list)
    )

    print("Loading species...")
    insert_in_batches(
        session,
        (
            Species(species_id=int(row["species_id"]), species_name=row["species"])
            for _, row in species_df.iterrows()
        ),
    )

    print("Loading genes...")
    seen_gene_ids = set()

    def gene_iter():
        for _, row in orthogroups_df.iterrows():
            species_id = int(row["species_id"])
            orthogroup_id = row["orthogroup"]
            for gene_id in row["genes"]:
                if gene_id in seen_gene_ids:
                    continue
                seen_gene_ids.add(gene_id)
                yield Gene(
                    gene_id=gene_id,
                    orthogroup_id=orthogroup_id,
                    species_id=species_id,
                )

    genes_count = insert_in_batches(session, gene_iter())

    print("Loading protein sequences...")

    def sequence_iter():
        for idx, row in sequences_df.iterrows():
            yield Sequence(
                sequence_idx=str(idx),
                species_id=int(row["species_id"]),
                ortho_gene_id=row["ortho_gene_id"],
                ortho_id=row["ortho_id"],
                gene_id=row["gene_id"],
                protein_sequence=row["protein_sequence"],
            )

    sequences_count = insert_in_batches(session, sequence_iter())

    print("Loading gene trees...")
    normalize_dpe_tree_labels = config.get("normalize_dpe_tree_labels", True)
    if args.no_normalize_dpe_tree_labels:
        normalize_dpe_tree_labels = False
    gene_trees_count = load_gene_trees(
        session,
        orthogroup_list,
        gene_tree_dir,
        normalize_dpe_tree_labels=normalize_dpe_tree_labels,
        verbose=args.verbose,
    )

    dataset_name = config.get("dataset_name") or input_dir.name
    run = IngestRun(
        dataset_name=dataset_name,
        input_dir=str(input_dir),
        created_at=datetime.utcnow(),
        orthogroups_count=len(orthogroup_list),
        genes_count=genes_count,
        sequences_count=sequences_count,
        gene_trees_count=gene_trees_count,
        config_json=json.dumps(config, sort_keys=True),
    )
    session.add(run)
    session.commit()

    print("Done.")


if __name__ == "__main__":
    main()
