#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: bash scripts/ingest_docker.sh /path/to/Results [dataset_name]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${PROJECT_ROOT}/config/orthofinder_ingest.docker.json"

HOST_RESULTS_PATH="$1"
DATASET_NAME="${2:-$(basename "${HOST_RESULTS_PATH}")}"

if [ ! -d "${HOST_RESULTS_PATH}" ]; then
  echo "Error: results directory not found: ${HOST_RESULTS_PATH}" >&2
  exit 1
fi

if [ ! -f "${CONFIG_PATH}" ]; then
  echo "Error: config not found: ${CONFIG_PATH}" >&2
  exit 1
fi

docker compose \
  --project-directory "${PROJECT_ROOT}" \
  -f "${PROJECT_ROOT}/docker-compose.yml" \
  --profile ingest run --rm \
  -v "${HOST_RESULTS_PATH}":/input:ro \
  ingest --config /config/orthofinder_ingest.docker.json \
  --input-dir /input --dataset-name "${DATASET_NAME}"
