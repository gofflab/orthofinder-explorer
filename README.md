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

### Container layout
Services:
- `web`: Flask app served by Gunicorn on `:8000` inside the Compose network.
- `nginx`: Reverse proxy on host port `8080`, forwards to `web:8000`.
- `ingest`: One-off job (profile `ingest`) that runs the ingest CLI.

Volumes:
- `orthofinder-data`: Persisted SQLite DB at `/data/orthofinder_new.db`.
- `static-assets`: Persisted static assets at `/app/app/static` shared by `web`
  and `ingest` so color palettes stay in sync after ingestion.

### Ingest data with Docker
Use the ingest service to load a new Orthofinder dataset into the shared volume:
```bash
docker compose --profile ingest run --rm \
  -v /path/to/OrthoFinder/Results:/input:ro \
  ingest --config /config/orthofinder_ingest.docker.json
```

Update `config/orthofinder_ingest.docker.json` with your actual dataset folder
name (`input_dir`) and metadata (`dataset_name`) before running the ingest. To
use a different config, append `--config /config/your_file.json` to the command.

The `input_dir` value is the container path, so the host results directory must
be mounted to `/input` (as shown above). A helper script is available:
```bash
bash scripts/ingest_docker.sh /path/to/OrthoFinder/Results Results_Feb21
```
The helper script runs against the repository's Compose project so it can be
invoked from any working directory.
You only need to edit `config/orthofinder_ingest.docker.json` when you want
non-default ingest settings (for example `mode`, `forced_clades`, or a custom
`db_path`). The helper script already supplies `input_dir` and `dataset_name`.

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
