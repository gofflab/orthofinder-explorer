#!/usr/bin/env python
"""Bring an existing explorer database up to date without re-ingesting.

Run this once after upgrading the code on a database that was built by an
older version of ``ingest_orthofinder.py``.  It is idempotent and only adds
things:

* creates any tables that are missing (for example ``species_tree``),
* creates any missing indexes declared on the models, and
* optionally loads the rooted OrthoFinder species tree, which the Species
  pages use for tree-ordered plots and gene-age (phylostrata) analyses.

Usage
-----
::

    python scripts/upgrade_db.py \\
        --db instance/orthofinder_new.db \\
        --species-tree /path/to/Results_XXXX/Species_Tree/SpeciesTree_rooted.txt
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.analysis.newick import leaf_names, parse_newick
from app.models import Base, Species, SpeciesTree
from app.schema import ensure_indexes


def load_species_tree(session, tree_path):
    """Store a rooted species tree and report how well it matches the DB.

    Args:
        session: SQLAlchemy session bound to the explorer database.
        tree_path: Path to a Newick file whose leaf names are species names.

    Returns:
        Tuple ``(matched, missing)`` where ``matched`` is the number of
        database species found in the tree and ``missing`` lists database
        species that are absent from it.

    Raises:
        app.analysis.newick.NewickError: If the file is not valid Newick.
    """
    newick = Path(tree_path).read_text().strip()
    leaves = set(leaf_names(parse_newick(newick)))
    species = [name for (name,) in session.query(Species.species_name).all()]
    missing = sorted(name for name in species if name not in leaves)
    session.add(
        SpeciesTree(newick=newick, source=str(tree_path), created_at=datetime.utcnow())
    )
    session.commit()
    return len(species) - len(missing), missing


def main(argv=None):
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Add missing tables, indexes and the species tree to an existing DB."
    )
    parser.add_argument("--db", required=True, help="Path to the SQLite database.")
    parser.add_argument(
        "--species-tree",
        help="Rooted species tree in Newick format "
        "(OrthoFinder: Species_Tree/SpeciesTree_rooted.txt).",
    )
    parser.add_argument(
        "--skip-indexes",
        action="store_true",
        help="Do not create missing indexes (they can take a while on large tables).",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    print("Tables are up to date.")

    if not args.skip_indexes:
        created = ensure_indexes(engine)
        print(f"Created {len(created)} index(es): {', '.join(created) or 'none needed'}")

    if args.species_tree:
        session = sessionmaker(bind=engine)()
        try:
            matched, missing = load_species_tree(session, args.species_tree)
        finally:
            session.close()
        print(f"Loaded species tree; {matched} database species found in the tree.")
        if missing:
            print(
                "Warning: species missing from the tree (shown last, excluded from "
                f"gene-age analyses): {', '.join(missing)}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
