#!/bin/bash

ROOT_DIR=$(pwd)

python3 -m venv "$ROOT_DIR/venv"
"$ROOT_DIR/venv/bin/pip" install -r requirements.txt

cd "$ROOT_DIR/normalizing_data"
"$ROOT_DIR/venv/bin/python3" create_rdf.py
"$ROOT_DIR/venv/bin/python3" load_ttl_to_graphdb.py