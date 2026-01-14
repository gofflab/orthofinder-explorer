#!/usr/bin/env sh
set -eu

command="${1:-serve}"
root_dir="$(cd "$(dirname "$0")/.." && pwd)"
docs_dir="${root_dir}/docs"
build_dir="${docs_dir}/_build/html"

case "$command" in
  serve)
    sphinx-build -b html "${docs_dir}" "${build_dir}"
    python -m http.server --directory "${build_dir}" 8000
    ;;
  build)
    sphinx-build -b html "${docs_dir}" "${build_dir}"
    ;;
  *)
    echo "Usage: ./scripts/docs.sh [serve|build]" >&2
    exit 2
    ;;
esac
