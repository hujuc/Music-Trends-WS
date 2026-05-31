# Music Trends WS

Django web application for exploring music trends using RDF data in a GraphDB
triplestore, with an OWL ontology and SPIN inference rules.

## Requirements

- Python 3.10+
- GraphDB (Desktop or Server) running and reachable at `http://localhost:7200`
- Git

## Project Structure

- `django/music_trends/` — Django project (the web app)
- `normalizing_data/` — data → RDF pipeline, ontology, SPIN rules and GraphDB loader
  - `create_rdf.py` — builds `music.ttl` (facts + ontology schema) from the CSV datasets
  - `ontology.ttl` — ontology-only layer (RDFS/OWL)
  - `shapes.ttl` — SHACL validation shapes
  - `spin_rules.py` / `spin_rules.ttl` — SPIN inference rules (module + RDF export)
  - `load_ttl_to_graphdb.py` — creates the repo, loads the RDF, applies the SPIN rules
- `requirements.txt` — single dependency file
- `setup.sh` — single entry point: install → build data → run app

## Quick Start

1. Start GraphDB — it must be reachable at `http://localhost:7200`.
2. From the repository root:

```bash
./setup.sh
```

That one command:

- creates a `venv` and installs `requirements.txt`;
- generates the RDF (`normalizing_data/music.ttl`) from the CSV datasets;
- creates the `music` repository in GraphDB and loads the facts, ontology and SHACL shapes;
- applies the SPIN inference rules (materializes the classifications and derived relations);
- runs the Django development server.

Then open:

- Home: http://127.0.0.1:8000/
- Songs: http://127.0.0.1:8000/songs/

### Partial runs

```bash
./setup.sh build   # (re)generate RDF + load into GraphDB + apply SPIN rules
./setup.sh full    # build + enrichment (Wikidata/DBpedia) + reload + run server
./setup.sh run     # migrate + run the Django server (data already loaded)
```

### Complete database (everything, including external enrichment)

Use this when you want a fully populated repository (base RDF + ontology + SHACL
+ SPIN inferences + DBpedia/Wikidata enrichment):

```bash
# from repository root
./setup.sh full
```

Why this order:

- `setup.sh full` creates base RDF, enriches artists, reloads all RDF layers,
  reapplies SPIN rules, runs migrations, and starts the app.

## Manual Steps (alternative to setup.sh)

```bash
# 1. environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. (re)generate the RDF from the CSVs
cd normalizing_data
python create_rdf.py

# 3. load into GraphDB + apply SPIN rules (GraphDB must be running)
python load_ttl_to_graphdb.py

# 4. run the app
cd ../django/music_trends
python manage.py migrate
python manage.py runserver
```

Default endpoint: `http://localhost:7200/repositories/music`.

## App Environment Variables (optional)

The app works without extra variables if you use the default endpoint. Optionally:

- `GRAPHDB_ENDPOINT` (default: `http://localhost:7200/repositories/music`)
- `GRAPHDB_TIMEOUT` in seconds (default: `10`)

The loader also reads `GRAPHDB_URL` (default `http://localhost:7200`) and
`REPOSITORY` (default `music`).

## Semantic Layer

### Ontology and Validation Artifacts

- `normalizing_data/music.ttl`: generated facts (instance data) + ontology declarations used by the app. Classifications and derived relations are **not** baked in here — they are produced by the SPIN rules.
- `normalizing_data/ontology.ttl`: ontology-only layer (classes, properties, domain/range, inverse/sub/equivalent/symmetric links).
- `normalizing_data/shapes.ttl`: minimal SHACL validation shapes.
- `normalizing_data/spin_rules.py`: independent module with the SPIN inference rules (see below).
- `normalizing_data/spin_rules.ttl`: the same rules exported as SPIN RDF (`sp:`/`spin:`), loadable in GraphDB/Protégé.
- `normalizing_data/enrich_artists.py`: external enrichment module (DBpedia + Wikidata).
- `normalizing_data/artists_external.ttl`: artist triples fetched from DBpedia/Wikidata.
- `docs/semantic_demo_queries.rq`: SPARQL queries for the semantic demo (genres, charts, albums, inference checks).

Quick validation commands:

```bash
cd normalizing_data
python -c "from rdflib import Graph; g=Graph(); g.parse('music.ttl', format='turtle'); print(len(g))"
python -c "from rdflib import Graph; Graph().parse('ontology.ttl', format='turtle'); Graph().parse('shapes.ttl', format='turtle'); print('ok')"
```

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

(`load_ttl_to_graphdb.py` already runs `--apply` after loading the data.)

Quick SPARQL checks in GraphDB (after applying the rules):

```sparql
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:ChartedSong . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:HitSong . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:HitArtist . }
SELECT (COUNT(*) AS ?c) WHERE { ?s a type:TrendingArtist . }
SELECT (COUNT(*) AS ?c) WHERE { ?s pred:appearsInChart ?o . }
SELECT (COUNT(*) AS ?c) WHERE { ?s pred:collaboratedWith ?o . }
```

### External Enrichment (DBpedia + Wikidata)

`normalizing_data/enrich_artists.py` complements the artist data with information
that is not in the original dataset, by querying the **DBpedia** and **Wikidata**
SPARQL endpoints programmatically (via `SPARQLWrapper`):

- **Wikidata** → country, genre, image, birth/inception date, official website,
  MusicBrainz id, short description;
- **DBpedia** → thumbnail, birth place, birth date, abstract (when available);
- both → `owl:sameAs` links to the external entities.

```bash
cd normalizing_data
python enrich_artists.py --names "Adele,Coldplay"   # quick test on specific names
python enrich_artists.py --limit 200                # first 200 artists
python enrich_artists.py                            # all artists (slow; rate-limited)
python enrich_artists.py --rebuild                  # rebuild the TTL from cache (no network)
python enrich_artists.py --apply                    # also insert into GraphDB
```

Notes:

- Results are cached **per source** in `enrichment_cache.json`: only successful
  queries are final, so a re-run **retries the sources that failed** (e.g. Wikidata
  while it was rate-limited) without repeating the ones that already worked. The
  output (`artists_external.ttl`) accumulates everything fetched so far.
- The app reads from **GraphDB**, not from the file. `load_ttl_to_graphdb.py`
  (and therefore `setup.sh build`) loads `artists_external.ttl` automatically when
  it exists. After enriching more artists, push the new data with
  `python enrich_artists.py --rebuild --apply` (or re-run `load_ttl_to_graphdb.py`).
- Matching is by exact name, so coverage is partial (ambiguous/garbled names are
  skipped). Wikidata may aggressively rate-limit; the module retries and falls
  back to DBpedia, and you can re-run later to fill the gaps.
- The Wikidata endpoint is configurable (`WIKIDATA_SPARQL_ENDPOINT` env var or
  `--wikidata-endpoint`). It defaults to the official WDQS
  (`https://query.wikidata.org/sparql`). When WDQS is in outage/rate-limited, you
  can point it at a **SPARQL mirror** (still SPARQL + `SPARQLWrapper`), e.g. QLever
  `https://qlever.cs.uni-freiburg.de/api/wikidata`. The query is endpoint-portable
  (no `wikibase:label` service dependency).

## Verification

With the app running:

1. Go to `/songs/` and confirm the song list appears.
2. Test the artist filter.

If GraphDB is offline or the endpoint is wrong, the page shows an error message
instead of crashing.

## Troubleshooting

- GraphDB connection error:
  - ensure GraphDB is running;
  - ensure the `music` repository exists (the loader creates it automatically);
  - ensure `GRAPHDB_ENDPOINT` / `GRAPHDB_URL` are correct.
- `ModuleNotFoundError` when running scripts:
  - activate the virtual environment;
  - reinstall dependencies with `pip install -r requirements.txt`.
- No data appears in `/songs/`:
  - ensure `load_ttl_to_graphdb.py` ran successfully against the correct repository.
