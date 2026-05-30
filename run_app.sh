#!/bin/bash

ROOT_DIR=$(pwd)

python3 -m venv "$ROOT_DIR/venv"
"$ROOT_DIR/venv/bin/pip" install -r requirements.txt

cd "$ROOT_DIR/django/music_trends"
"$ROOT_DIR/venv/bin/python3" manage.py migrate
"$ROOT_DIR/venv/bin/python3" manage.py runserver