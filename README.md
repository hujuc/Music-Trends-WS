# Music Trends WS

Django web application for exploring music trends using RDF data in a GraphDB triplestore.

## Requirements

- Python 3.10+
- GraphDB (Desktop or Server)
- Git

## Relevant Structure

- `django/music_trends/`: Django project
- `normalizing_data/`: data-to-RDF transformation script
- `normalizing_data/music.ttl`: RDF file to import into GraphDB

## 1) Python Environment Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r django/music_trends/requirements.txt
```

If you want to regenerate the RDF with the script in `normalizing_data/create_rdf.py`, also install:

```bash
pip install pandas rdflib rapidfuzz
```

## 2) Prepare GraphDB

1. Open GraphDB.
2. Create a repository named `music`.
3. Import `normalizing_data/music.ttl` into that repository.

Expected default endpoint:

- `http://localhost:7200/repositories/music`

## 3) (Optional) Regenerate RDF

If you need to recreate `music.ttl` from the CSV files:

```bash
cd normalizing_data
python create_rdf.py
```

At the end, the script writes/updates `normalizing_data/music.ttl`.

## 4) Configure App Environment Variables

The app already works without extra variables if you use the default endpoint above.

Optionally, you can define:

- `GRAPHDB_ENDPOINT` (default: `http://localhost:7200/repositories/music`)
- `GRAPHDB_TIMEOUT` in seconds (default: `10`)

Example:

```bash
export GRAPHDB_ENDPOINT="http://localhost:7200/repositories/music"
export GRAPHDB_TIMEOUT="10"
```

## 5) Run the Django Application

```bash
cd django/music_trends
python manage.py migrate
python manage.py runserver
```

Open in browser:

- Home: `http://127.0.0.1:8000/`
- Songs: `http://127.0.0.1:8000/songs/`

## 6) Quick Verification

With the app running:

1. Go to `/songs/`.
2. Confirm the song list appears.
3. Test the artist filter.

If GraphDB is offline or the endpoint is wrong, the page shows an error message instead of crashing.

## Troubleshooting

- GraphDB connection error:
	- ensure GraphDB is running;
	- ensure the `music` repository exists;
	- ensure `GRAPHDB_ENDPOINT` is correct.
- `ModuleNotFoundError` when running scripts:
	- activate the virtual environment;
	- reinstall dependencies with `pip install -r django/music_trends/requirements.txt`.
- No data appears in `/songs/`:
	- ensure `normalizing_data/music.ttl` was imported into the correct repository.