import pandas as pd
import re
import hashlib
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from rdflib import Graph, Namespace, URIRef, Literal
from rapidfuzz import fuzz
from rdflib.namespace import RDF, RDFS, OWL, XSD
import os

# files e output
# ta hardcoded por agora, mas é só meter os ficheiros na mesma pasta e correr o script, e ele cria o music.ttl com as triples todas 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BILLBOARD_FILE = os.path.join(BASE_DIR, "digital.csv")
SPOTIFY_FILE = os.path.join(BASE_DIR, "spotify-tracks-dataset-detailed.csv")
OUTPUT_FILE = os.path.join(BASE_DIR, "music.ttl")
billboard = pd.read_csv(BILLBOARD_FILE)
spotify = pd.read_csv(SPOTIFY_FILE)

g = Graph()

# namespaces para os uris e predicados, nao esquecer de meter igual no graphdb 
# acho q isto devia ir para um ficheiro das configs ou assim, mas tá aqui hardcoded por agora
BASE = Namespace("http://music.org/")
PRED = Namespace("http://music.org/pred/")
TYPE = Namespace("http://music.org/type/")

g.bind("music", BASE)
g.bind("pred", PRED)
g.bind("type", TYPE)
g.bind("rdf", RDF)
g.bind("rdfs", RDFS)
g.bind("owl", OWL)
g.bind("xsd", XSD)


def add_ontology_schema(graph):
    song = TYPE.Song
    charted_song = TYPE.ChartedSong
    hit_song = TYPE.HitSong
    artist = TYPE.Artist
    hit_artist = TYPE.HitArtist
    trending_artist = TYPE.TrendingArtist
    genre = TYPE.Genre
    chart = TYPE.Chart
    chart_entry = TYPE.ChartEntry
    album = TYPE.Album

    graph.add((BASE.MusicOntology, RDF.type, OWL.Ontology))

    for cls in (
        song,
        charted_song,
        hit_song,
        artist,
        hit_artist,
        trending_artist,
        genre,
        chart,
        chart_entry,
        album,
    ):
        graph.add((cls, RDF.type, OWL.Class))

    graph.add((charted_song, RDFS.subClassOf, song))
    graph.add((hit_song, RDFS.subClassOf, charted_song))
    graph.add((hit_artist, RDFS.subClassOf, artist))
    graph.add((trending_artist, RDFS.subClassOf, artist))

    graph.add((chart_entry, RDFS.subClassOf, PROV.Entity))
    graph.add((song, OWL.disjointWith, chart_entry))

    performer = PRED.performer
    main_artist = PRED.mainArtist
    featured_artist = PRED.featuredArtist
    performed = PRED.performed
    entry_song = PRED.entrySong
    in_chart = PRED.inChart
    has_chart_entry = PRED.hasChartEntry
    appears_in_chart = PRED.appearsInChart
    has_genre = PRED.hasGenre
    song_link = PRED.song
    album_link = PRED.album

    object_props = (
        (performer, song, artist),
        (main_artist, song, artist),
        (featured_artist, song, artist),
        (performed, artist, song),
        (entry_song, chart_entry, song),
        (song_link, chart_entry, song),
        (has_chart_entry, song, chart_entry),
        (in_chart, chart_entry, chart),
        (appears_in_chart, artist, chart),
        (has_genre, song, genre),
        (album_link, song, album),
    )
    for prop, dom, rng in object_props:
        graph.add((prop, RDF.type, OWL.ObjectProperty))
        graph.add((prop, RDFS.domain, dom))
        graph.add((prop, RDFS.range, rng))

    graph.add((main_artist, RDFS.subPropertyOf, performer))
    graph.add((featured_artist, RDFS.subPropertyOf, performer))
    graph.add((performer, OWL.inverseOf, performed))
    graph.add((entry_song, OWL.equivalentProperty, song_link))
    graph.add((has_chart_entry, OWL.inverseOf, song_link))

    datatype_props = (
        (PRED.name, song, XSD.string),
        (PRED.name, artist, XSD.string),
        (PRED.rank, chart_entry, XSD.integer),
        (PRED.weeks, chart_entry, XSD.integer),
        (PRED.date, chart_entry, XSD.date),
        (PRED.popularity, song, XSD.decimal),
        (PRED.energy, song, XSD.decimal),
        (PRED.danceability, song, XSD.decimal),
        (PRED.tempo, song, XSD.decimal),
        (PRED.valence, song, XSD.decimal),
        (PRED.loudness, song, XSD.decimal),
        (PRED.speechiness, song, XSD.decimal),
        (PRED.acousticness, song, XSD.decimal),
        (PRED.instrumentalness, song, XSD.decimal),
        (PRED.liveness, song, XSD.decimal),
        (PRED.duration_ms, song, XSD.integer),
        (PRED.explicit, song, XSD.boolean),
        (PRED.albumName, song, XSD.string),
        (RDFS.label, genre, XSD.string),
        (RDFS.label, chart, XSD.string),
    )
    for prop, dom, rng in datatype_props:
        graph.add((prop, RDF.type, OWL.DatatypeProperty))
        graph.add((prop, RDFS.domain, dom))
        graph.add((prop, RDFS.range, rng))


def as_decimal_literal(value):
    try:
        return Literal(Decimal(str(value)), datatype=XSD.decimal)
    except (InvalidOperation, ValueError, TypeError):
        return None


def as_int_literal(value):
    try:
        return Literal(int(float(value)), datatype=XSD.integer)
    except (ValueError, TypeError):
        return None


def as_bool_literal(value):
    if isinstance(value, bool):
        return Literal(value, datatype=XSD.boolean)

    value_str = str(value).strip().lower()
    true_set = {"true", "1", "yes", "y", "t"}
    false_set = {"false", "0", "no", "n", "f"}
    if value_str in true_set:
        return Literal(True, datatype=XSD.boolean)
    if value_str in false_set:
        return Literal(False, datatype=XSD.boolean)
    return None


def as_date_literal(value):
    value_str = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value_str):
        return Literal(value_str, datatype=XSD.date)
    return Literal(value_str)

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


def clean_artist_token(token):
    token = str(token).strip()
    token = re.sub(r'^[\s\.,;:!\-_]+', '', token)
    token = re.sub(r'[\s\.,;:!\-_]+$', '', token)
    token = re.sub(r'\s{2,}', ' ', token)
    return token.strip()


def split_genres(raw_genre):
    if pd.isna(raw_genre):
        return []
    parts = [p.strip() for p in str(raw_genre).split(',')]
    return [p for p in parts if p]


def _split_feature_segments(raw_artist_str):
    raw_artist_str = str(raw_artist_str)
    raw_artist_str = raw_artist_str.replace('"', '').replace("'", "")
    cleaned = re.sub(r'\b(featuring|feat|ft)\.?(?=\s|,|$)', ',', raw_artist_str, flags=re.I)
    return [clean_artist_token(p) for p in cleaned.split(',') if clean_artist_token(p)]


def _split_ambiguous_band_separators(segment):
    segment = str(segment)
    cleaned = re.sub(r'\s*&\s*', ',', segment)
    cleaned = re.sub(r'\s*\+\s*', ',', cleaned)
    cleaned = re.sub(r'\b(and)\b', ',', cleaned, flags=re.I)
    return [clean_artist_token(p) for p in cleaned.split(',') if clean_artist_token(p)]


def _expand_protected_band_variants(protected):
    """
    Add common textual variants for protected band names (and/&/+).
    This helps avoid accidental splits when source rows use a different separator.
    """
    expanded = set(protected)
    joiners = [" & ", " + ", " and "]

    for band in list(protected):
        parts = _split_ambiguous_band_separators(band)
        if len(parts) < 2:
            continue

        for joiner in joiners:
            expanded.add(joiner.join(parts))

    return expanded


def _is_probable_same_group(
    set_a,
    set_b,
    min_shared_songs=2,
    overlap_threshold=0.85,
    one_side_full_threshold=0.98,
):
    if not set_a or not set_b:
        return False

    shared = len(set_a & set_b)
    if shared < min_shared_songs:
        return False

    ratio_a = shared / len(set_a) if set_a else 0
    ratio_b = shared / len(set_b) if set_b else 0

    # Case 1: both behave as a duo/group most of the time.
    if ratio_a >= overlap_threshold and ratio_b >= overlap_threshold:
        return True

    # Case 2: one side appears almost exclusively with the other
    # (e.g., "Selena Gomez" solo exists, but "The Scene" only appears with Selena Gomez).
    if ratio_a >= one_side_full_threshold or ratio_b >= one_side_full_threshold:
        return True

    return False


def detect_protected_band_names(
    billboard_df,
    min_shared_songs=2,
    overlap_threshold=0.85,
    one_side_full_threshold=0.98,
):
    """
    Detect names that should NOT be split by &, +, and.
    Heuristic: if split fragments share almost all songs (by overlap ratio),
    they are likely a single band/group name.
    """
    fragment_songs = defaultdict(set)
    segment_songs = defaultdict(set)

    for _, row in billboard_df.iterrows():
        song_norm = normalize_text(row["Song"])
        segments = _split_feature_segments(row["Artist"])
        for segment in segments:
            segment_songs[normalize_text(segment)].add(song_norm)

        main_raw, features_raw = split_artists(row["Artist"], protected_bands=None)
        for part in [main_raw] + features_raw:
            if part:
                fragment_songs[normalize_text(part)].add(song_norm)

    protected = set()
    unique_artists = billboard_df["Artist"].dropna().astype(str).unique()

    for raw_artist in unique_artists:
        segments = _split_feature_segments(raw_artist)
        for segment in segments:
            if not re.search(r'&|\+|\band\b', segment, flags=re.I):
                continue

            parts = _split_ambiguous_band_separators(segment)
            if len(parts) < 2:
                continue

            song_sets = []
            valid = True
            for p in parts:
                norm = normalize_text(p)
                sset = fragment_songs.get(norm, set())
                if not sset:
                    valid = False
                    break
                song_sets.append(sset)

            if not valid:
                continue

            if len(song_sets) == 2:
                # One-off duo edge case (e.g., "Dan & Phil"): both fragments only
                # appear together once, so keep the full segment unsplit.
                if len(song_sets[0]) == 1 and len(song_sets[1]) == 1 and len(song_sets[0] & song_sets[1]) == 1:
                    protected.add(clean_artist_token(segment))
                    continue

                if _is_probable_same_group(
                    song_sets[0],
                    song_sets[1],
                    min_shared_songs=min_shared_songs,
                    overlap_threshold=overlap_threshold,
                    one_side_full_threshold=one_side_full_threshold,
                ):
                    protected.add(clean_artist_token(segment))
                continue

            all_pairs_match = True
            for i in range(len(song_sets)):
                for j in range(i + 1, len(song_sets)):
                    if not _is_probable_same_group(
                        song_sets[i],
                        song_sets[j],
                        min_shared_songs=min_shared_songs,
                        overlap_threshold=overlap_threshold,
                        one_side_full_threshold=one_side_full_threshold,
                    ):
                        all_pairs_match = False
                        break
                if not all_pairs_match:
                    break

            if all_pairs_match:
                protected.add(clean_artist_token(segment))

    protected = _expand_protected_band_variants(protected)

    suppressed_fragments = set()
    for band_name in protected:
        band_norm = normalize_text(band_name)
        band_song_set = segment_songs.get(band_norm, set())
        if not band_song_set:
            continue

        parts = _split_ambiguous_band_separators(band_name)
        for part in parts:
            part_norm = normalize_text(part)
            part_song_set = fragment_songs.get(part_norm, set())
            if not part_song_set:
                continue

            # Suppress only tiny fragment artifacts whose songs are fully explained
            # by a protected band name (safe against real solo artists).
            if len(part_song_set) <= 3 and part_song_set.issubset(band_song_set) and len(part_song_set) < len(band_song_set):
                suppressed_fragments.add(part_norm)

    return protected, suppressed_fragments

#os artistas do digital.csv estão tipo com 50 combinações de featuring, feat., and, &, só vigula diferentes, e no outro tao todos divididos por ";", 
# entao aqui eu tento separar os artistas e guardar o nome raw pra depois meter no artist name
def split_artists(raw_artist_str, protected_bands=None, suppressed_fragments=None):
    raw_artist_str = str(raw_artist_str)
    original_raw_artist = raw_artist_str

    # tirar as aspas 
    raw_artist_str = raw_artist_str.replace('"', '').replace("'", "")

    placeholder_map = {}
    if protected_bands:
        protected_sorted = sorted(protected_bands, key=len, reverse=True)
        for i, band_name in enumerate(protected_sorted):
            token = f"BANDTOKEN{i}ZZ"
            pattern = re.compile(re.escape(band_name), flags=re.I)

            def _replace(match):
                placeholder_map[token] = clean_artist_token(match.group(0))
                return token

            raw_artist_str = pattern.sub(_replace, raw_artist_str)

    cleaned = re.sub(r'\b(featuring|feat|ft)\.?(?=\s|,|$)', ',', raw_artist_str, flags=re.I)
    cleaned = re.sub(r'\bwith\b', ',', cleaned, flags=re.I)
    cleaned = re.sub(r'\band\b', ',', cleaned, flags=re.I)
    cleaned = re.sub(r'\s+[xX]\s+', ',', cleaned)
    cleaned = re.sub(r'\s*&\s*', ',', cleaned)
    cleaned = re.sub(r'\s*\+\s*', ',', cleaned)
    cleaned = re.sub(r'\s*;\s*', ',', cleaned)

    initial_parts = []
    for part in cleaned.split(','):
        p = clean_artist_token(part)
        if not p:
            continue
        if p in placeholder_map:
            p = placeholder_map[p]
        initial_parts.append(p)

    # Alguns casos vêm colados por slash (ex.: "Jay-Z/Linkin Park").
    # Só dividimos quando ambos os lados parecem nomes completos para evitar casos como AC/DC.
    parts = []
    for token in initial_parts:
        if '/' in token and token.count('/') == 1:
            left, right = [t.strip() for t in token.split('/')]
            if len(left) >= 4 and len(right) >= 4:
                left_clean = clean_artist_token(left)
                right_clean = clean_artist_token(right)
                if left_clean in placeholder_map:
                    left_clean = placeholder_map[left_clean]
                if right_clean in placeholder_map:
                    right_clean = placeholder_map[right_clean]
                parts.extend([left_clean, right_clean])
                continue
        token_clean = clean_artist_token(token)
        if token_clean in placeholder_map:
            token_clean = placeholder_map[token_clean]
        parts.append(token_clean)

    if len(parts) == 0:
        return None, []

    if protected_bands and suppressed_fragments:
        has_protected_band = False
        for band_name in protected_bands:
            if re.search(re.escape(band_name), original_raw_artist, flags=re.I):
                has_protected_band = True
                break

        if has_protected_band:
            parts = [p for p in parts if normalize_text(p) not in suppressed_fragments]

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

    best_with_artist = None
    best_with_artist_score = 0

    best_fallback = None
    best_fallback_score = 0

    bill_artists_set = set(bill_artists_norm)

    for s in candidates:
        score = fuzz.ratio(bill_song_norm, s["name_norm"])
        if score < 85:
            continue

        overlap = len(bill_artists_set & s["artists_norm"])

        total_score = score + (overlap * 10)

        if overlap > 0:
            if total_score > best_with_artist_score:
                best_with_artist_score = total_score
                best_with_artist = s
            continue

        # Fallback only when title similarity is almost exact and we have no
        # artist-overlap option. This avoids collisions like same title,
        # different artists.
        if score >= 97 and score > best_fallback_score:
            best_fallback_score = score
            best_fallback = s

    if best_with_artist is not None:
        return best_with_artist

    # If we know the Billboard artist(s), avoid cross-artist matches entirely.
    # Better to skip enrichment than attach attributes from a different track.
    if bill_artists_set:
        return None

    return best_fallback


PROV = Namespace("http://www.w3.org/ns/prov#")
g.bind("prov", PROV)

add_ontology_schema(g)

BILLBOARD_HOT_100 = URIRef(BASE["chart/billboard_hot_100"])
g.add((BILLBOARD_HOT_100, RDF.type, TYPE.Chart))
g.add((BILLBOARD_HOT_100, RDFS.label, Literal("Billboard Hot 100", datatype=XSD.string)))
TRENDING_SINCE = "2024-01-01"


PROTECTED_BANDS, SUPPRESSED_FRAGMENTS = detect_protected_band_names(
    billboard,
    min_shared_songs=2,
    overlap_threshold=0.85,
    one_side_full_threshold=0.98,
)
if PROTECTED_BANDS:
    print(f"Detected {len(PROTECTED_BANDS)} protected band names.")
    preview = sorted(PROTECTED_BANDS)[:20]
    print("Preview:", "; ".join(preview))
else:
    print("No protected band names detected.")

if SUPPRESSED_FRAGMENTS:
    print(f"Suppressed {len(SUPPRESSED_FRAGMENTS)} fragment artifacts.")

# processar cada linha do billboard, criar os uris e as triples, e tentar achar a match no spotify pra meter os atributos da danceability, energy, bla bla bla 
for i, row in billboard.iterrows():

    raw_song = str(row["Song"])
    song_norm = normalize_text(raw_song)

    # split artists (RAW + NORMALIZED)
    main_raw, features_raw = split_artists(
        row["Artist"],
        protected_bands=PROTECTED_BANDS,
        suppressed_fragments=SUPPRESSED_FRAGMENTS,
    )

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

    song_artist_uris = []

    # artistas são artistas, e eu guardo o nome raw pra meter no name do artista, e o normalized só pra criar o id do uri
    if main_raw:
        main_uri = URIRef(BASE["artist/" + make_id(main_norm)])
        # o nome do artista é o nome do artista
        g.add((main_uri, PRED.name, Literal(main_raw)))
        g.add((main_uri, RDF.type, TYPE.Artist))
        # artista principal da música 
        g.add((song_uri, PRED.mainArtist, main_uri))
        g.add((song_uri, PRED.performer, main_uri))
        g.add((main_uri, PRED.performed, song_uri))
        song_artist_uris.append(main_uri)

    for f_raw in features_raw:
        f_norm = normalize_text(f_raw)
        feat_uri = URIRef(BASE["artist/" + make_id(f_norm)])
        # a mesma cena, os features são artistas, e o nome do artista é o nome do artista      
        g.add((feat_uri, PRED.name, Literal(f_raw)))
        g.add((feat_uri, RDF.type, TYPE.Artist))
        # artistas featuring da musica
        g.add((song_uri, PRED.featuredArtist, feat_uri))
        g.add((song_uri, PRED.performer, feat_uri))
        g.add((feat_uri, PRED.performed, song_uri))
        song_artist_uris.append(feat_uri)

    # a entry é a entrada da música no chart, e tem como atributos o rank, as semanas, e a data
    # é a cena q expliquei lá em cima do all i want for christmas is you, que tem tipo 170 entradas diferentes
    g.add((entry_uri, PRED.song, song_uri))
    g.add((entry_uri, PRED.entrySong, song_uri))
    g.add((song_uri, PRED.hasChartEntry, entry_uri))
    g.add((song_uri, RDF.type, TYPE.ChartedSong))
    g.add((entry_uri, PRED.inChart, BILLBOARD_HOT_100))
    g.add((entry_uri, RDF.type, TYPE.ChartEntry))

    for artist_uri in song_artist_uris:
        g.add((artist_uri, PRED.appearsInChart, BILLBOARD_HOT_100))

    rank_literal = as_int_literal(row["Rank"])
    weeks_literal = as_int_literal(row["Weeks in Charts"])
    if rank_literal is not None:
        g.add((entry_uri, PRED.rank, rank_literal))
    if weeks_literal is not None:
        g.add((entry_uri, PRED.weeks, weeks_literal))
    g.add((entry_uri, PRED.date, as_date_literal(row["Date"])))

    rank_value = None
    try:
        rank_value = int(float(row["Rank"]))
    except (TypeError, ValueError):
        pass

    if rank_value is not None and rank_value <= 10:
        g.add((song_uri, RDF.type, TYPE.HitSong))
        for artist_uri in song_artist_uris:
            g.add((artist_uri, RDF.type, TYPE.HitArtist))

        row_date = str(row["Date"]).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", row_date) and row_date >= TRENDING_SINCE:
            for artist_uri in song_artist_uris:
                g.add((artist_uri, RDF.type, TYPE.TrendingArtist))

    # fazer a match pra meter os atributos da música do outro dataset
    match = find_match(song_norm, all_artists_norm)

    if match:
        srow = match["row"]

        decimal_fields = [
            (PRED.popularity, srow["popularity"]),
            (PRED.energy, srow["energy"]),
            (PRED.danceability, srow["danceability"]),
            (PRED.tempo, srow["tempo"]),
            (PRED.valence, srow["valence"]),
            (PRED.loudness, srow["loudness"]),
            (PRED.speechiness, srow["speechiness"]),
            (PRED.acousticness, srow["acousticness"]),
            (PRED.instrumentalness, srow["instrumentalness"]),
            (PRED.liveness, srow["liveness"]),
        ]
        for predicate, value in decimal_fields:
            decimal_literal = as_decimal_literal(value)
            if decimal_literal is not None:
                g.add((song_uri, predicate, decimal_literal))

        duration_literal = as_int_literal(srow["duration_ms"])
        if duration_literal is not None:
            g.add((song_uri, PRED.duration_ms, duration_literal))

        explicit_literal = as_bool_literal(srow["explicit"])
        if explicit_literal is not None:
            g.add((song_uri, PRED.explicit, explicit_literal))

        album_name = str(srow["album_name"]).strip()
        if album_name:
            album_uri = URIRef(BASE["album/" + make_id(normalize_text(album_name) + "|" + str(main_norm))])
            g.add((album_uri, RDF.type, TYPE.Album))
            g.add((album_uri, PRED.name, Literal(album_name, datatype=XSD.string)))
            g.add((song_uri, PRED.album, album_uri))
            g.add((song_uri, PRED.albumName, Literal(album_name, datatype=XSD.string)))

        genres = split_genres(srow["track_genre"])
        if genres:
            # Keep legacy genre literal while adding normalized Genre resources.
            g.add((song_uri, PRED.genre, Literal(", ".join(genres), datatype=XSD.string)))
            for genre_name in genres:
                genre_norm = normalize_text(genre_name)
                if not genre_norm:
                    continue
                genre_uri = URIRef(BASE["genre/" + make_id(genre_norm)])
                g.add((genre_uri, RDF.type, TYPE.Genre))
                g.add((genre_uri, RDFS.label, Literal(genre_name, datatype=XSD.string)))
                g.add((song_uri, PRED.hasGenre, genre_uri))

    # guys isto é só pra ver isto a funcionar mas se quiserem tirar metam comentario, 
    # é só pra ver o progresso porque isto demora um bocado a correr, e assim dá pra ver que tá a funcionar e mais ou menos quanto tempo falta
    # isto acaba de correr tipo nas 53000 rows 
    if i % 1000 == 0:
        print(f"Processed {i} rows...")

# ficheiro gostosinho
g.serialize(OUTPUT_FILE, format="turtle")

print(f"RDF saved to {OUTPUT_FILE}")