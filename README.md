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

- `normalizing_data/music.ttl`: generated facts (instance data) + ontology declarations used by the app. Classifications and derived relations are **not** baked in here — they are produced by the SPIN rules.
- `normalizing_data/ontology.ttl`: ontology-only layer (classes, properties, domain/range, inverse/sub/equivalent/symmetric links).
- `normalizing_data/shapes.ttl`: minimal SHACL validation shapes.
- `normalizing_data/spin_rules.py`: independent module with the SPIN inference rules (see below).
- `normalizing_data/spin_rules.ttl`: the same rules exported as SPIN RDF (`sp:`/`spin:`), loadable in GraphDB/Protégé.
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

### Inference Rules (SPIN)

The inference rules are defined in an **independent Python module**,
`normalizing_data/spin_rules.py`, so they are explicitly identified and isolated
from the data generation. Each rule implements an automatic classification or a
new relation that the RDFS/OWL engines cannot derive on their own (they need
`FILTER` / numeric or date comparisons). `create_rdf.py` only writes the base
facts; the rules below produce the derived knowledge.

| Rule (`spin:rule`) | Produces | Condition |
|---|---|---|
| `ChartedSongRule` | `type:ChartedSong` | song referenced by ≥ 1 chart entry |
| `HitSongRule` | `type:HitSong` | song with an entry where `rank <= 10` |
| `HitArtistRule` | `type:HitArtist` | artist who performs a `type:HitSong` (chains on `HitSongRule`) |
| `TrendingArtistRule` | `type:TrendingArtist` | artist with a top-10 entry dated `>= 2024-01-01` |
| `AppearsInChartRule` | `pred:appearsInChart` | new artist → chart relation, from the artist's entries |
| `CollaboratedWithRule` | `pred:collaboratedWith` | new symmetric artist ↔ artist relation (shared song) |

Each rule is stored as a SPARQL `CONSTRUCT` (SPIN `sp:text`) attached to its
target class via `spin:rule`. The module can export the rules as SPIN RDF and
apply them to GraphDB (materialization, for when the SPIN engine is not active):

```bash
cd normalizing_data
python spin_rules.py --export                 # writes spin_rules.ttl
python spin_rules.py --apply --dry-run        # prints the SPARQL updates
python spin_rules.py --apply                  # materializes inferences on GraphDB
```

Recommended GraphDB workflow:

1. Import `music.ttl` (base facts) into the `music` repository.
2. Import `ontology.ttl` (schema) — enables RDFS/OWL inferences (e.g. `pred:performer`
   from `pred:mainArtist` via `rdfs:subPropertyOf`).
3. Run `python spin_rules.py --apply` to materialize the SPIN classifications.

Quick SPARQL checks in GraphDB (after applying the rules):

```sparql
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:ChartedSong . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:HitSong . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:HitArtist . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:TrendingArtist . }
SELECT (COUNT(*) AS ?c) WHERE { ?s pred:appearsInChart ?o . }
SELECT (COUNT(*) AS ?c) WHERE { ?s pred:collaboratedWith ?o . }
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