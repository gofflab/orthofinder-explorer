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

## Docker (Gunicorn + Nginx)
Build and run the web app behind Nginx:
```bash
docker compose up --build
```

The app will be available at:
```
http://localhost:8080
```

The SQLite database is persisted in the `orthofinder-data` volume. To use a
custom database file, update `ORTHOFINDER_DB_PATH` in `docker-compose.yml` and
mount the path into `/data`.
Static assets are stored in the `static-assets` volume so the ingest job can
update `app/static/species_colors.json` for the web container.

### Ingest data with Docker
Use the ingest service to load a new Orthofinder dataset into the shared volume:
```bash
docker compose --profile ingest run --rm \
  -v /path/to/OrthoFinder/Results:/input:ro \
  ingest
```

Update `config/orthofinder_ingest.docker.json` with your actual dataset folder
name (`input_dir`) and metadata (`dataset_name`) before running the ingest. To
use a different config, append `--config /config/your_file.json` to the command.

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
