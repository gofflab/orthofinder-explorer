"""Schema maintenance helpers shared by the web app and the ingest scripts."""

from sqlalchemy import inspect

from .models import Base


def ensure_indexes(engine):
    """Create any model-declared indexes that are missing from the database.

    ``Base.metadata.create_all`` only builds indexes for tables it creates, so
    databases that predate an index declaration never receive it.  This helper
    closes that gap and is safe to call repeatedly.

    Args:
        engine: SQLAlchemy engine connected to the OrthoFinder database.

    Returns:
        List of index names that were created (empty when already up to date).
    """
    inspector = inspect(engine)
    created = []
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in sorted(table.indexes, key=lambda ix: ix.name):
            if index.name not in existing:
                index.create(engine)
                created.append(index.name)
    return created
