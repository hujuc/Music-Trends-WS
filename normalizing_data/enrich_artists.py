"""
Enriquecimento dos dados dos artistas a partir da DBpedia e da Wikidata.

Acesso programatico aos endpoints SPARQL das duas fontes (via SPARQLWrapper),
para complementar o conjunto de dados do SI com informacao que nao existe no
dataset original (pais de origem, biografia, imagem, data de nascimento/formacao,
sitio oficial, MusicBrainz id) e ligacoes `owl:sameAs` as entidades externas.

Estrategia (a Wikidata limita o numero de pedidos):
  * os artistas sao agrupados em lotes e consultados com `VALUES` (poucos pedidos);
  * cache local POR FONTE: so as consultas bem-sucedidas ficam definitivas; uma
    fonte que falhou (ex.: Wikidata em rate-limit) e re-tentada numa nova execucao,
    enquanto as que ja resultaram nao se repetem;
  * retries com backoff em caso de 429 / falha de rede (fail-fast);
  * filtro por entidades efetivamente musicais (ocupacao musico/cantor/... ou
    banda/grupo) para reduzir falsos positivos com nomes ambiguos.

Uso:
    python enrich_artists.py --limit 50              # testa com 50 artistas
    python enrich_artists.py --names "Drake,Adele"   # testa nomes especificos
    python enrich_artists.py                         # todos (interativo; salta rate-limit)
    python enrich_artists.py --patient               # nao-assistido: honra Retry-After
    python enrich_artists.py --rebuild               # regenera o TTL da cache (sem rede)
    python enrich_artists.py --apply                 # insere o resultado na GraphDB
    # mirror SPARQL (quando o WDQS oficial esta em outage) -- continua SPARQL + SPARQLwrapper:
    python enrich_artists.py --wikidata-endpoint https://qlever.cs.uni-freiburg.de/api/wikidata
"""

import argparse
import json
import os
import sys
import time

import requests
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
from SPARQLWrapper import JSON, SPARQLWrapper

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MUSIC_TTL = os.path.join(BASE_DIR, "music.ttl")
OUTPUT_TTL = os.path.join(BASE_DIR, "artists_external.ttl")
CACHE_FILE = os.path.join(BASE_DIR, "enrichment_cache.json")

# Endpoint SPARQL da Wikidata. Por omissao usa o WDQS oficial (o que o enunciado
# pede). E configuravel (env WIKIDATA_SPARQL_ENDPOINT ou --wikidata-endpoint) para
# se poder apontar a um MIRROR SPARQL quando o WDQS oficial esta em outage/rate-limit
# -- continua a ser SPARQL via SPARQLwrapper. Mirror conhecido (QLever):
#   https://qlever.cs.uni-freiburg.de/api/wikidata
WIKIDATA_ENDPOINT = os.getenv(
    "WIKIDATA_SPARQL_ENDPOINT", "https://query.wikidata.org/sparql"
)
DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"
USER_AGENT = "MusicTrendsWS/1.0 (academic project; WS course)"

BASE = Namespace("http://music.org/")
PRED = Namespace("http://music.org/pred/")
TYPE = Namespace("http://music.org/type/")

DEFAULT_ENDPOINT = os.getenv(
    "GRAPHDB_ENDPOINT", "http://localhost:7200/repositories/music"
)


# ── Carregar artistas (nome -> URI) a partir dos factos ───────────────────────
def load_artists():
    g = Graph()
    g.parse(MUSIC_TTL, format="turtle")
    artists = {}
    for s in g.subjects(RDF.type, TYPE.Artist):
        for name in g.objects(s, PRED.name):
            artists[str(name)] = str(s)
            break
    return artists


# Configuracao de resiliencia (alterada por --patient no main).
#   fail-fast (default): tenta pouco e desiste -> bom para corridas interativas.
#   patient: honra o Retry-After do servidor e tenta mais vezes -> bom para
#            corridas nao-assistidas (deixar a preencher a Wikidata em background).
RETRY_CONFIG = {"retries": 2, "wait_429": 20.0, "honor_retry_after": False, "max_wait": 1100.0}


def _retry_after_seconds(exc):
    """Le o header Retry-After da resposta 429, se existir (em segundos)."""
    headers = getattr(exc, "headers", None)
    if headers is None:
        headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        try:
            value = headers.get("Retry-After")
        except AttributeError:
            value = None
        if value and str(value).strip().isdigit():
            return int(str(value).strip())
    return None


# ── Execucao resiliente de uma query SPARQL ───────────────────────────────────
def run_sparql(endpoint, query):
    client = SPARQLWrapper(endpoint, agent=USER_AGENT)
    client.setQuery(query)
    client.setReturnFormat(JSON)
    host = endpoint.split("//")[1].split("/")[0]
    cfg = RETRY_CONFIG
    for attempt in range(cfg["retries"]):
        try:
            return client.query().convert()["results"]["bindings"]
        except Exception as exc:  # HTTPError (429/5xx), timeouts, etc.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            code = status or getattr(exc, "code", None)
            if attempt == cfg["retries"] - 1:
                print(f"  ! {host} indisponivel ({type(exc).__name__} {code or ''}); a saltar",
                      file=sys.stderr)
                return None
            wait = cfg["wait_429"]
            if code == 429:
                retry_after = _retry_after_seconds(exc)
                if cfg["honor_retry_after"] and retry_after:
                    wait = min(retry_after, cfg["max_wait"])
                    print(f"  ! {host} pediu Retry-After={retry_after}s; a aguardar {wait:.0f}s",
                          file=sys.stderr)
                else:
                    print(f"  ! {host} em rate-limit (429); retry em {wait:.0f}s "
                          f"(usa --patient para honrar Retry-After)", file=sys.stderr)
            else:
                print(f"  ! {host} falhou ({code or type(exc).__name__}); retry em {wait:.0f}s",
                      file=sys.stderr)
            time.sleep(wait)
    return None


def _values_labels(names):
    def esc(n):
        return n.replace("\\", "\\\\").replace('"', '\\"')

    return " ".join(f'"{esc(n)}"@en' for n in names)


# ── Wikidata ──────────────────────────────────────────────────────────────────
def query_wikidata(names):
    # P106 occupations: singer, musician, rapper, guitarist, singer-songwriter, composer.
    # P31 classes: musical group, band.
    # Query PORTAVEL: PREFIX explicitos e labels via rdfs:label (em vez do
    # SERVICE wikibase:label, que so existe no WDQS oficial). Assim corre tanto
    # no WDQS como em mirrors SPARQL (ex.: QLever).
    # Casa por rdfs:label OU skos:altLabel. Como um nome pode ser ambiguo (ex.:
    # "Train" e a banda americana mas tambem o alias da japonesa "Densha"),
    # recolhemos TODOS os candidatos e escolhemos o melhor por sinais de
    # desambiguacao: match por rdfs:label (vs altLabel) > tem artigo na Wikipedia
    # EN > tem MusicBrainz id.
    values = _values_labels(names)
    query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX schema: <http://schema.org/>
    SELECT ?label ?item ?viaLabel ?enwiki ?countryLabel ?genreLabel ?image
           ?birth ?inception ?website ?mbid ?desc WHERE {{
      VALUES ?label {{ {values} }}
      {{ {{ ?item rdfs:label ?label . BIND(1 AS ?viaLabel) }}
         UNION
         {{ ?item skos:altLabel ?label . BIND(0 AS ?viaLabel) }} }}
      {{ {{ ?item wdt:P106 ?occ .
            VALUES ?occ {{ wd:Q177220 wd:Q639669 wd:Q2252262 wd:Q855091 wd:Q488205 wd:Q36834 }} }}
         UNION
         {{ ?item wdt:P31 ?gtype . ?gtype wdt:P279* wd:Q2088357 }} }}
      OPTIONAL {{ ?article schema:about ?item ;
                           schema:isPartOf <https://en.wikipedia.org/> . BIND(1 AS ?enwiki) }}
      OPTIONAL {{ ?item wdt:P27 ?country .
                  ?country rdfs:label ?countryLabel . FILTER(lang(?countryLabel) = "en") }}
      OPTIONAL {{ ?item wdt:P136 ?genre .
                  ?genre rdfs:label ?genreLabel . FILTER(lang(?genreLabel) = "en") }}
      OPTIONAL {{ ?item wdt:P18 ?image . }}
      OPTIONAL {{ ?item wdt:P569 ?birth . }}
      OPTIONAL {{ ?item wdt:P571 ?inception . }}
      OPTIONAL {{ ?item wdt:P856 ?website . }}
      OPTIONAL {{ ?item wdt:P434 ?mbid . }}
      OPTIONAL {{ ?item schema:description ?desc . FILTER(lang(?desc) = "en") }}
    }}
    """
    rows = run_sparql(WIKIDATA_ENDPOINT, query)
    # name -> {item -> dados agregados + sinais}
    candidates = {}
    for r in rows or []:
        name = r["label"]["value"]
        item = r["item"]["value"]
        by_item = candidates.setdefault(name, {})
        cand = by_item.get(item)
        if cand is None:
            cand = {
                "item": item, "country": None, "genres": [], "image": None,
                "birth": None, "inception": None, "website": None,
                "mbid": None, "desc": None, "_via_label": False, "_enwiki": False,
            }
            by_item[item] = cand
        if r.get("viaLabel", {}).get("value") == "1":
            cand["_via_label"] = True
        if r.get("enwiki", {}).get("value") == "1":
            cand["_enwiki"] = True
        genre = r.get("genreLabel", {}).get("value")
        if genre and genre not in cand["genres"]:
            cand["genres"].append(genre)
        for field, key in (("country", "countryLabel"), ("image", "image"),
                           ("birth", "birth"), ("inception", "inception"),
                           ("website", "website"), ("mbid", "mbid"), ("desc", "desc")):
            if not cand[field]:
                value = r.get(key, {}).get("value")
                if value:
                    cand[field] = value

    out = {}
    for name, by_item in candidates.items():
        best = max(by_item.values(), key=lambda c: (
            c["_via_label"], c["_enwiki"], bool(c["mbid"]), bool(c["desc"]),
            len(c["genres"]),
        ))
        best.pop("_via_label", None)
        best.pop("_enwiki", None)
        out[name] = best
    return out, rows is not None  # (resultados, query teve sucesso)


# ── DBpedia ───────────────────────────────────────────────────────────────────
def query_dbpedia(qid_by_name):
    """DBpedia ANCORADA ao QID da Wikidata (owl:sameAs), nao ao nome.

    Casar por nome confunde homonimos (ex.: uma cantora vs. uma enfermeira com o
    mesmo nome). Como a Wikidata ja identificou a entidade certa (filtra por
    ocupacao musical), buscamos o recurso DBpedia que e `owl:sameAs` desse QID --
    garantindo que ambas as fontes falam da MESMA pessoa.

    qid_by_name: {nome_artista: URI_da_entidade_wikidata}
    """
    if not qid_by_name:
        return {}, True
    qid_to_name = {qid: name for name, qid in qid_by_name.items()}
    values = " ".join(f"<{q}>" for q in qid_by_name.values())
    query = f"""
    PREFIX dbo: <http://dbpedia.org/ontology/>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?wd ?a ?abstract (SAMPLE(?th) AS ?thumbnail)
           (SAMPLE(?bpl) AS ?birthPlace) WHERE {{
      VALUES ?wd {{ {values} }}
      ?a owl:sameAs ?wd .
      FILTER(strstarts(str(?a), "http://dbpedia.org/resource/"))
      # Por vezes um lugar partilha (erradamente) o mesmo QID que a banda
      # (ex.: "Train, Bavaria" vs. a banda Train). Um artista nunca e um lugar.
      FILTER NOT EXISTS {{ ?a a dbo:Place }}
      OPTIONAL {{ ?a dbo:abstract ?abstract . FILTER(lang(?abstract) = "en") }}
      OPTIONAL {{ ?a dbo:thumbnail ?th . }}
      OPTIONAL {{ ?a dbo:birthPlace ?bplR . ?bplR rdfs:label ?bpl .
                  FILTER(lang(?bpl) = "en") }}
    }}
    GROUP BY ?wd ?a ?abstract
    """
    rows = run_sparql(DBPEDIA_ENDPOINT, query)
    out = {}
    for r in rows or []:
        name = qid_to_name.get(r["wd"]["value"])
        if not name:
            continue
        thumb = r.get("thumbnail", {}).get("value")
        entry = out.setdefault(
            name, {"resource": None, "abstract": None, "thumbnail": None, "birthPlace": None}
        )
        # Varios recursos podem apontar ao mesmo QID (ex.: Adele e Adele_(singer));
        # prefere o que tem thumbnail e une os campos disponiveis.
        if entry["resource"] is None or (thumb and not entry["thumbnail"]):
            entry["resource"] = r["a"]["value"]
        for key in ("abstract", "thumbnail", "birthPlace"):
            value = r.get(key, {}).get("value")
            if value and not entry[key]:
                entry[key] = value
    return out, rows is not None  # (resultados, query teve sucesso)


# ── Construir as triplas de enriquecimento ────────────────────────────────────
def _date(value):
    if not value:
        return None
    date_text = value[:10]
    if date_text.count("-") < 2:
        return None
    return Literal(date_text, datatype=XSD.date)


def add_triples(graph, artist_uri, wd, db):
    a = URIRef(artist_uri)
    wd = wd or {}
    db = db or {}

    # owl:sameAs para as entidades externas (rastreabilidade).
    if wd.get("item"):
        graph.add((a, OWL.sameAs, URIRef(wd["item"])))
    if db.get("resource"):
        graph.add((a, OWL.sameAs, URIRef(db["resource"])))

    # Wikidata (mais rico): pais, genero, imagem, sitio, MusicBrainz, descricao.
    if wd.get("country"):
        graph.add((a, PRED.originCountry, Literal(wd["country"])))
    genres = wd.get("genres") or []
    if isinstance(genres, str):
        genres = [genres]
    if not genres and wd.get("genre"):
        genres = [wd["genre"]]
    for genre in genres:
        graph.add((a, PRED.externalGenre, Literal(genre)))
    if wd.get("image"):
        graph.add((a, PRED.image, URIRef(wd["image"])))
    if wd.get("inception"):
        graph.add((a, PRED.inceptionDate, _date(wd["inception"])))
    if wd.get("website"):
        graph.add((a, PRED.website, URIRef(wd["website"])))
    if wd.get("mbid"):
        graph.add((a, PRED.musicBrainzId, Literal(wd["mbid"])))
    if wd.get("desc"):
        graph.add((a, PRED.description, Literal(wd["desc"], lang="en")))

    # DBpedia: thumbnail, local de nascimento e abstract (quando disponivel).
    if db.get("thumbnail"):
        graph.add((a, PRED.thumbnail, URIRef(db["thumbnail"])))
    if db.get("birthPlace"):
        graph.add((a, PRED.birthPlace, Literal(db["birthPlace"])))
    if db.get("abstract"):
        graph.add((a, PRED.abstract, Literal(db["abstract"], lang="en")))

    # Data de nascimento: preferir a Wikidata, senao a DBpedia.
    birth = _date(wd.get("birth")) or _date(db.get("birth"))
    if birth:
        graph.add((a, PRED.birthDate, birth))


def build_graph(results, artists):
    g = Graph()
    g.bind("music", BASE)
    g.bind("pred", PRED)
    g.bind("owl", OWL)
    enriched = 0
    for name, data in results.items():
        uri = artists.get(name)
        if not uri or not (data.get("wd") or data.get("db")):
            continue
        add_triples(g, uri, data.get("wd"), data.get("db"))
        enriched += 1
    return g, enriched


# ── Cache ─────────────────────────────────────────────────────────────────────
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)


# ── GraphDB ───────────────────────────────────────────────────────────────────
def apply_to_graphdb(ttl_path, endpoint):
    statements = endpoint.rstrip("/") + "/statements"
    with open(ttl_path, "rb") as f:
        resp = requests.post(statements, headers={"Content-Type": "text/turtle"}, data=f)
    resp.raise_for_status()
    print(f"artists_external.ttl inserido na GraphDB ({endpoint}).")


# ── Pipeline ──────────────────────────────────────────────────────────────────
def chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def source_ok(entry, source):
    """A fonte (`wd`/`db`) ja foi consultada com SUCESSO para este artista?

    So as consultas bem-sucedidas (haja ou nao match) ficam definitivas. Uma
    falha (ex.: Wikidata em rate-limit -> sem `*_ok`) e re-tentada na proxima
    execucao. Migra entradas antigas: ter dados => considera-se sucesso.
    """
    if not entry:
        return False
    flag = entry.get(f"{source}_ok")
    if flag is not None:
        return flag
    return entry.get(source) is not None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Enrich artist data from DBpedia and Wikidata."
    )
    parser.add_argument("--limit", type=int, default=None, help="max artists to process")
    parser.add_argument("--names", help="comma-separated artist names (testing)")
    parser.add_argument("--batch-size", type=int, default=40, help="labels per query")
    parser.add_argument("--sleep", type=float, default=2.0, help="seconds between batches")
    parser.add_argument("--no-cache", action="store_true", help="ignore the local cache")
    parser.add_argument("--output", default=OUTPUT_TTL, help="output TTL path")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the TTL from the cache only (no network)")
    parser.add_argument("--patient", action="store_true",
                        help="honour the server Retry-After and retry more (unattended runs)")
    parser.add_argument("--apply", action="store_true", help="insert the result into GraphDB")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="GraphDB endpoint")
    parser.add_argument("--wikidata-endpoint", default=None,
                        help="override the Wikidata SPARQL endpoint (e.g. a QLever "
                             "mirror) when the official WDQS is rate-limited")
    args = parser.parse_args(argv)

    if args.patient:
        RETRY_CONFIG.update(retries=6, honor_retry_after=True)

    if args.wikidata_endpoint:
        global WIKIDATA_ENDPOINT
        WIKIDATA_ENDPOINT = args.wikidata_endpoint
        print(f"Wikidata endpoint: {WIKIDATA_ENDPOINT}")

    artists = load_artists()
    print(f"{len(artists)} artistas nos factos.")

    if args.names:
        wanted = [n.strip() for n in args.names.split(",") if n.strip()]
        names = [n for n in wanted if n in artists] or wanted
        # permite testar nomes que talvez nao estejam no dataset
        for n in wanted:
            artists.setdefault(n, str(BASE[f"artist/test-{n.replace(' ', '_')}"]))
    else:
        names = sorted(artists.keys())  # ordem estavel -> --limit reproduzivel
        if args.limit:
            names = names[:args.limit]

    cache = {} if args.no_cache else load_cache()

    if args.rebuild:
        print(f"modo rebuild: a regenerar o TTL a partir de {len(cache)} entradas em cache.")
    else:
        # Por fonte: so consulta quem ainda nao tem consulta bem-sucedida. Assim
        # uma re-execucao preenche o que ficou em falta (ex.: Wikidata bloqueada),
        # sem repetir as consultas que ja resultaram.
        pending_wd = [n for n in names if not source_ok(cache.get(n), "wd")]
        print(f"{len(names)} artistas | a (re)consultar Wikidata: {len(pending_wd)}.")

        for batch in chunks(pending_wd, args.batch_size):
            print(f"  Wikidata: lote de {len(batch)}...")
            data, ok = query_wikidata(batch)
            for name in batch:
                entry = cache.setdefault(name, {})
                if ok:
                    entry["wd"] = data.get(name)
                    entry["wd_ok"] = True
                else:
                    entry.setdefault("wd", None)
                    entry["wd_ok"] = False
            save_cache(cache)
            time.sleep(args.sleep)

        # DBpedia ancorada ao QID da Wikidata -> so corre para artistas cuja
        # Wikidata ja foi resolvida (wd_ok). Os que tem QID sao consultados por
        # owl:sameAs; os que a Wikidata nao encontrou ficam sem DBpedia (evita
        # falsos positivos por nome, ex.: homonimos).
        pending_db = [
            n for n in names
            if source_ok(cache.get(n), "wd") and not source_ok(cache.get(n), "db")
        ]
        print(f"a (re)consultar DBpedia (via QID): {len(pending_db)}.")
        for batch in chunks(pending_db, args.batch_size):
            qid_by_name = {}
            for name in batch:
                wd = (cache.get(name) or {}).get("wd")
                if wd and wd.get("item"):
                    qid_by_name[name] = wd["item"]
            print(f"  DBpedia: lote de {len(batch)} ({len(qid_by_name)} com QID)...")
            data, ok = query_dbpedia(qid_by_name)
            for name in batch:
                entry = cache.setdefault(name, {})
                if name not in qid_by_name:
                    entry["db"] = None       # sem ancora Wikidata -> sem DBpedia
                    entry["db_ok"] = True
                elif ok:
                    entry["db"] = data.get(name)
                    entry["db_ok"] = True
                else:
                    entry.setdefault("db", None)
                    entry["db_ok"] = False
            save_cache(cache)
            time.sleep(args.sleep)

    # O output reflete TUDO o que ja foi obtido (toda a cache), por isso re-execucoes
    # acumulam resultados de varias sessoes em vez de se sobreporem.
    results = {name: data for name, data in cache.items() if name in artists}

    graph, enriched = build_graph(results, artists)
    matched_wd = sum(1 for v in results.values() if v.get("wd"))
    matched_db = sum(1 for v in results.values() if v.get("db"))
    graph.serialize(destination=args.output, format="turtle")
    print(
        f"\nEnriquecidos {enriched} artistas no total "
        f"(Wikidata: {matched_wd}, DBpedia: {matched_db}). "
        f"{len(graph)} triplas -> {args.output}"
    )

    if args.apply:
        apply_to_graphdb(args.output, args.endpoint)
    else:
        print("Nota: a app le da GraphDB, nao do ficheiro. Corre com --apply "
              "(ou 'python load_ttl_to_graphdb.py') para refletir isto na UI.")


if __name__ == "__main__":
    main()
