# orthofinder-explorer
Parsing tool to create a relational DB from Orthofinder output and associated web exploration tool.

## Ingest new Orthofinder results
Use the ingestion script to build or append to the SQLite database without editing code paths.

Example using the sample config:
```bash
python scripts/ingest_orthofinder.py --config config/orthofinder_ingest.example.json
```

To override the DB used by the Flask app, set:
```bash
export ORTHOFINDER_DB_PATH=instance/orthofinder_new.db
```

## Documentation
Docs are built with Sphinx and live in `docs/`.
Serve docs locally:
```bash
./scripts/docs.sh serve
```

Build docs:
```bash
./scripts/docs.sh build
```
