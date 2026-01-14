#!/usr/bin/env python
import sys


def main():
    """Exit with guidance to use the new ingestion CLI instead."""
    print(
        "parse_OF.py is retired. Use scripts/ingest_orthofinder.py instead.",
        file=sys.stderr,
    )
    print(
        "Example: python scripts/ingest_orthofinder.py --config config/orthofinder_ingest.example.json",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
