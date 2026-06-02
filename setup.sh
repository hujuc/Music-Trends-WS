#!/usr/bin/env bash
#
# Single entry point to set up and run the Music Trends project.
#
# Usage:
#   ./setup.sh           # full flow: deps -> generate RDF -> load+infer -> run app
#   ./setup.sh build     # deps -> generate RDF -> load into GraphDB + apply SPIN rules
#   ./setup.sh full      # build + enrich artists + reload all RDF + run app
#   ./setup.sh run       # deps -> migrate -> run the Django dev server
#
# Requires: Python 3.10+, and (for `build`) a running GraphDB at GRAPHDB_URL.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT_DIR/venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
MODE="${1:-all}"

ensure_venv() {
  if [ ! -d "$VENV" ]; then
    echo "==> Creating virtual environment (venv)"
    python3 -m venv "$VENV"
  fi
  echo "==> Installing dependencies from requirements.txt"
  "$PIP" install --quiet --upgrade pip
  "$PIP" install --quiet -r "$ROOT_DIR/requirements.txt"
}

do_build() {
  echo "==> Generating RDF (normalizing_data/music.ttl)"
  ( cd "$ROOT_DIR/normalizing_data" && "$PY" create_rdf.py )
  echo "==> Loading RDF into GraphDB and applying SPIN inference rules"
  ( cd "$ROOT_DIR/normalizing_data" && "$PY" load_ttl_to_graphdb.py )
}

do_enrich() {
  echo "==> Enriching artists from Wikidata/DBpedia (patient mode)"
  ( cd "$ROOT_DIR/normalizing_data" && "$PY" enrich_artists.py --patient )
  echo "==> Reloading RDF into GraphDB to include artists_external.ttl"
  ( cd "$ROOT_DIR/normalizing_data" && "$PY" load_ttl_to_graphdb.py )
}

do_run() {
  echo "==> Starting the Django application"
  ( cd "$ROOT_DIR/django/music_trends" \
      && "$PY" manage.py migrate \
      && "$PY" manage.py runserver )
}

case "$MODE" in
  build) ensure_venv; do_build ;;
  full)  ensure_venv; do_build; do_enrich; do_run ;;
  run)   ensure_venv; do_run ;;
  all)   ensure_venv; do_build; do_run ;;
  *)
    echo "Usage: ./setup.sh [build|full|run|all]"
    exit 1
    ;;
esac
