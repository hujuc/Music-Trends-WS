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

### Ontology and Validation Artifacts

After running the generator, these RDF artifacts are available:

- `normalizing_data/music.ttl`: full generated data + ontology declarations used by the app.
- `normalizing_data/ontology.ttl`: ontology-only layer (classes, properties, domain/range, inverse/sub/equivalent links).
- `normalizing_data/shapes.ttl`: minimal SHACL validation shapes.
- `docs/semantic_demo_queries.rq`: SPARQL queries for semantic demo (genres, charts, albums, inference checks).

Quick validation commands:

```bash
cd normalizing_data
python -c "from rdflib import Graph; g=Graph(); g.parse('music.ttl', format='turtle'); print(len(g))"
python -c "from rdflib import Graph; Graph().parse('ontology.ttl', format='turtle'); Graph().parse('shapes.ttl', format='turtle'); print('ok')"
```

Compatibility note:

- Existing predicates used by the Django app were preserved.
- New semantic predicates (`pred:hasGenre`, `pred:inChart`, `pred:album`, `pred:performer`) were added incrementally.

### Implemented Inferences (RDFS/OWL + Materialized)

The project now includes schema-level semantics and materialized inferred triples generated in `normalizing_data/create_rdf.py`.

Schema-level additions:

- New classes: `type:ChartedSong`, `type:HitSong`, `type:HitArtist`, `type:TrendingArtist`.
- New properties: `pred:hasChartEntry` and `pred:appearsInChart`.
- `pred:hasChartEntry` is declared as inverse of `pred:song`.

Materialized inferred data emitted in `music.ttl`:

- `type:ChartedSong`: songs with at least one chart entry.
- `type:HitSong`: songs with at least one entry where `pred:rank <= 10`.
- `type:HitArtist`: artists who perform at least one `type:HitSong`.
- `type:TrendingArtist`: artists with a top-10 song from `2024-01-01` onward.
- `pred:hasChartEntry`: explicit song-to-entry relation.
- `pred:appearsInChart`: explicit artist-to-chart relation.

Quick SPARQL checks in GraphDB:

```sparql
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:ChartedSong . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:HitSong . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:HitArtist . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:TrendingArtist . }
SELECT (COUNT(*) AS ?c) WHERE { ?s pred:hasChartEntry ?o . }
SELECT (COUNT(*) AS ?c) WHERE { ?s pred:appearsInChart ?o . }
```

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