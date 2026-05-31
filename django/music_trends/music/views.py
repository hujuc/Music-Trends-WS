import hashlib
import math
import re
from datetime import datetime

from django.core.cache import cache
from django.shortcuts import render, redirect

from .sparql_client import SparqlClientError, run_select, run_update, sparql_escape_literal

import urllib.request
import urllib.parse
import urllib.error
import json as _json


# ── Helpers ──────────────────────────────────────────────────────────────────

MONTH_NAMES = {
    '01': 'January', '02': 'February', '03': 'March', '04': 'April',
    '05': 'May', '06': 'June', '07': 'July', '08': 'August',
    '09': 'September', '10': 'October', '11': 'November', '12': 'December',
}

OPERATIONS_OPTIONS_CACHE_KEY = 'music:operations:options:v1'
OPERATIONS_OPTIONS_CACHE_TTL = 60


def _val(binding, key, default='—'):
    return binding.get(key, {}).get('value', default)


def _safe_float(s, ndigits=2):
    try:
        return round(float(s), ndigits)
    except (TypeError, ValueError):
        return s


def _safe_int(s, default=0):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return default


def _valid_music_uri(uri):
    return isinstance(uri, str) and uri.startswith('http://music.org/')


def _clean_artist_label(name: str) -> str:
    if not isinstance(name, str):
        return name
    cleaned = re.sub(r'^[\s\.,;:!\-_]+', '', name).strip()
    return cleaned or name


def _split_genres(raw_genre):
    if raw_genre in (None, '', '—'):
        return []
    parts = [p.strip() for p in str(raw_genre).split(',')]
    return [p for p in parts if p]


# ── Dashboard ─────────────────────────────────────────────────────────────────

def home(request):
    ctx = {
        'stats': {'songs': '—', 'artists': '—', 'chart_entries': '—', 'longtail_songs': '—'},
        'top_artists': [],
        'top_songs': [],
        'longtail_top_songs': [],
        'longtail_top_artists': [],
        'longtail_avg_popularity': '—',
        'semantic_genres': [],
        'chart_distribution': [],
    }

    try:
        r = run_select("SELECT (COUNT(?s) AS ?count) WHERE { ?s a type:Song . }")
        ctx['stats']['songs'] = _val(r[0], 'count') if r else '—'

        r = run_select("SELECT (COUNT(?a) AS ?count) WHERE { ?a a type:Artist . }")
        ctx['stats']['artists'] = _val(r[0], 'count') if r else '—'

        r = run_select("SELECT (COUNT(?e) AS ?count) WHERE { ?e a type:ChartEntry . }")
        ctx['stats']['chart_entries'] = _val(r[0], 'count') if r else '—'

        r = run_select("SELECT (COUNT(DISTINCT ?s) AS ?count) WHERE { ?s a type:LongTailSong . }")
        ctx['stats']['longtail_songs'] = _val(r[0], 'count') if r else '—'

        r = run_select("""
            SELECT ?artist ?artistName (COUNT(?entry) AS ?entries)
            WHERE {
              ?entry a type:ChartEntry ;
                     pred:song ?song .
              ?song pred:mainArtist ?artist .
              ?artist pred:name ?artistName .
            }
            GROUP BY ?artist ?artistName
            ORDER BY DESC(?entries)
            LIMIT 10
        """)
        ctx['top_artists'] = [
            {
                'uri': _val(row, 'artist'),
                'name': _clean_artist_label(_val(row, 'artistName')),
                'entries': _val(row, 'entries'),
            }
            for row in r
        ]

        r = run_select("""
                SELECT ?song ?songName ?bestRank (COUNT(?bestEntry) AS ?weeksAtBestRank)
                WHERE {
                    {
                        SELECT ?song ?songName (MIN(?rank) AS ?bestRank)
                        WHERE {
                            ?entry a type:ChartEntry ;
                                            pred:song ?song ;
                                            pred:rank ?rank .
                            ?song pred:name ?songName .
                        }
                        GROUP BY ?song ?songName
                    }
                    ?bestEntry a type:ChartEntry ;
                                            pred:song ?song ;
                                            pred:rank ?bestRank .
                }
                GROUP BY ?song ?songName ?bestRank
                ORDER BY DESC(?weeksAtBestRank) ASC(?bestRank)
                LIMIT 10
        """)
        ctx['top_songs'] = [
            {
                'uri': _val(row, 'song'),
                'name': _val(row, 'songName'),
                'best_rank': _safe_int(_val(row, 'bestRank')),
                'weeks_at_best_rank': _safe_int(_val(row, 'weeksAtBestRank')),
            }
            for row in r
        ]

        r = run_select("""
            SELECT ?song ?songName ?artist ?artistName (MAX(?weeks) AS ?maxWeeks)
            WHERE {
              ?song a type:LongTailSong ;
                    pred:name ?songName .
              ?entry a type:ChartEntry ;
                     pred:song ?song ;
                     pred:weeks ?weeks .
              OPTIONAL {
                ?song pred:mainArtist ?artist .
                ?artist pred:name ?artistName .
              }
            }
            GROUP BY ?song ?songName ?artist ?artistName
            ORDER BY DESC(?maxWeeks) ASC(?songName)
            LIMIT 10
        """)
        ctx['longtail_top_songs'] = [
            {
                'uri': _val(row, 'song'),
                'name': _val(row, 'songName'),
                'artist_uri': _val(row, 'artist', ''),
                'artist_name': _clean_artist_label(_val(row, 'artistName')),
                'max_weeks': _safe_int(_val(row, 'maxWeeks')),
            }
            for row in r
        ]

        r = run_select("""
            SELECT ?artist ?artistName (COUNT(DISTINCT ?song) AS ?longTailSongs)
            WHERE {
              ?song a type:LongTailSong ;
                    pred:mainArtist ?artist .
              ?artist pred:name ?artistName .
            }
            GROUP BY ?artist ?artistName
            ORDER BY DESC(?longTailSongs) ASC(?artistName)
            LIMIT 10
        """)
        ctx['longtail_top_artists'] = [
            {
                'uri': _val(row, 'artist'),
                'name': _clean_artist_label(_val(row, 'artistName')),
                'count': _safe_int(_val(row, 'longTailSongs')),
            }
            for row in r
        ]

        r = run_select("""
            SELECT (AVG(?popularity) AS ?avgPopularity)
            WHERE {
              ?song a type:LongTailSong ;
                    pred:popularity ?popularity .
            }
        """)
        ctx['longtail_avg_popularity'] = _safe_float(_val(r[0], 'avgPopularity')) if r else '—'

        r = run_select("""
            SELECT ?genre ?genreLabel (COUNT(DISTINCT ?song) AS ?numSongs)
            WHERE {
              ?song a type:Song ;
                    pred:hasGenre ?genre .
              ?genre rdfs:label ?genreLabel .
            }
            GROUP BY ?genre ?genreLabel
            ORDER BY DESC(?numSongs)
            LIMIT 10
        """)
        ctx['semantic_genres'] = [
            {
                'uri': _val(row, 'genre'),
                'label': _val(row, 'genreLabel'),
                'count': _val(row, 'numSongs'),
            }
            for row in r
        ]

        r = run_select("""
            SELECT ?chart ?chartLabel (COUNT(?entry) AS ?numEntries)
            WHERE {
              ?entry a type:ChartEntry ;
                     pred:inChart ?chart .
              ?chart rdfs:label ?chartLabel .
            }
            GROUP BY ?chart ?chartLabel
            ORDER BY DESC(?numEntries)
        """)
        ctx['chart_distribution'] = [
            {
                'uri': _val(row, 'chart'),
                'label': _val(row, 'chartLabel'),
                'count': _val(row, 'numEntries'),
            }
            for row in r
        ]

    except SparqlClientError as exc:
        ctx['error_message'] = str(exc)

    return render(request, 'dashboard.html', ctx)


# ── Songs Explorer ────────────────────────────────────────────────────────────

def songs(request):
    song_query = request.GET.get('song', '').strip()
    artist_query = request.GET.get('artist', '').strip()
    genre_query = request.GET.get('genre', '').strip()
    with_audio_features = request.GET.get('with_audio_features', '').strip() == 'on'
    popularity_min = request.GET.get('popularity_min', '').strip()
    popularity_max = request.GET.get('popularity_max', '').strip()
    top_metric = request.GET.get('top_metric', '').strip()
    page_raw = request.GET.get('page', '1').strip()
    page_size = 15
    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    offset = (page - 1) * page_size

    filters = []

    if song_query:
        filters.append(
            f"FILTER(CONTAINS(LCASE(STR(?songname)), LCASE(STR({sparql_escape_literal(song_query)}))))"
        )

    if artist_query:
        filters.append(
            f"FILTER(CONTAINS(LCASE(STR(?artistname)), LCASE(STR({sparql_escape_literal(artist_query)}))))"
        )

    if genre_query:
        filters.append(
            f"FILTER(BOUND(?genre) && CONTAINS(LCASE(STR(?genre)), LCASE(STR({sparql_escape_literal(genre_query)}))))"
        )

    if with_audio_features:
        filters.append(
            "FILTER(BOUND(?energy) || BOUND(?danceability) || BOUND(?valence) || "
            "BOUND(?acousticness) || BOUND(?speechiness) || BOUND(?instrumentalness) || BOUND(?liveness))"
        )

    if popularity_min:
        try:
            pop_min_value = float(popularity_min)
            filters.append(f"FILTER(BOUND(?popularity) && ?popularity >= {pop_min_value})")
        except ValueError:
            popularity_min = ''

    if popularity_max:
        try:
            pop_max_value = float(popularity_max)
            filters.append(f"FILTER(BOUND(?popularity) && ?popularity <= {pop_max_value})")
        except ValueError:
            popularity_max = ''

    top_metric = top_metric if top_metric in (
        'energy', 'danceability', 'valence',
        'acousticness', 'speechiness', 'instrumentalness', 'liveness'
    ) else ''
    order_clause = f'ORDER BY DESC(?{top_metric})' if top_metric else ''
    filters_block = "\n        ".join(filters)

    count_query = f"""
    SELECT (COUNT(DISTINCT ?song) AS ?count)
    WHERE {{
        ?song a type:Song ;
              pred:name ?songname ;
              pred:mainArtist ?mainArtist .
        ?mainArtist pred:name ?artistname .
        OPTIONAL {{ ?song pred:genre ?genre . }}
        OPTIONAL {{ ?song pred:popularity ?popularity . }}
        OPTIONAL {{ ?song pred:energy ?energy . }}
        OPTIONAL {{ ?song pred:danceability ?danceability . }}
        OPTIONAL {{ ?song pred:valence ?valence . }}
        OPTIONAL {{ ?song pred:acousticness ?acousticness . }}
        OPTIONAL {{ ?song pred:speechiness ?speechiness . }}
        OPTIONAL {{ ?song pred:instrumentalness ?instrumentalness . }}
        OPTIONAL {{ ?song pred:liveness ?liveness . }}
        {filters_block}
    }}
    """

    query = f"""
    SELECT ?song ?songname ?mainArtist ?artistname ?genre ?popularity ?energy ?danceability ?valence
           ?acousticness ?speechiness ?instrumentalness ?liveness
    WHERE {{
        ?song a type:Song ;
        pred:name ?songname ;
        pred:mainArtist ?mainArtist .
        ?mainArtist pred:name ?artistname .
        OPTIONAL {{ ?song pred:genre ?genre . }}
        OPTIONAL {{ ?song pred:popularity ?popularity . }}
        OPTIONAL {{ ?song pred:energy ?energy . }}
        OPTIONAL {{ ?song pred:danceability ?danceability . }}
        OPTIONAL {{ ?song pred:valence ?valence . }}
        OPTIONAL {{ ?song pred:acousticness ?acousticness . }}
        OPTIONAL {{ ?song pred:speechiness ?speechiness . }}
        OPTIONAL {{ ?song pred:instrumentalness ?instrumentalness . }}
        OPTIONAL {{ ?song pred:liveness ?liveness . }}
        {filters_block}
    }}
    {order_clause}
    LIMIT {page_size}
    OFFSET {offset}
    """

    try:
        count_bindings = run_select(count_query)
        total_count = _safe_int(_val(count_bindings[0], 'count', '0')) if count_bindings else 0
        bindings = run_select(query)
    except SparqlClientError as exc:
        return render(request, 'songs.html', {
            'songs': [], 'error_message': str(exc),
            'song_query': song_query,
            'artist_query': artist_query, 'genre_query': genre_query,
            'with_audio_features': with_audio_features,
            'popularity_min': popularity_min, 'popularity_max': popularity_max,
            'top_metric': top_metric,
            'page': 1,
            'has_previous': False,
            'has_next': False,
            'total_count': 0,
        })

    # Deduplicate by URI and merge repeated rows caused by multi-value genres.
    results_by_uri = {}
    ordered_uris = []
    for r in bindings:
        uri = _val(r, 'song')
        if not uri:
            continue

        if uri not in results_by_uri:
            ordered_uris.append(uri)
            results_by_uri[uri] = {
                'uri': uri,
                'name': _val(r, 'songname'),
                'artist_uri': _val(r, 'mainArtist'),
                'artist': _clean_artist_label(_val(r, 'artistname')),
                'genres': [],
                'popularity': _safe_float(_val(r, 'popularity', '-')),
                'energy': _safe_float(_val(r, 'energy', '-')),
                'danceability': _safe_float(_val(r, 'danceability', '-')),
                'valence': _safe_float(_val(r, 'valence', '-')),
                'acousticness': _safe_float(_val(r, 'acousticness', '-')),
                'speechiness': _safe_float(_val(r, 'speechiness', '-')),
                'instrumentalness': _safe_float(_val(r, 'instrumentalness', '-')),
                'liveness': _safe_float(_val(r, 'liveness', '-')),
            }

        genre_value = _val(r, 'genre', None)
        for genre in _split_genres(genre_value):
            if genre not in results_by_uri[uri]['genres']:
                results_by_uri[uri]['genres'].append(genre)

    results = []
    for uri in ordered_uris:
        song = results_by_uri[uri]
        genres = song['genres']
        song['genres_preview'] = genres[:3]
        song['genres_remaining'] = max(0, len(genres) - 3)
        results.append(song)

    max_page = max(1, (total_count + page_size - 1) // page_size)
    page = min(page, max_page)
    has_previous = page > 1
    has_next = page < max_page

    return render(request, 'songs.html', {
        'songs': results,
        'song_query': song_query,
        'artist_query': artist_query, 'genre_query': genre_query,
        'with_audio_features': with_audio_features,
        'popularity_min': popularity_min, 'popularity_max': popularity_max,
        'top_metric': top_metric,
        'page': page,
        'has_previous': has_previous,
        'has_next': has_next,
        'previous_page': page - 1,
        'next_page': page + 1,
        'total_count': total_count,
    })


# ── Song Detail ───────────────────────────────────────────────────────────────

def song_detail(request):
    uri = request.GET.get('uri', '').strip()
    if not _valid_music_uri(uri):
        return redirect('songs')

    ctx = {}
    try:
        bindings = run_select(f"""
            SELECT ?songName ?mainArtist ?mainArtistName
                   ?featuredArtist ?featuredArtistName
                   ?genre ?genreResource ?genreLabel
                   ?popularity ?energy ?danceability ?tempo ?valence
                   ?loudness ?speechiness ?acousticness ?instrumentalness
                   ?liveness ?duration ?explicit ?albumName
            WHERE {{
              BIND(<{uri}> AS ?song)
              ?song pred:name ?songName ;
                    pred:mainArtist ?mainArtist .
              ?mainArtist pred:name ?mainArtistName .
              OPTIONAL {{ ?song pred:featuredArtist ?featuredArtist .
                          ?featuredArtist pred:name ?featuredArtistName . }}
              OPTIONAL {{
                    ?song pred:hasGenre ?genreResource .
                    ?genreResource <http://www.w3.org/2000/01/rdf-schema#label> ?genreLabel .
              }}
              OPTIONAL {{ ?song pred:genre ?genre . }}
              OPTIONAL {{ ?song pred:popularity ?popularity . }}
              OPTIONAL {{ ?song pred:energy ?energy . }}
              OPTIONAL {{ ?song pred:danceability ?danceability . }}
              OPTIONAL {{ ?song pred:tempo ?tempo . }}
              OPTIONAL {{ ?song pred:valence ?valence . }}
              OPTIONAL {{ ?song pred:loudness ?loudness . }}
              OPTIONAL {{ ?song pred:speechiness ?speechiness . }}
              OPTIONAL {{ ?song pred:acousticness ?acousticness . }}
              OPTIONAL {{ ?song pred:instrumentalness ?instrumentalness . }}
              OPTIONAL {{ ?song pred:liveness ?liveness . }}
              OPTIONAL {{ ?song pred:duration_ms ?duration . }}
              OPTIONAL {{ ?song pred:explicit ?explicit . }}
              OPTIONAL {{ ?song pred:albumName ?albumName . }}
            }}
        """)

        if not bindings:
            return render(request, 'song_detail.html', {'error_message': 'Song not found.'})

        row0 = bindings[0]

        # Prefer semantic genres (hasGenre + rdfs:label), fallback to legacy pred:genre literals.
        genres = []
        seen_semantic = set()
        for r in bindings:
            label = _val(r, 'genreLabel', None)
            if not label or label == '—':
                continue
            key = label.strip().lower()
            if key in seen_semantic:
                continue
            seen_semantic.add(key)
            genres.append(label.strip())

        if not genres:
            seen_legacy = set()
            for r in bindings:
                for genre in _split_genres(_val(r, 'genre', None)):
                    key = genre.strip().lower()
                    if key in seen_legacy:
                        continue
                    seen_legacy.add(key)
                    genres.append(genre)

        seen_feat = set()
        featured_artists = []
        for r in bindings:
            fa_uri = r.get('featuredArtist', {}).get('value')
            if fa_uri and fa_uri not in seen_feat:
                seen_feat.add(fa_uri)
                featured_artists.append({'uri': fa_uri, 'name': _clean_artist_label(_val(r, 'featuredArtistName'))})

        # Audio feature bars (all values 0–1 scale)
        def feat(label, key):
            raw = _val(row0, key, None)
            if raw is None or raw == '—':
                return None
            try:
                v = float(raw)
                return {
                    'label': label,
                    'value_display': f'{v:.3f}',
                    'pct': min(100, max(0, round(v * 100))),
                }
            except ValueError:
                return None

        audio_features = [f for f in [
            feat('Energy', 'energy'),
            feat('Danceability', 'danceability'),
            feat('Valence', 'valence'),
            feat('Acousticness', 'acousticness'),
            feat('Speechiness', 'speechiness'),
            feat('Instrumentalness', 'instrumentalness'),
            feat('Liveness', 'liveness'),
        ] if f]

        # Duration ms → m:ss
        duration_min = None
        raw_dur = _val(row0, 'duration', None)
        if raw_dur and raw_dur != '—':
            try:
                ms = int(float(raw_dur))
                m, s = divmod(ms // 1000, 60)
                duration_min = f'{m}:{s:02d}'
            except ValueError:
                pass

        ctx['song'] = {
            'uri': uri,
            'name': _val(row0, 'songName'),
            'main_artist_uri': _val(row0, 'mainArtist'),
            'main_artist_name': _clean_artist_label(_val(row0, 'mainArtistName')),
            'featured_artists': featured_artists,
            'genres': genres,
            'popularity': _safe_float(_val(row0, 'popularity', None)),
            'tempo': _safe_float(_val(row0, 'tempo', None), 1),
            'duration_min': duration_min,
            'duration_ms': raw_dur if raw_dur and raw_dur != '—' else '',
            'explicit': _val(row0, 'explicit', None),
            'album_name': _val(row0, 'albumName', None),
            'audio_features': audio_features,
        }

        chart_bindings = run_select(f"""
            SELECT ?rank ?weeks ?date
            WHERE {{
              BIND(<{uri}> AS ?song)
              ?entry a type:ChartEntry ;
                     pred:song ?song ;
                     pred:rank ?rank ;
                     pred:weeks ?weeks ;
                     pred:date ?date .
            }}
            ORDER BY ?date
            LIMIT 50
        """)
        ctx['chart_entries'] = [
            {'rank': _val(r, 'rank'), 'weeks': _val(r, 'weeks'), 'date': _val(r, 'date')}
            for r in chart_bindings
        ]

        # ── Similar songs (Manhattan distance over normalised audio features) ──
        _FEAT_KEYS = ['energy', 'danceability', 'valence', 'acousticness',
                      'speechiness', 'instrumentalness', 'liveness']
        feat_vals = {}
        for fk in _FEAT_KEYS:
            raw = _val(row0, fk, None)
            if raw is not None and raw != '—':
                try:
                    feat_vals[fk] = float(raw)
                except ValueError:
                    pass

        if len(feat_vals) >= 3:
            try:
                preds = ' ;\n                '.join(
                    f'pred:{k} ?{k}' for k in feat_vals
                )
                terms = ' + '.join(
                    f'ABS(?{k} - {v})' for k, v in feat_vals.items()
                )
                similar_rows = run_select(f"""
                    SELECT ?song ?name ?artistUri ?artistName
                           ?energy ?danceability ?valence ?distance
                    WHERE {{
                      ?song a type:Song ;
                            pred:name ?name ;
                            pred:mainArtist ?artistUri ;
                            {preds} .
                      ?artistUri pred:name ?artistName .
                      FILTER(?song != <{uri}>)
                      BIND(({terms}) AS ?distance)
                    }}
                    ORDER BY ASC(?distance)
                    LIMIT 6
                """)
                max_dist = len(feat_vals)
                similar_songs = []
                for r in similar_rows:
                    raw_dist = _val(r, 'distance', None)
                    dist = None
                    sim_pct = None
                    if raw_dist is not None and raw_dist != '—':
                        try:
                            dist = float(raw_dist)
                            sim_pct = max(0, round((1 - dist / max_dist) * 100))
                        except ValueError:
                            pass
                    similar_songs.append({
                        'uri': _val(r, 'song'),
                        'name': _val(r, 'name'),
                        'artist_uri': _val(r, 'artistUri'),
                        'artist_name': _val(r, 'artistName'),
                        'energy_pct': round(float(_val(r, 'energy', 0) or 0) * 100),
                        'dance_pct': round(float(_val(r, 'danceability', 0) or 0) * 100),
                        'valence_pct': round(float(_val(r, 'valence', 0) or 0) * 100),
                        'sim_pct': sim_pct,
                    })
                ctx['similar_songs'] = similar_songs
            except SparqlClientError:
                pass  # similar songs are optional; don't break the page

    except SparqlClientError as exc:
        ctx['error_message'] = str(exc)

    return render(request, 'song_detail.html', ctx)


# ── Artist Detail ─────────────────────────────────────────────────────────────

def artist_detail(request):
    uri = request.GET.get('uri', '').strip()
    if not _valid_music_uri(uri):
        return redirect('songs')

    ctx = {}
    try:
        bindings = run_select(f"""
                        SELECT ?artistName ?song ?songName ?genre ?popularity ?energy ?danceability ?valence
                        WHERE {{
                            BIND(<{uri}> AS ?artist)
                            ?artist pred:name ?artistName .
                            ?song a type:Song ;
                                        pred:mainArtist ?artist ;
                                        pred:name ?songName .
                            OPTIONAL {{ ?song pred:genre ?genre . }}
                            OPTIONAL {{ ?song pred:popularity ?popularity . }}
                            OPTIONAL {{ ?song pred:energy ?energy . }}
                            OPTIONAL {{ ?song pred:danceability ?danceability . }}
                            OPTIONAL {{ ?song pred:valence ?valence . }}
                        }}
                        ORDER BY ?songName
                """)

        if not bindings:
            return render(request, 'artist_detail.html', {'error_message': 'Artist not found.'})

        artist_name = _clean_artist_label(_val(bindings[0], 'artistName'))
        # Each genre carries its source ("Dataset" vs "Wikidata") for the tooltip.
        genres = []
        seen_genre = set()
        for r in bindings:
            for genre in _split_genres(_val(r, 'genre', None)):
                if genre.lower() not in seen_genre:
                    seen_genre.add(genre.lower())
                    genres.append({'name': genre, 'source': 'Dataset'})

        seen_songs = set()
        songs_list = []
        for r in bindings:
            s_uri = _val(r, 'song')
            if s_uri not in seen_songs:
                seen_songs.add(s_uri)
                songs_list.append({
                    'uri': s_uri,
                    'name': _val(r, 'songName'),
                    'genre': (_split_genres(_val(r, 'genre', None)) or [None])[0],
                    'popularity': _safe_float(_val(r, 'popularity', None)),
                    'energy': _safe_float(_val(r, 'energy', None)),
                    'danceability': _safe_float(_val(r, 'danceability', None)),
                    'valence': _safe_float(_val(r, 'valence', None)),
                })

        chart_bindings = run_select(f"""
            SELECT (MIN(?rank) AS ?bestRank) (COUNT(DISTINCT ?entry) AS ?chartEntries)
            WHERE {{
              BIND(<{uri}> AS ?artist)
              ?entry a type:ChartEntry ;
                     pred:song ?song ;
                     pred:rank ?rank .
              ?song pred:mainArtist ?artist .
            }}
        """)
        best_rank = _val(chart_bindings[0], 'bestRank') if chart_bindings else '—'
        chart_entries = _val(chart_bindings[0], 'chartEntries') if chart_bindings else '0'

        collab_bindings = run_select(f"""
            SELECT ?collab (SAMPLE(?collabName) AS ?collabDisplay)
                   (COUNT(DISTINCT ?sharedSong) AS ?sharedSongs)
            WHERE {{
                BIND(<{uri}> AS ?artist)
                {{
                    ?sharedSong a type:Song ;
                                pred:mainArtist ?artist ;
                                pred:featuredArtist ?collab .
                }}
                UNION
                {{
                    ?sharedSong a type:Song ;
                                pred:mainArtist ?collab ;
                                pred:featuredArtist ?artist .
                }}
                ?collab pred:name ?collabName .
                FILTER(?collab != ?artist)
            }}
            GROUP BY ?collab
            ORDER BY DESC(?sharedSongs)
            LIMIT 12
        """)

        collaborators = [
            {
                'uri': _val(r, 'collab'),
                'name': _clean_artist_label(_val(r, 'collabDisplay')),
                'shared_songs': _val(r, 'sharedSongs', '0'),
                'chart_overlap': _val(r, 'chartOverlap', '0'),
                'score': _val(r, 'collabScore', '0'),
                'shared_tracks': [],
            }
            for r in collab_bindings
        ]

        collab_uris = [c['uri'] for c in collaborators if c.get('uri')]
        shared_tracks_map = {}

        if collab_uris:
            values_collab = " ".join(f"<{u}>" for u in collab_uris)
            try:
                shared_song_bindings = run_select(f"""
                    SELECT ?collab ?song ?songName
                    WHERE {{
                        BIND(<{uri}> AS ?artist)
                        VALUES ?collab {{ {values_collab} }}
                        {{
                            ?song a type:Song ;
                                  pred:mainArtist ?artist ;
                                  pred:featuredArtist ?collab .
                        }}
                        UNION
                        {{
                            ?song a type:Song ;
                                  pred:mainArtist ?collab ;
                                  pred:featuredArtist ?artist .
                        }}
                        ?song pred:name ?songName .
                    }}
                    ORDER BY ?collab ?songName
                """)
            except SparqlClientError:
                shared_song_bindings = []

            seen_track_uris = {}
            for r in shared_song_bindings:
                c_uri = _val(r, 'collab')
                s_uri = _val(r, 'song')
                s_name = _val(r, 'songName')
                if not c_uri or not s_uri:
                    continue

                if c_uri not in seen_track_uris:
                    seen_track_uris[c_uri] = set()
                    shared_tracks_map[c_uri] = []

                if s_uri not in seen_track_uris[c_uri]:
                    seen_track_uris[c_uri].add(s_uri)
                    shared_tracks_map[c_uri].append(s_name)

        for c in collaborators:
            overlap_count = 0
            try:
                overlap_bindings = run_select(f"""
                    SELECT (COUNT(DISTINCT ?chartDate) AS ?chartOverlap)
                    WHERE {{
                        BIND(<{uri}> AS ?artist)
                        BIND(<{c['uri']}> AS ?collab)
                        {{
                            ?sharedSong a type:Song ;
                                        pred:mainArtist ?artist ;
                                        pred:featuredArtist ?collab .
                        }}
                        UNION
                        {{
                            ?sharedSong a type:Song ;
                                        pred:mainArtist ?collab ;
                                        pred:featuredArtist ?artist .
                        }}
                        ?entry a type:ChartEntry ;
                               pred:song ?sharedSong ;
                               pred:date ?chartDate .
                    }}
                """)
                overlap_count = _safe_int(_val(overlap_bindings[0], 'chartOverlap', '0')) if overlap_bindings else 0
            except SparqlClientError:
                overlap_count = 0

            shared_count = _safe_int(c.get('shared_songs'), 0)
            c['chart_overlap'] = str(overlap_count)
            c['score'] = str((shared_count * 2) + overlap_count)
            c['shared_tracks'] = shared_tracks_map.get(c['uri'], [])

        collaborators.sort(
            key=lambda row: (_safe_int(row.get('score')), _safe_int(row.get('shared_songs'))),
            reverse=True,
        )

        collab_graph = []
        if collaborators:
            total = len(collaborators)
            angle_step = (2 * math.pi) / total
            radius = 39
            start_angle = -math.pi / 2

            for i, c in enumerate(collaborators):
                angle = start_angle + (i * angle_step)
                x = 50 + (radius * math.cos(angle))
                y = 50 + (radius * math.sin(angle))
                preview_tracks = c['shared_tracks'][:2]
                more_tracks = max(len(c['shared_tracks']) - len(preview_tracks), 0)

                collab_graph.append({
                    'uri': c['uri'],
                    'name': c['name'],
                    'shared_songs': c['shared_songs'],
                    'chart_overlap': c['chart_overlap'],
                    'score': c['score'],
                    'preview_tracks': preview_tracks,
                    'more_tracks': more_tracks,
                    'x': round(x, 2),
                    'y': round(y, 2),
                    'tooltip': (
                        f"{c['name']} | Score {c['score']} | "
                        f"{c['shared_songs']} songs | Overlap {c['chart_overlap']}"
                    ),
                })

        pop_values = [s['popularity'] for s in songs_list if isinstance(s['popularity'], float)]
        avg_pop = round(sum(pop_values) / len(pop_values), 1) if pop_values else '—'
        energy_values = [s['energy'] for s in songs_list if isinstance(s['energy'], float)]
        dance_values = [s['danceability'] for s in songs_list if isinstance(s['danceability'], float)]
        valence_values = [s['valence'] for s in songs_list if isinstance(s['valence'], float)]

        avg_energy = round(sum(energy_values) / len(energy_values), 3) if energy_values else '—'
        avg_danceability = round(sum(dance_values) / len(dance_values), 3) if dance_values else '—'
        avg_valence = round(sum(valence_values) / len(valence_values), 3) if valence_values else '—'

        ctx['artist'] = {
            'uri': uri,
            'name': artist_name,
            'genres': genres,
            'song_count': len(songs_list),
            'chart_entries': chart_entries,
            'best_rank': best_rank,
            'avg_energy': avg_energy,
            'avg_danceability': avg_danceability,
            'avg_valence': avg_valence,
            'avg_popularity': avg_pop,
            'collaborator_count': len(collaborators),
        }
        ctx['songs'] = songs_list
        ctx['collaborators'] = collaborators
        ctx['collab_graph'] = collab_graph

        # ── External enrichment (DBpedia + Wikidata via enrich_artists.py) ──
        # All OPTIONAL: the page works whether or not artists_external.ttl was
        # loaded into GraphDB. owl:sameAs uses the full IRI to avoid prefix deps.
        try:
            enrich_rows = run_select(f"""
                                SELECT (SAMPLE(?countryDisplay) AS ?country) (SAMPLE(?countryNode) AS ?countryUri)
                                             (SAMPLE(?birthPlace) AS ?birthPlace) (SAMPLE(?birthDate) AS ?birthDate)
                                             (SAMPLE(?inception) AS ?inception) (SAMPLE(?website) AS ?website)
                                             (SAMPLE(?image) AS ?image) (SAMPLE(?thumbnail) AS ?thumbnail)
                                             (SAMPLE(?description) AS ?description) (SAMPLE(?abstract) AS ?abstract)
                                             (SAMPLE(?mbid) AS ?mbid)
                       (GROUP_CONCAT(DISTINCT ?genre; separator="||") AS ?genres)
                       (GROUP_CONCAT(DISTINCT ?same; separator="||") AS ?sameAs)
                WHERE {{
                  BIND(<{uri}> AS ?artist)
                                    OPTIONAL {{
                                        ?artist pred:originCountry ?countryNode .
                                        FILTER(isIRI(?countryNode))
                                        OPTIONAL {{
                                            ?countryNode <http://www.w3.org/2000/01/rdf-schema#label> ?countryNodeLabel .
                                            FILTER(lang(?countryNodeLabel) = "en" || lang(?countryNodeLabel) = "")
                                        }}
                                    }}
                                    OPTIONAL {{
                                        ?artist pred:originCountry ?countryLiteral .
                                        FILTER(!isIRI(?countryLiteral))
                                    }}
                                    OPTIONAL {{ ?artist pred:originCountryLabel ?countryLegacyLabel }}
                                    BIND(COALESCE(?countryNodeLabel, ?countryLegacyLabel, ?countryLiteral) AS ?countryDisplay)
                  OPTIONAL {{ ?artist pred:birthPlace ?birthPlace }}
                  OPTIONAL {{ ?artist pred:birthDate ?birthDate }}
                  OPTIONAL {{ ?artist pred:inceptionDate ?inception }}
                  OPTIONAL {{ ?artist pred:website ?website }}
                  OPTIONAL {{ ?artist pred:image ?image }}
                  OPTIONAL {{ ?artist pred:thumbnail ?thumbnail }}
                  OPTIONAL {{ ?artist pred:description ?description }}
                  OPTIONAL {{ ?artist pred:abstract ?abstract }}
                  OPTIONAL {{ ?artist pred:musicBrainzId ?mbid }}
                  OPTIONAL {{ ?artist pred:externalGenre ?genre }}
                  OPTIONAL {{ ?artist <http://www.w3.org/2002/07/owl#sameAs> ?same }}
                }}
            """)
            if enrich_rows:
                row = enrich_rows[0]
                dbpedia = wikidata = None
                for link in _val(row, 'sameAs', '').split('||'):
                    if 'dbpedia.org' in link:
                        dbpedia = link
                    elif 'wikidata.org' in link:
                        wikidata = link
                ext_genres = [g for g in _val(row, 'genres', '').split('||') if g]
                photo = _val(row, 'image', None) or _val(row, 'thumbnail', None)
                mbid = _val(row, 'mbid', None)
                enrichment = {
                    'photo': photo if photo and photo != '—' else None,
                    'country': _val(row, 'country', None),
                    'country_uri': _val(row, 'countryUri', None),
                    'birth_place': _val(row, 'birthPlace', None),
                    'birth_date': _val(row, 'birthDate', None),
                    'inception': _val(row, 'inception', None),
                    'website': _val(row, 'website', None),
                    'description': _val(row, 'description', None),
                    'abstract': _val(row, 'abstract', None),
                    'genres': ext_genres,
                    'dbpedia': dbpedia,
                    'wikidata': wikidata,
                    'musicbrainz': (
                        f'https://musicbrainz.org/artist/{mbid}'
                        if mbid and mbid != '—' else None
                    ),
                }
                # Only attach if at least one field has real data.
                has_data = ext_genres or any(
                    v and v != '—'
                    for k, v in enrichment.items() if k != 'genres'
                )
                if has_data:
                    ctx['enrichment'] = enrichment
                    # Merge external (Wikidata) genres into the single genre row
                    # shown at the top (deduplicated), so all genres live in one
                    # place, each tagged with its source for the tooltip.
                    existing = {g['name'].lower() for g in ctx['artist']['genres']}
                    for g in ext_genres:
                        if g.lower() not in existing:
                            ctx['artist']['genres'].append({'name': g, 'source': 'Wikidata'})
                            existing.add(g.lower())
        except SparqlClientError:
            pass  # enrichment is optional; never break the page

    except SparqlClientError as exc:
        ctx['error_message'] = str(exc)

    return render(request, 'artist_detail.html', ctx)


# ── SPARQL Operations ─────────────────────────────────────────────────────────

def operations(request):
    ctx = {
        'song_options': [],
        'artist_options': [],
        'genre_options': [],
        'chart_entry_options': [],
        'chart_entries_by_song': {},
        'song_attribute_map': {},
        'song_genres_map': {},
        'artist_delete_name': '',
        'artist_delete_songs': [],
    }

    allowed_attributes = {
        'energy': {'predicate': 'pred:energy', 'min': 0.0, 'max': 1.0},
        'danceability': {'predicate': 'pred:danceability', 'min': 0.0, 'max': 1.0},
        'valence': {'predicate': 'pred:valence', 'min': 0.0, 'max': 1.0},
        'acousticness': {'predicate': 'pred:acousticness', 'min': 0.0, 'max': 1.0},
        'speechiness': {'predicate': 'pred:speechiness', 'min': 0.0, 'max': 1.0},
        'instrumentalness': {'predicate': 'pred:instrumentalness', 'min': 0.0, 'max': 1.0},
        'liveness': {'predicate': 'pred:liveness', 'min': 0.0, 'max': 1.0},
        'tempo': {'predicate': 'pred:tempo', 'min': 0.0, 'max': 300.0},
    }

    def _load_options():
        cached_options = cache.get(OPERATIONS_OPTIONS_CACHE_KEY)
        if cached_options:
            ctx.update(cached_options)
            return

        try:
            song_rows = run_select("""
                SELECT ?songName
                       (MAX(IF(BOUND(?energy), 1, 0)) AS ?hasEnergy)
                       (MAX(IF(BOUND(?danceability), 1, 0)) AS ?hasDanceability)
                       (MAX(IF(BOUND(?valence), 1, 0)) AS ?hasValence)
                     (MAX(IF(BOUND(?acousticness), 1, 0)) AS ?hasAcousticness)
                     (MAX(IF(BOUND(?speechiness), 1, 0)) AS ?hasSpeechiness)
                     (MAX(IF(BOUND(?instrumentalness), 1, 0)) AS ?hasInstrumentalness)
                     (MAX(IF(BOUND(?liveness), 1, 0)) AS ?hasLiveness)
                       (MAX(IF(BOUND(?tempo), 1, 0)) AS ?hasTempo)
                WHERE {
                  ?song a type:Song ;
                        pred:name ?songName .
                  OPTIONAL { ?song pred:energy ?energy }
                  OPTIONAL { ?song pred:danceability ?danceability }
                  OPTIONAL { ?song pred:valence ?valence }
                OPTIONAL { ?song pred:acousticness ?acousticness }
                OPTIONAL { ?song pred:speechiness ?speechiness }
                OPTIONAL { ?song pred:instrumentalness ?instrumentalness }
                OPTIONAL { ?song pred:liveness ?liveness }
                  OPTIONAL { ?song pred:tempo ?tempo }
                }
                GROUP BY ?songName
                ORDER BY ?songName
                LIMIT 5000
            """)

            song_options = []
            song_attribute_map = {}
            for row in song_rows:
                song_name = _val(row, 'songName')
                if song_name == '—':
                    continue
                song_options.append(song_name)

                attrs = []
                if _val(row, 'hasEnergy') == '1':
                    attrs.append('energy')
                if _val(row, 'hasDanceability') == '1':
                    attrs.append('danceability')
                if _val(row, 'hasValence') == '1':
                    attrs.append('valence')
                if _val(row, 'hasAcousticness') == '1':
                    attrs.append('acousticness')
                if _val(row, 'hasSpeechiness') == '1':
                    attrs.append('speechiness')
                if _val(row, 'hasInstrumentalness') == '1':
                    attrs.append('instrumentalness')
                if _val(row, 'hasLiveness') == '1':
                    attrs.append('liveness')
                if _val(row, 'hasTempo') == '1':
                    attrs.append('tempo')
                song_attribute_map[song_name] = attrs

            ctx['song_options'] = song_options
            ctx['song_attribute_map'] = song_attribute_map

            song_genre_rows = run_select("""
                SELECT ?songName ?genre
                WHERE {
                  ?song a type:Song ;
                        pred:name ?songName .
                  OPTIONAL { ?song pred:genre ?genre . }
                }
                ORDER BY ?songName ?genre
                LIMIT 10000
            """)
            song_genres_map = {}
            for row in song_genre_rows:
                song_name = _val(row, 'songName')
                genre = _val(row, 'genre', None)
                if not song_name or song_name == '—':
                    continue
                if song_name not in song_genres_map:
                    song_genres_map[song_name] = []
                if genre and genre != '—' and genre not in song_genres_map[song_name]:
                    song_genres_map[song_name].append(genre)
            ctx['song_genres_map'] = song_genres_map

            artist_rows = run_select("""
                SELECT DISTINCT ?artistName
                WHERE {
                  ?artist a type:Artist ;
                          pred:name ?artistName .
                }
                ORDER BY ?artistName
                LIMIT 10000
            """)
            ctx['artist_options'] = [_val(r, 'artistName') for r in artist_rows if _val(r, 'artistName') != '—']

            genre_rows = run_select("""
                SELECT DISTINCT ?genre
                WHERE {
                  ?song pred:genre ?genre .
                }
                ORDER BY ?genre
                LIMIT 1000
            """)
            ctx['genre_options'] = [_val(r, 'genre') for r in genre_rows if _val(r, 'genre') != '—']

            entry_rows = run_select("""
                SELECT ?entry ?songName ?date ?rank ?weeks
                WHERE {
                  ?entry a type:ChartEntry ;
                         pred:song ?song ;
                         pred:date ?date ;
                         pred:rank ?rank ;
                         pred:weeks ?weeks .
                  ?song pred:name ?songName .
                }
                ORDER BY ?songName DESC(?date) ?entry
            """)
            ctx['chart_entry_options'] = [_val(r, 'entry') for r in entry_rows if _val(r, 'entry') != '—']

            chart_entries_by_song = {}
            for row in entry_rows:
                song_name = _val(row, 'songName')
                entry_uri = _val(row, 'entry')
                if song_name == '—' or entry_uri == '—':
                    continue
                date = _val(row, 'date', '—')
                rank = _val(row, 'rank', '—')
                weeks = _val(row, 'weeks', '—')
                label = f'{date} | rank {rank} | weeks {weeks}'
                chart_entries_by_song.setdefault(song_name, []).append({
                    'uri': entry_uri,
                    'label': label,
                    'date': date,
                    'rank': rank,
                    'weeks': weeks,
                })
            ctx['chart_entries_by_song'] = chart_entries_by_song

            cache.set(
                OPERATIONS_OPTIONS_CACHE_KEY,
                {
                    'song_options': ctx['song_options'],
                    'artist_options': ctx['artist_options'],
                    'genre_options': ctx['genre_options'],
                    'chart_entry_options': ctx['chart_entry_options'],
                    'chart_entries_by_song': ctx['chart_entries_by_song'],
                    'song_attribute_map': ctx['song_attribute_map'],
                    'song_genres_map': ctx['song_genres_map'],
                },
                OPERATIONS_OPTIONS_CACHE_TTL,
            )
        except (SparqlClientError, StopIteration):
            pass

    def _song_uri_by_name(song_name_literal):
        rows = run_select(f"""
            SELECT ?song
            WHERE {{
              ?song a type:Song ;
                    pred:name {song_name_literal} .
            }}
            LIMIT 1
        """)
        return _val(rows[0], 'song', None) if rows else None

    def _artist_uri_by_name(artist_name_literal):
        rows = run_select(f"""
            SELECT ?artist
            WHERE {{
              ?artist a type:Artist ;
                      pred:name {artist_name_literal} .
            }}
            LIMIT 1
        """)
        return _val(rows[0], 'artist', None) if rows else None

    def _song_exists_exact(song_name_literal):
        return _song_uri_by_name(song_name_literal) is not None

    def _artist_exists_exact(artist_name_literal):
        return _artist_uri_by_name(artist_name_literal) is not None

    def _entry_exists(entry_uri):
        rows = run_select(f"""
            SELECT ?entry
            WHERE {{
              BIND(<{entry_uri}> AS ?entry)
              ?entry a type:ChartEntry .
            }}
            LIMIT 1
        """)
        return bool(rows)

    def _entry_uri_by_song_and_date(song_name_literal, date_literal):
        rows = run_select(f"""
            SELECT ?entry
            WHERE {{
              ?song a type:Song ;
                    pred:name {song_name_literal} .
              ?entry a type:ChartEntry ;
                     pred:song ?song ;
                     pred:date {date_literal} .
            }}
            LIMIT 2
        """)
        if not rows:
            return None
        if len(rows) > 1:
            raise SparqlClientError('More than one chart entry found for this song/date. Please use ChartEntry URI.')
        return _val(rows[0], 'entry', None)

    def _song_has_attribute(song_name_literal, predicate):
        rows = run_select(f"""
            SELECT ?v
            WHERE {{
              ?song a type:Song ;
                    pred:name {song_name_literal} ;
                    {predicate} ?v .
            }}
            LIMIT 1
        """)
        return bool(rows)

    def _song_has_genre(song_name_literal, genre_literal):
        rows = run_select(f"""
            SELECT ?genre
            WHERE {{
              ?song a type:Song ;
                    pred:name {song_name_literal} ;
                    pred:genre {genre_literal} .
            }}
            LIMIT 1
        """)
        return bool(rows)

    def _new_uri(kind, seed):
        digest = hashlib.md5(seed.encode()).hexdigest()[:12]
        return f"http://music.org/{kind}/manual-{digest}"

    if request.method == 'POST':
        op = request.POST.get('operation', '')
        try:
            # ── Songs CRUD ───────────────────────────────────────────────────
            if op == 'song_add':
                song_name_raw = request.POST.get('song_name', '').strip()
                artist_name_raw = request.POST.get('artist_name', '').strip()
                genre_raw = request.POST.get('genre', '').strip()
                if not song_name_raw or not artist_name_raw:
                    raise SparqlClientError('Song name and main artist are required.')
                song_name = sparql_escape_literal(song_name_raw)
                artist_name = sparql_escape_literal(artist_name_raw)
                genre = sparql_escape_literal(genre_raw) if genre_raw else None
                if _song_exists_exact(song_name):
                    raise SparqlClientError('Song already exists (exact name).')
                artist_uri = _artist_uri_by_name(artist_name)
                if not artist_uri:
                    artist_uri = _new_uri('artist', artist_name_raw)
                    run_update(f"""
                        INSERT DATA {{
                          <{artist_uri}> a type:Artist ;
                            pred:name {artist_name} .
                        }}
                    """)
                song_uri = _new_uri('song', f'{song_name_raw}|{artist_name_raw}')
                genre_line = f' ;\n                            pred:genre {genre}' if genre else ''
                run_update(f"""
                    INSERT DATA {{
                      <{song_uri}> a type:Song ;
                        pred:name {song_name} ;
                        pred:mainArtist <{artist_uri}>{genre_line} .
                    }}
                """)
                ctx['success_message'] = 'Song added successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op == 'song_edit':
                old_name_raw = request.POST.get('old_song_name', '').strip()
                new_name_raw = request.POST.get('new_song_name', '').strip()
                if not old_name_raw or not new_name_raw:
                    raise SparqlClientError('Both current and new song names are required.')
                old_name = sparql_escape_literal(old_name_raw)
                new_name = sparql_escape_literal(new_name_raw)
                if not _song_exists_exact(old_name):
                    raise SparqlClientError('Song not found (exact name required).')
                run_update(f"""
                    DELETE {{
                      ?song pred:name {old_name} .
                    }}
                    INSERT {{
                      ?song pred:name {new_name} .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {old_name} .
                    }}
                """)
                ctx['success_message'] = 'Song name updated successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op == 'song_delete':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                run_update(f"""
                    DELETE {{
                      ?entry ?ep ?eo .
                      ?song ?sp ?so .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} .
                      OPTIONAL {{
                        ?entry a type:ChartEntry ;
                               pred:song ?song ;
                               ?ep ?eo .
                      }}
                      ?song ?sp ?so .
                    }}
                """)
                ctx['success_message'] = 'Song deleted successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            # ── Genres CRUD ──────────────────────────────────────────────────
            elif op in ('add_genre', 'genre_add'):
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                genre = sparql_escape_literal(request.POST.get('genre', '').strip())
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                run_update(f"""
                    INSERT {{
                      ?song pred:genre {genre} .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} .
                    }}
                """)
                ctx['success_message'] = 'Genre added successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op == 'genre_edit':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                old_genre = sparql_escape_literal(request.POST.get('old_genre', '').strip())
                new_genre = sparql_escape_literal(request.POST.get('new_genre', '').strip())
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                if not _song_has_genre(song_name, old_genre):
                    raise SparqlClientError('Old genre is not linked to this song.')
                run_update(f"""
                    DELETE {{
                      ?song pred:genre {old_genre} .
                    }}
                    INSERT {{
                      ?song pred:genre {new_genre} .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} ;
                            pred:genre {old_genre} .
                    }}
                """)
                ctx['success_message'] = 'Genre updated successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op == 'genre_delete':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                genre = sparql_escape_literal(request.POST.get('genre', '').strip())
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                if not _song_has_genre(song_name, genre):
                    raise SparqlClientError('Genre is not linked to this song.')
                run_update(f"""
                    DELETE {{
                      ?song pred:genre {genre} .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} ;
                            pred:genre {genre} .
                    }}
                """)
                ctx['success_message'] = 'Genre removed successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            # ── Attributes CRUD ──────────────────────────────────────────────
            elif op == 'attribute_add':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                attribute = request.POST.get('attribute', '').strip()
                attr_config = allowed_attributes.get(attribute)
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                if not attr_config:
                    raise SparqlClientError(
                        'Invalid attribute. Allowed: energy, danceability, valence, acousticness, speechiness, instrumentalness, liveness, tempo.'
                    )
                try:
                    value = float(request.POST.get('value', ''))
                    if value < attr_config['min'] or value > attr_config['max']:
                        raise ValueError
                except ValueError:
                    raise SparqlClientError(
                        f"Invalid value for {attribute} (must be between {attr_config['min']} and {attr_config['max']})."
                    )
                predicate = attr_config['predicate']
                if _song_has_attribute(song_name, predicate):
                    raise SparqlClientError(f'{attribute.capitalize()} already exists. Use edit.')
                run_update(f"""
                    INSERT {{
                      ?song {predicate} {value} .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} .
                    }}
                """)
                ctx['success_message'] = f'{attribute.capitalize()} added successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op in ('edit_attribute', 'attribute_edit'):
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                attribute = request.POST.get('attribute', '').strip()
                attr_config = allowed_attributes.get(attribute)
                if not attr_config:
                    raise SparqlClientError(
                        'Invalid attribute. Allowed: energy, danceability, valence, acousticness, speechiness, instrumentalness, liveness, tempo.'
                    )
                try:
                    value = float(request.POST.get('value', ''))
                    if value < attr_config['min'] or value > attr_config['max']:
                        raise ValueError
                except ValueError:
                    raise SparqlClientError(
                        f"Invalid value for {attribute} (must be between {attr_config['min']} and {attr_config['max']})."
                    )
                predicate = attr_config['predicate']
                if not _song_has_attribute(song_name, predicate):
                    raise SparqlClientError(f'{attribute.capitalize()} does not exist. Use add.')
                run_update(f"""
                    DELETE {{
                      ?song {predicate} ?old .
                    }}
                    INSERT {{
                      ?song {predicate} {value} .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} .
                      OPTIONAL {{ ?song {predicate} ?old . }}
                    }}
                """)
                ctx['success_message'] = f'{attribute.capitalize()} updated successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op == 'attribute_delete':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                attribute = request.POST.get('attribute', '').strip()
                attr_config = allowed_attributes.get(attribute)
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                if not attr_config:
                    raise SparqlClientError(
                        'Invalid attribute. Allowed: energy, danceability, valence, acousticness, speechiness, instrumentalness, liveness, tempo.'
                    )
                predicate = attr_config['predicate']
                if not _song_has_attribute(song_name, predicate):
                    raise SparqlClientError(f'{attribute.capitalize()} is not set for this song.')
                run_update(f"""
                    DELETE {{
                      ?song {predicate} ?v .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} ;
                            {predicate} ?v .
                    }}
                """)
                ctx['success_message'] = f'{attribute.capitalize()} removed successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            # ── Artists CRUD ─────────────────────────────────────────────────
            elif op in ('artist_add', 'add_artist'):
                artist_name_raw = request.POST.get('artist_name', '').strip()
                if not artist_name_raw:
                    raise SparqlClientError('Artist name is required.')
                artist_name = sparql_escape_literal(artist_name_raw)
                if _artist_exists_exact(artist_name):
                    raise SparqlClientError('Artist already exists (exact name).')
                artist_uri = _new_uri('artist', artist_name_raw)
                run_update(f"""
                    INSERT DATA {{
                      <{artist_uri}> a type:Artist ;
                        pred:name {artist_name} .
                    }}
                """)
                ctx['success_message'] = 'Artist added successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op in ('artist_edit', 'edit_artist'):
                old_name_raw = request.POST.get('old_artist_name', '').strip()
                new_name_raw = request.POST.get('new_artist_name', '').strip()
                if not old_name_raw or not new_name_raw:
                    raise SparqlClientError('Both current and new artist names are required.')
                old_name = sparql_escape_literal(old_name_raw)
                new_name = sparql_escape_literal(new_name_raw)
                if not _artist_exists_exact(old_name):
                    raise SparqlClientError('Artist not found (exact name required).')
                run_update(f"""
                    DELETE {{
                      ?artist pred:name {old_name} .
                    }}
                    INSERT {{
                      ?artist pred:name {new_name} .
                    }}
                    WHERE {{
                      ?artist a type:Artist ;
                              pred:name {old_name} .
                    }}
                """)
                ctx['success_message'] = 'Artist name updated successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op in ('artist_delete', 'remove_artist'):
                artist_name_raw = request.POST.get('artist_name', '').strip()
                artist_name = sparql_escape_literal(artist_name_raw)
                force_delete = request.POST.get('force_delete_artist') == '1'
                artist_uri = _artist_uri_by_name(artist_name)
                if not artist_uri:
                    raise SparqlClientError('Artist not found (exact name required).')
                linked_song_rows = run_select(f"""
                    SELECT ?songName
                    WHERE {{
                      ?song a type:Song ;
                            pred:mainArtist <{artist_uri}> ;
                            pred:name ?songName .
                    }}
                    ORDER BY ?songName
                """)
                linked_song_names = [_val(r, 'songName') for r in linked_song_rows if _val(r, 'songName') != '—']
                if linked_song_names and not force_delete:
                    ctx['artist_delete_name'] = artist_name_raw
                    ctx['artist_delete_songs'] = linked_song_names
                    raise SparqlClientError(
                        'Artist is linked as main artist to existing songs. Select "Delete linked songs and chart entries" to continue.'
                    )
                if linked_song_names:
                    run_update(f"""
                        DELETE {{
                          ?entry ?ep ?eo .
                        }}
                        WHERE {{
                          ?song a type:Song ;
                                pred:mainArtist <{artist_uri}> .
                          ?entry a type:ChartEntry ;
                                 pred:song ?song ;
                                 ?ep ?eo .
                        }}
                    """)
                    run_update(f"""
                        DELETE {{
                          ?song ?sp ?so .
                        }}
                        WHERE {{
                          ?song a type:Song ;
                                pred:mainArtist <{artist_uri}> ;
                                ?sp ?so .
                        }}
                    """)
                run_update(f"""
                    DELETE WHERE {{
                      <{artist_uri}> ?p ?o .
                    }}
                """)
                run_update(f"""
                    DELETE WHERE {{
                      ?song pred:featuredArtist <{artist_uri}> .
                    }}
                """)
                if linked_song_names:
                    ctx['success_message'] = f'Artist deleted successfully. Also removed {len(linked_song_names)} linked song(s) and related chart entries.'
                else:
                    ctx['success_message'] = 'Artist deleted successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            # ── Chart Entry CRUD ─────────────────────────────────────────────
            elif op in ('add_chart_entry', 'chart_add'):
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                try:
                    rank = int(request.POST.get('rank', '0'))
                    weeks = int(request.POST.get('weeks', '0'))
                    if rank < 1 or weeks < 1:
                        raise ValueError
                except ValueError:
                    raise SparqlClientError('Invalid rank or weeks (must be positive integers).')
                date = request.POST.get('date', '').strip()
                try:
                    datetime.strptime(date, '%Y-%m-%d')
                except ValueError:
                    raise SparqlClientError('Invalid date format (expected YYYY-MM-DD).')
                date_lit = sparql_escape_literal(date)
                entry_id = hashlib.md5(f"{song_name}{date}{rank}".encode()).hexdigest()[:12]
                run_update(f"""
                    INSERT {{
                      <http://music.org/entry/manual-{entry_id}> a type:ChartEntry ;
                        pred:song ?song ;
                        pred:rank {rank} ;
                        pred:weeks {weeks} ;
                        pred:date {date_lit} .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} .
                    }}
                """)
                ctx['success_message'] = 'Chart entry added successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op == 'chart_edit':
                entry_uri = request.POST.get('entry_uri', '').strip()
                if not entry_uri or not _valid_music_uri(entry_uri) or not _entry_exists(entry_uri):
                    raise SparqlClientError('Chart entry not found or invalid reference.')
                try:
                    rank = int(request.POST.get('rank', '0'))
                    weeks = int(request.POST.get('weeks', '0'))
                    if rank < 1 or weeks < 1:
                        raise ValueError
                except ValueError:
                    raise SparqlClientError('Invalid rank or weeks (must be positive integers).')
                date = request.POST.get('date', '').strip()
                try:
                    datetime.strptime(date, '%Y-%m-%d')
                except ValueError:
                    raise SparqlClientError('Invalid date format (expected YYYY-MM-DD).')
                date_lit = sparql_escape_literal(date)
                run_update(f"""
                    DELETE {{
                      <{entry_uri}> pred:rank ?oldRank ;
                                    pred:weeks ?oldWeeks ;
                                    pred:date ?oldDate .
                    }}
                    INSERT {{
                      <{entry_uri}> pred:rank {rank} ;
                                    pred:weeks {weeks} ;
                                    pred:date {date_lit} .
                    }}
                    WHERE {{
                      <{entry_uri}> a type:ChartEntry ;
                                    pred:rank ?oldRank ;
                                    pred:weeks ?oldWeeks ;
                                    pred:date ?oldDate .
                    }}
                """)
                ctx['success_message'] = 'Chart entry updated successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            elif op in ('remove_chart_entry', 'chart_delete'):
                entry_uri = request.POST.get('entry_uri', '').strip()
                if not entry_uri or not _valid_music_uri(entry_uri):
                    raise SparqlClientError('Invalid chart entry reference.')
                if not _entry_exists(entry_uri):
                    raise SparqlClientError('Chart entry not found.')
                run_update(f"""
                    DELETE WHERE {{
                      <{entry_uri}> ?p ?o .
                    }}
                """)
                ctx['success_message'] = 'Chart entry removed successfully.'
                cache.delete(OPERATIONS_OPTIONS_CACHE_KEY)

            else:
                ctx['error_message'] = 'Unknown operation.'

        except SparqlClientError as exc:
            ctx['error_message'] = str(exc)

    _load_options()

    return render(request, 'operations.html', ctx)


# ── Insights ──────────────────────────────────────────────────────────────────

def insights(request):
    ctx = {'insights': {}}

    def safe_query(sparql, transform):
        try:
            return [transform(r) for r in run_select(sparql)]
        except SparqlClientError:
            return []

    ctx['insights']['party'] = safe_query("""
        SELECT ?song ?songName ?mainArtist ?artistName ?partyScore
        WHERE {
          ?song a type:Song ;
                pred:name ?songName ;
                pred:mainArtist ?mainArtist ;
                pred:energy ?energy ;
                pred:danceability ?danceability ;
                pred:valence ?valence .
          ?mainArtist pred:name ?artistName .
          BIND((?energy + ?danceability + ?valence) / 3 AS ?partyScore)
        }
        ORDER BY DESC(?partyScore)
        LIMIT 25
    """, lambda r: {
        'uri': _val(r, 'song'),
        'name': _val(r, 'songName'),
        'artist_uri': _val(r, 'mainArtist'),
        'artist': _clean_artist_label(_val(r, 'artistName')),
        'score': _safe_float(_val(r, 'partyScore')),
    })

    ctx['insights']['hidden_gems'] = safe_query("""
        SELECT ?song ?songName ?mainArtist ?artistName ?energy ?danceability ?chartCount
        WHERE {
          {
            SELECT ?song (COUNT(DISTINCT ?entry) AS ?chartCount)
            WHERE {
              ?song a type:Song ;
                    pred:energy ?energy ;
                    pred:danceability ?danceability .
              FILTER(?energy >= 0.75 && ?danceability >= 0.75)
              OPTIONAL {
                ?entry a type:ChartEntry ;
                       pred:song ?song .
              }
            }
            GROUP BY ?song
            HAVING(COUNT(DISTINCT ?entry) <= 2)
          }
          ?song pred:name ?songName ;
                pred:mainArtist ?mainArtist ;
                pred:energy ?energy ;
                pred:danceability ?danceability .
          ?mainArtist pred:name ?artistName .
        }
        ORDER BY ASC(?chartCount) DESC(?energy) DESC(?danceability)
        LIMIT 30
    """, lambda r: {
        'uri': _val(r, 'song'),
        'name': _val(r, 'songName'),
        'artist_uri': _val(r, 'mainArtist'),
        'artist': _clean_artist_label(_val(r, 'artistName')),
        'energy': _safe_float(_val(r, 'energy')),
        'danceability': _safe_float(_val(r, 'danceability')),
        'chart_count': _safe_int(_val(r, 'chartCount')),
    })

    try:
        versatile_raw = run_select("""
            SELECT ?artist ?artistName ?genre
            WHERE {
              ?artist a type:Artist ;
                      pred:name ?artistName .
              ?song a type:Song ;
                    pred:mainArtist ?artist .
              OPTIONAL {
                ?song pred:genre ?genre .
              }
            }
            ORDER BY ?artist
        """)
    except SparqlClientError:
        versatile_raw = []

    versatile_by_artist = {}
    for r in versatile_raw:
        artist_uri = _val(r, 'artist')
        if artist_uri not in versatile_by_artist:
            versatile_by_artist[artist_uri] = {
                'uri': artist_uri,
                'name': _clean_artist_label(_val(r, 'artistName')),
                'genres': set(),
            }
        genre_str = _val(r, 'genre', None)
        if genre_str:
            for genre in _split_genres(genre_str):
                versatile_by_artist[artist_uri]['genres'].add(genre)

    ctx['insights']['versatile'] = sorted(
        [
            {'uri': v['uri'], 'name': v['name'], 'genre_count': len(v['genres'])}
            for v in versatile_by_artist.values()
        ],
        key=lambda x: x['genre_count'],
        reverse=True,
    )[:20]

    ctx['insights']['resilient'] = safe_query("""
        SELECT ?song ?songName (MAX(?weeks) AS ?weeksPeak) (MIN(?rank) AS ?bestRank)
        WHERE {
          ?entry a type:ChartEntry ;
                 pred:song ?song ;
                 pred:weeks ?weeks ;
                 pred:rank ?rank .
          ?song pred:name ?songName .
        }
        GROUP BY ?song ?songName
        ORDER BY DESC(?weeksPeak) ?bestRank
        LIMIT 30
    """, lambda r: {
        'uri': _val(r, 'song'),
        'name': _val(r, 'songName'),
        'weeks_peak': _val(r, 'weeksPeak'),
        'best_rank': _val(r, 'bestRank'),
    })

    ctx['insights']['seasonality'] = safe_query("""
        SELECT ?month (COUNT(?entry) AS ?entries)
        WHERE {
          ?entry a type:ChartEntry ;
                 pred:date ?date .
          BIND(SUBSTR(STR(?date), 6, 2) AS ?month)
        }
        GROUP BY ?month
        ORDER BY ?month
    """, lambda r: {
        'month': MONTH_NAMES.get(_val(r, 'month'), _val(r, 'month')),
        'entries': _val(r, 'entries'),
    })

    ctx['insights']['collaboration_pairs'] = safe_query("""
        SELECT ?artistA (SAMPLE(?artistAName) AS ?artistADisplay)
               ?artistB (SAMPLE(?artistBName) AS ?artistBDisplay)
               (COUNT(DISTINCT ?song) AS ?collabs)
        WHERE {
          ?song a type:Song ;
                pred:mainArtist ?artistA ;
                pred:featuredArtist ?artistB .
          ?artistA pred:name ?artistAName .
          ?artistB pred:name ?artistBName .
          FILTER(?artistA != ?artistB)
        }
        GROUP BY ?artistA ?artistB
        ORDER BY DESC(?collabs)
        LIMIT 20
    """, lambda r: {
        'artist_a_uri': _val(r, 'artistA'),
        'artist_a_name': _clean_artist_label(_val(r, 'artistADisplay')),
        'artist_b_uri': _val(r, 'artistB'),
        'artist_b_name': _clean_artist_label(_val(r, 'artistBDisplay')),
        'collabs': _val(r, 'collabs'),
    })

    ctx['insights']['country_charted_songs'] = safe_query("""
        SELECT ?country (COALESCE(?countryName, ?legacyName, REPLACE(STR(?country), "^.*/", "")) AS ?countryLabel)
               (COUNT(DISTINCT ?song) AS ?numSongs)
        WHERE {
          ?song a type:Song ;
                pred:mainArtist ?artist .
          {
            ?song pred:hasChartEntry ?entry .
          }
          UNION
          {
            ?entry a type:ChartEntry ;
                   pred:song ?song .
          }
          ?artist pred:originCountry ?country .
          FILTER(isIRI(?country))
          OPTIONAL {
            ?country <http://www.w3.org/2000/01/rdf-schema#label> ?countryName .
            FILTER(lang(?countryName) = "en" || lang(?countryName) = "")
          }
          OPTIONAL { ?artist pred:originCountryLabel ?legacyName . }
        }
        GROUP BY ?country ?countryName ?legacyName
        ORDER BY DESC(?numSongs)
        LIMIT 12
    """, lambda r: {
        'uri': _val(r, 'country'),
        'label': _val(r, 'countryLabel'),
        'count': _safe_int(_val(r, 'numSongs')),
    })

    ctx['insights']['country_avg_popularity'] = safe_query("""
        SELECT ?country (COALESCE(?countryName, ?legacyName, REPLACE(STR(?country), "^.*/", "")) AS ?countryLabel)
               (AVG(?popularity) AS ?avgPopularity)
        WHERE {
          ?song a type:Song ;
                pred:mainArtist ?artist ;
                pred:popularity ?popularity .
          ?artist pred:originCountry ?country .
          FILTER(isIRI(?country))
          OPTIONAL {
            ?country <http://www.w3.org/2000/01/rdf-schema#label> ?countryName .
            FILTER(lang(?countryName) = "en" || lang(?countryName) = "")
          }
          OPTIONAL { ?artist pred:originCountryLabel ?legacyName . }
        }
        GROUP BY ?country ?countryName ?legacyName
        ORDER BY DESC(?avgPopularity)
        LIMIT 12
    """, lambda r: {
        'uri': _val(r, 'country'),
        'label': _val(r, 'countryLabel'),
        'avg_popularity': _safe_float(_val(r, 'avgPopularity'), 2),
    })

    return render(request, 'insights.html', ctx)


def country_detail(request):
    uri = request.GET.get('uri', '').strip()
    if not uri.startswith('http://www.wikidata.org/entity/'):
        return redirect('insights')

    ctx = {
        'country': {
            'uri': uri,
            'label': 'Unknown Country',
            'artists': 0,
            'songs': 0,
            'avg_popularity': '—',
        },
        'top_artists': [],
        'top_songs': [],
    }

    try:
        label_rows = run_select(f"""
            SELECT (COALESCE(?countryName, REPLACE(STR(?country), "^.*/", "")) AS ?countryLabel)
            WHERE {{
              BIND(<{uri}> AS ?country)
              OPTIONAL {{
                ?country <http://www.w3.org/2000/01/rdf-schema#label> ?countryName .
                FILTER(lang(?countryName) = "en" || lang(?countryName) = "")
              }}
            }}
            LIMIT 1
        """)
        if label_rows:
            ctx['country']['label'] = _val(label_rows[0], 'countryLabel', ctx['country']['label'])

        stat_rows = run_select(f"""
            SELECT (COUNT(DISTINCT ?artist) AS ?artists)
                   (COUNT(DISTINCT ?song) AS ?songs)
                   (AVG(?popularity) AS ?avgPopularity)
            WHERE {{
              BIND(<{uri}> AS ?country)
              ?artist pred:originCountry ?country .
              OPTIONAL {{
                ?song a type:Song ;
                      pred:mainArtist ?artist ;
                      pred:popularity ?popularity .
              }}
            }}
        """)
        if stat_rows:
            row = stat_rows[0]
            ctx['country']['artists'] = _safe_int(_val(row, 'artists'))
            ctx['country']['songs'] = _safe_int(_val(row, 'songs'))
            avg_pop = _val(row, 'avgPopularity', None)
            ctx['country']['avg_popularity'] = _safe_float(avg_pop, 2) if avg_pop and avg_pop != '—' else '—'

        artist_rows = run_select(f"""
            SELECT ?artist ?artistName
                   (COUNT(DISTINCT ?song) AS ?songs)
                   (COUNT(DISTINCT ?entry) AS ?chartEntries)
            WHERE {{
              BIND(<{uri}> AS ?country)
              ?artist pred:originCountry ?country ;
                      pred:name ?artistName .
              OPTIONAL {{
                ?song a type:Song ;
                      pred:mainArtist ?artist .
                OPTIONAL {{
                  ?entry a type:ChartEntry ;
                         pred:song ?song .
                }}
              }}
            }}
            GROUP BY ?artist ?artistName
            ORDER BY DESC(?chartEntries) DESC(?songs)
            LIMIT 20
        """)
        ctx['top_artists'] = [
            {
                'uri': _val(r, 'artist'),
                'name': _clean_artist_label(_val(r, 'artistName')),
                'songs': _safe_int(_val(r, 'songs')),
                'chart_entries': _safe_int(_val(r, 'chartEntries')),
            }
            for r in artist_rows
        ]

        song_rows = run_select(f"""
                SELECT (SAMPLE(?song) AS ?song) ?songName ?artist ?artistName
                   (SAMPLE(?popularityRaw) AS ?popularity)
                   (COUNT(DISTINCT ?entry) AS ?chartEntries)
                WHERE {{
                  BIND(<{uri}> AS ?country)
                  ?artist pred:originCountry ?country ;
                      pred:name ?artistName .
                  ?song a type:Song ;
                    pred:mainArtist ?artist ;
                    pred:name ?songName .
                  OPTIONAL {{ ?song pred:popularity ?popularityRaw . }}
                  OPTIONAL {{
                ?entry a type:ChartEntry ;
                       pred:song ?song .
                  }}
                }}
                GROUP BY ?songName ?artist ?artistName
                ORDER BY DESC(?popularity) DESC(?chartEntries) ?songName
                LIMIT 25
            """)
        ctx['top_songs'] = [
            {
                'uri': _val(r, 'song'),
                'name': _val(r, 'songName'),
                'artist_uri': _val(r, 'artist'),
                'artist_name': _clean_artist_label(_val(r, 'artistName')),
                'popularity': _safe_float(_val(r, 'popularity'), 2),
                'chart_entries': _safe_int(_val(r, 'chartEntries')),
            }
            for r in song_rows
        ]

    except SparqlClientError as exc:
        ctx['error_message'] = str(exc)

    return render(request, 'country_detail.html', ctx)


# ── Billboard ─────────────────────────────────────────────────────────────────

def billboard(request):
    ctx = {}
    try:
        dates_bindings = run_select("""
            SELECT DISTINCT ?date
            WHERE {
              ?entry a type:ChartEntry ;
                     pred:date ?date .
            }
            ORDER BY DESC(?date)
        """)
        dates = [_val(r, 'date') for r in dates_bindings if _val(r, 'date') != '—']

        date_tree = {}
        for d in dates:
            parts = d.split('-')
            if len(parts) == 3:
                y, m, day = parts
                if y not in date_tree:
                    date_tree[y] = {}
                if m not in date_tree[y]:
                    date_tree[y][m] = []
                date_tree[y][m].append(day)

        ctx['date_tree'] = date_tree
        ctx['month_names'] = MONTH_NAMES

        selected_date = request.GET.get('date', '').strip()
        if not selected_date:
            year = request.GET.get('year', '').strip()
            month = request.GET.get('month', '').strip()
            day = request.GET.get('day', '').strip()
            if year and month and day:
                selected_date = f"{year}-{month}-{day}"

        if not selected_date and dates:
            selected_date = dates[0]

        ctx['selected_date'] = selected_date

        if selected_date and len(selected_date.split('-')) == 3:
            y, m, d = selected_date.split('-')
            ctx['sel_year'] = y
            ctx['sel_month'] = m
            ctx['sel_day'] = d

        if selected_date:
            date_lit = sparql_escape_literal(selected_date)
            entries_bindings = run_select(f"""
                SELECT ?rank ?weeks ?song ?songName ?artist ?artistName
                WHERE {{
                  ?entry a type:ChartEntry ;
                         pred:date {date_lit} ;
                         pred:rank ?rank ;
                         pred:weeks ?weeks ;
                         pred:song ?song .
                  ?song pred:name ?songName ;
                        pred:mainArtist ?artist .
                  ?artist pred:name ?artistName .
                }}
            """)

            entries = []
            for r in entries_bindings:
                entries.append({
                    'rank': _safe_int(_val(r, 'rank', '0')),
                    'weeks': _safe_int(_val(r, 'weeks', '0')),
                    'song_uri': _val(r, 'song'),
                    'song_name': _val(r, 'songName'),
                    'artist_uri': _val(r, 'artist'),
                    'artist_name': _clean_artist_label(_val(r, 'artistName')),
                })

            entries.sort(key=lambda x: x['rank'])
            ctx['entries'] = entries

    except SparqlClientError as exc:
        ctx['error_message'] = str(exc)

    return render(request, 'billboard.html', ctx)


# ── About Data ────────────────────────────────────────────────────────────────

def about_data(request):
    return render(request, 'about_data.html', {})


# ── Lyrics proxy (lrclib.net) ─────────────────────────────────────────────────
def lyrics(request):
    from django.http import JsonResponse
    track = request.GET.get('track', '').strip()
    artist = request.GET.get('artist', '').strip()
    if not track or not artist:
        return JsonResponse({'error': 'Missing track or artist'}, status=400)

    url = 'https://lrclib.net/api/get?' + urllib.parse.urlencode({'track_name': track, 'artist_name': artist})
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MusicTrendsWS/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        return JsonResponse({'plainLyrics': data.get('plainLyrics') or '', 'syncedLyrics': data.get('syncedLyrics') or ''})
    except urllib.error.HTTPError:
        return JsonResponse({'error': 'Lyrics not found'}, status=404)
    except Exception:
        return JsonResponse({'error': 'Request failed'}, status=500)
