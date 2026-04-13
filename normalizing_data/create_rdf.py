import pandas as pd
import re
import hashlib
from rdflib import Graph, Namespace, URIRef, Literal
from rapidfuzz import fuzz
from rdflib.namespace import RDF

# files e output
# ta hardcoded por agora, mas é só meter os ficheiros na mesma pasta e correr o script, e ele cria o music.ttl com as triples todas 
BILLBOARD_FILE = "digital.csv"
SPOTIFY_FILE = "spotify-tracks-dataset-detailed.csv"
OUTPUT_FILE = "music.ttl"

billboard = pd.read_csv(BILLBOARD_FILE)
spotify = pd.read_csv(SPOTIFY_FILE)

g = Graph()

# namespaces para os uris e predicados, nao esquecer de meter igual no graphdb 
# acho q isto devia ir para um ficheiro das configs ou assim, mas tá aqui hardcoded por agora
BASE = Namespace("http://music.org/")
PRED = Namespace("http://music.org/pred/")
TYPE = Namespace("http://music.org/type/")

g.bind("pred", PRED)
g.bind("type", TYPE)

# ids dos uris é uma hash pra serem todos diferentes, lá em baixo chamo isto tipo 
# make_id(song_name + artist_name) por exemplo, e assim para as musicas com o mesmo nome os uris vão ser diferentes
def make_id(text):
    return hashlib.md5(str(text).encode()).hexdigest()

# normalizar pra fazer a match entre os dois datasets
def normalize_text(text):
    text = str(text).lower().strip()
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'-.*', '', text)
    text = re.sub(r'[^a-z0-9 ]', '', text)
    return text.strip()

#os artistas do digital.csv estão tipo com 50 combinações de featuring, feat., and, &, só vigula diferentes, e no outro tao todos divididos por ";", 
# entao aqui eu tento separar os artistas e guardar o nome raw pra depois meter no artist name
def split_artists(raw_artist_str):
    raw_artist_str = str(raw_artist_str)

    # tirar as aspas 
    raw_artist_str = raw_artist_str.replace('"', '').replace("'", "")

    cleaned = re.sub(r'\b(featuring|feat\.?|ft\.?|and|&)(?=\s|,|$)', ',', raw_artist_str, flags=re.I)

    parts = [p.strip() for p in cleaned.split(',') if p.strip()]

    if len(parts) == 0:
        return None, []

    main_raw = parts[0]
    features_raw = parts[1:]
    features_raw = list(dict.fromkeys(features_raw))

    return main_raw, features_raw

#isto e só pra nao demorar 20 mil horas pra cada linha do billboard procurar no spotify, meti um indice por letra pra reduzir o numero de comparacoes
#mas provavelmente ta parvo nsei kakakak
spotify_index_by_letter = {}

# dataset das musicas do spotify que tem os atributos da musica, tipo danceability, energy
# guardar o nome normalizado e os artistas normalizados de cada musica, e a row original pra depois meter os atributos da musica nas triples muito mais rapido
for _, row in spotify.iterrows():
    name_raw = str(row["track_name"])
    name_norm = normalize_text(name_raw)

    artists_norm = set([normalize_text(a) for a in str(row["artists"]).split(";")])

    item = {
        "name_norm": name_norm,
        "artists_norm": artists_norm,
        "row": row
    }

    first = name_norm[:1]
    spotify_index_by_letter.setdefault(first, []).append(item)

# aqui eu tento achar a melhor match entre o nome da musica e os artistas
# eu tentei meter fuzzy matching pro nome e overlap dos artistas
# porque às vezes há aspas ou espaços a mais ou a menos, acho q tá a funfar bem
def find_match(bill_song_norm, bill_artists_norm):
    first = bill_song_norm[:1]
    candidates = spotify_index_by_letter.get(first, [])

    best_match = None
    best_score = 0

    for s in candidates:
        score = fuzz.ratio(bill_song_norm, s["name_norm"])
        overlap = len(set(bill_artists_norm) & s["artists_norm"])

        total_score = score + (overlap * 10)

        if total_score > best_score and score > 85:
            best_score = total_score
            best_match = s

    return best_match

# processar cada linha do billboard, criar os uris e as triples, e tentar achar a match no spotify pra meter os atributos da danceability, energy, bla bla bla 
for i, row in billboard.iterrows():

    raw_song = str(row["Song"])
    song_norm = normalize_text(raw_song)

    # split artists (RAW + NORMALIZED)
    main_raw, features_raw = split_artists(row["Artist"])

    main_norm = normalize_text(main_raw) if main_raw else None
    features_norm = [normalize_text(f) for f in features_raw]

    all_artists_norm = [a for a in [main_norm] + features_norm if a]

    #hash dos uris (USAR NORMALIZADO PRA ISSO, MAS GUARDAR O NOME RAW NAS TRIPLES)
    song_uri = URIRef(
        BASE["song/" + make_id(song_norm + "|" + str(main_norm))]
    )

    #isto é pq há bues musicas q tao trending na cena do hot 100 buéeeees anos (tipo all i want for christmas is you)
    # entao eu meti q a entry é a "entrada" da música no chart 
    entry_uri = URIRef(
        BASE["entry/" + make_id(song_norm + "|" + str(main_norm) + "|" + str(row["Date"]))]
    )

    # nome da musica é o nome da musica
    g.add((song_uri, PRED.name, Literal(raw_song)))
    g.add((song_uri, RDF.type, TYPE.Song))

    # artistas são artistas, e eu guardo o nome raw pra meter no name do artista, e o normalized só pra criar o id do uri
    if main_raw:
        main_uri = URIRef(BASE["artist/" + make_id(main_norm)])
        # o nome do artista é o nome do artista
        g.add((main_uri, PRED.name, Literal(main_raw)))
        g.add((main_uri, RDF.type, TYPE.Artist))
        # artista principal da música 
        g.add((song_uri, PRED.mainArtist, main_uri))

    for f_raw in features_raw:
        f_norm = normalize_text(f_raw)
        feat_uri = URIRef(BASE["artist/" + make_id(f_norm)])
        # a mesma cena, os features são artistas, e o nome do artista é o nome do artista      
        g.add((feat_uri, PRED.name, Literal(f_raw)))
        g.add((feat_uri, RDF.type, TYPE.Artist))
        # artistas featuring da musica
        g.add((song_uri, PRED.featuredArtist, feat_uri))

    # a entry é a entrada da música no chart, e tem como atributos o rank, as semanas, e a data
    # é a cena q expliquei lá em cima do all i want for christmas is you, que tem tipo 170 entradas diferentes
    g.add((entry_uri, PRED.song, song_uri))
    g.add((entry_uri, RDF.type, TYPE.ChartEntry))

    g.add((entry_uri, PRED.rank, Literal(int(row["Rank"]))))
    g.add((entry_uri, PRED.weeks, Literal(int(row["Weeks in Charts"]))))
    g.add((entry_uri, PRED.date, Literal(str(row["Date"]))))

    # fazer a match pra meter os atributos da música do outro dataset
    match = find_match(song_norm, all_artists_norm)

    if match:
        srow = match["row"]

        g.add((song_uri, PRED.popularity, Literal(float(srow["popularity"]))))
        g.add((song_uri, PRED.energy, Literal(float(srow["energy"]))))
        g.add((song_uri, PRED.danceability, Literal(float(srow["danceability"]))))
        g.add((song_uri, PRED.tempo, Literal(float(srow["tempo"]))))
        g.add((song_uri, PRED.valence, Literal(float(srow["valence"]))))
        g.add((song_uri, PRED.loudness, Literal(float(srow["loudness"]))))     
        g.add((song_uri, PRED.speechiness, Literal(float(srow["speechiness"]))))
        g.add((song_uri, PRED.acousticness, Literal(float(srow["acousticness"]))))
        g.add((song_uri, PRED.instrumentalness, Literal(float(srow["instrumentalness"]))))
        g.add((song_uri, PRED.liveness, Literal(float(srow["liveness"]))))

        g.add((song_uri, PRED.duration_ms, Literal(int(srow["duration_ms"]))))
        g.add((song_uri, PRED.explicit, Literal(bool(srow["explicit"]))))

        g.add((song_uri, PRED.albumName, Literal(str(srow["album_name"]))))
        g.add((song_uri, PRED.genre, Literal(str(srow["track_genre"]))))

    # guys isto é só pra ver isto a funcionar mas se quiserem tirar metam comentario, 
    # é só pra ver o progresso porque isto demora um bocado a correr, e assim dá pra ver que tá a funcionar e mais ou menos quanto tempo falta
    # isto acaba de correr tipo nas 53000 rows 
    if i % 500 == 0:
        print(f"Processed {i} rows...")

# ficheiro gostosinho
g.serialize(OUTPUT_FILE, format="turtle")

print(f"RDF saved to {OUTPUT_FILE}")