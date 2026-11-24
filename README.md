# orthofinder-explorer
Parsing tool to create a relational DB from Orthofinder output and associated web exploration tool.

## Docker quickstart (Gunicorn + Nginx)
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

### Run the web app
Build and run the web app behind Nginx:
```bash
docker compose up --build
```

The app will be available at:
```
https://cephexplorer.gofflab.org
```

The SQLite database is persisted in the `orthofinder-data` volume. To use a
custom database file, update `ORTHOFINDER_DB_PATH` in `docker-compose.yml` and
mount the path into `/data`.
The ingest job writes `species_colors.json` into `/data`, and the web app serves
it from there via `/species-colors.json` (configured by
`ORTHOFINDER_SPECIES_COLORS_PATH` in `docker-compose.yml`).

### Container layout
Services:
- `web`: Flask app served by Gunicorn on `:8000` inside the Compose network.
- `nginx`: Reverse proxy on host ports `80`/`443`, forwards to `web:8000`.
- `ingest`: One-off job (profile `ingest`) that runs the ingest CLI.

Volumes:
- `orthofinder-data`: Persisted SQLite DB at `/data/orthofinder_new.db`.
  `species_colors.json` lives alongside the DB at `/data/species_colors.json`.

For local development without TLS, update `deploy/nginx.conf` and the Nginx
ports in `docker-compose.yml` to use a non-privileged port (for example
`8080:80`) and remove the `/etc/letsencrypt` mount.

### Local Docker override
For local testing without TLS, use the provided override file:
```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
```

Then visit:
```
http://localhost:8080
```

### Species pages
The Species (`/species`) and Species Comparison (`/compare`) pages summarise
gene-family content per species and highlight expansions and contractions
between any two species. They work on any existing database. To enable the
tree-ordered and gene-age views, and to add the indexes they benefit from, run
the upgrade script once against a database built by an older version. Rebuild
the ingest image first so that it contains the script:
```bash
docker compose --profile ingest build ingest
```
```bash
docker compose --profile ingest run --rm \
  -v /path/to/OrthoFinder/Results_XXXX:/input:ro \
  --entrypoint python ingest scripts/upgrade_db.py \
  --db /data/orthofinder_new.db \
  --species-tree /input/Species_Tree/SpeciesTree_rooted.txt
```
New ingests store the species tree and create the indexes automatically. See
`docs/species-pages.rst` for how each statistic is defined.

## Local development (non-Docker)
Use the ingestion script to build or append to the SQLite database without editing code paths.

Example using the sample config:
```bash
python scripts/ingest_orthofinder.py --config config/orthofinder_ingest.example.json
```

To override the DB used by the Flask app, set:
```bash
export ORTHOFINDER_DB_PATH=instance/orthofinder_new.db
```
To try the UI without real data, build a small synthetic database:
```bash
python scripts/build_demo_db.py --db instance/demo.db
```
```bash
ORTHOFINDER_DB_PATH=$PWD/instance/demo.db python run.py
```
To enable Google Analytics (GA4), set:
```bash
export GOOGLE_ANALYTICS_MEASUREMENT_ID=G-XXXXXXX
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
