import hashlib
import math
import re

from django.shortcuts import render, redirect

from .sparql_client import SparqlClientError, run_select, run_update, sparql_escape_literal

# ── Helpers ──────────────────────────────────────────────────────────────────

MONTH_NAMES = {
    '01': 'January', '02': 'February', '03': 'March', '04': 'April',
    '05': 'May', '06': 'June', '07': 'July', '08': 'August',
    '09': 'September', '10': 'October', '11': 'November', '12': 'December',
}


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


# ── Dashboard ─────────────────────────────────────────────────────────────────

def home(request):
    ctx = {
        'stats': {'songs': '—', 'artists': '—', 'chart_entries': '—'},
        'top_artists': [],
        'top_songs': [],
    }

    try:
        r = run_select("SELECT (COUNT(?s) AS ?count) WHERE { ?s a type:Song . }")
        ctx['stats']['songs'] = _val(r[0], 'count') if r else '—'

        r = run_select("SELECT (COUNT(?a) AS ?count) WHERE { ?a a type:Artist . }")
        ctx['stats']['artists'] = _val(r[0], 'count') if r else '—'

        r = run_select("SELECT (COUNT(?e) AS ?count) WHERE { ?e a type:ChartEntry . }")
        ctx['stats']['chart_entries'] = _val(r[0], 'count') if r else '—'

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
            SELECT ?song ?songName ?popularity
            WHERE {
              ?song a type:Song ;
                    pred:name ?songName ;
                    pred:popularity ?popularity .
            }
            ORDER BY DESC(?popularity)
            LIMIT 10
        """)
        ctx['top_songs'] = [
            {
                'uri': _val(row, 'song'),
                'name': _val(row, 'songName'),
                'popularity': _safe_float(_val(row, 'popularity')),
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

    top_metric = top_metric if top_metric in ('energy', 'danceability', 'valence') else ''
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
        {filters_block}
    }}
    """

    query = f"""
    SELECT ?song ?songname ?mainArtist ?artistname ?genre ?popularity ?energy ?danceability ?valence
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
            'popularity_min': popularity_min, 'popularity_max': popularity_max,
            'top_metric': top_metric,
            'page': 1,
            'has_previous': False,
            'has_next': False,
            'total_count': 0,
        })

    # Deduplicate by URI (a song can appear multiple times if it has multiple genres)
    seen = set()
    results = []
    for r in bindings:
        uri = _val(r, 'song')
        if uri not in seen:
            seen.add(uri)
            results.append({
                'uri': uri,
                'name': _val(r, 'songname'),
                'artist_uri': _val(r, 'mainArtist'),
                'artist': _clean_artist_label(_val(r, 'artistname')),
                'genre': _val(r, 'genre', '-'),
                'popularity': _safe_float(_val(r, 'popularity', '-')),
                'energy': _safe_float(_val(r, 'energy', '-')),
                'danceability': _safe_float(_val(r, 'danceability', '-')),
                'valence': _safe_float(_val(r, 'valence', '-')),
            })

    max_page = max(1, (total_count + page_size - 1) // page_size)
    page = min(page, max_page)
    has_previous = page > 1
    has_next = page < max_page

    return render(request, 'songs.html', {
        'songs': results,
        'song_query': song_query,
        'artist_query': artist_query, 'genre_query': genre_query,
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
                   ?genre ?popularity ?energy ?danceability ?tempo ?valence
                   ?loudness ?speechiness ?acousticness ?instrumentalness
                   ?liveness ?duration ?explicit ?albumName
            WHERE {{
              BIND(<{uri}> AS ?song)
              ?song pred:name ?songName ;
                    pred:mainArtist ?mainArtist .
              ?mainArtist pred:name ?mainArtistName .
              OPTIONAL {{ ?song pred:featuredArtist ?featuredArtist .
                          ?featuredArtist pred:name ?featuredArtistName . }}
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

        # Collect multi-value fields
        genres = list({_val(r, 'genre') for r in bindings if r.get('genre')})
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
            'name': _val(row0, 'songName'),
            'main_artist_uri': _val(row0, 'mainArtist'),
            'main_artist_name': _clean_artist_label(_val(row0, 'mainArtistName')),
            'featured_artists': featured_artists,
            'genres': genres,
            'popularity': _safe_float(_val(row0, 'popularity', None)),
            'tempo': _safe_float(_val(row0, 'tempo', None), 1),
            'duration_min': duration_min,
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
            SELECT ?artistName ?song ?songName ?genre ?popularity ?energy ?danceability
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
            }}
            ORDER BY ?songName
        """)

        if not bindings:
            return render(request, 'artist_detail.html', {'error_message': 'Artist not found.'})

        artist_name = _clean_artist_label(_val(bindings[0], 'artistName'))
        genres = list({_val(r, 'genre') for r in bindings if r.get('genre')})

        seen_songs = set()
        songs_list = []
        for r in bindings:
            s_uri = _val(r, 'song')
            if s_uri not in seen_songs:
                seen_songs.add(s_uri)
                songs_list.append({
                    'uri': s_uri,
                    'name': _val(r, 'songName'),
                    'genre': _val(r, 'genre', None),
                    'popularity': _safe_float(_val(r, 'popularity', None)),
                    'energy': _safe_float(_val(r, 'energy', None)),
                    'danceability': _safe_float(_val(r, 'danceability', None)),
                })

        chart_bindings = run_select(f"""
            SELECT (MIN(?rank) AS ?bestRank)
            WHERE {{
              BIND(<{uri}> AS ?artist)
              ?entry a type:ChartEntry ;
                     pred:song ?song ;
                     pred:rank ?rank .
              ?song pred:mainArtist ?artist .
            }}
        """)
        best_rank = _val(chart_bindings[0], 'bestRank') if chart_bindings else '—'

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

        ctx['artist'] = {
            'name': artist_name,
            'genres': genres,
            'song_count': len(songs_list),
            'best_rank': best_rank,
            'avg_popularity': avg_pop,
            'collaborator_count': len(collaborators),
        }
        ctx['songs'] = songs_list
        ctx['collaborators'] = collaborators
        ctx['collab_graph'] = collab_graph

    except SparqlClientError as exc:
        ctx['error_message'] = str(exc)

    return render(request, 'artist_detail.html', ctx)


# ── SPARQL Operations ─────────────────────────────────────────────────────────

def operations(request):
    ctx = {}

    if request.method == 'POST':
        op = request.POST.get('operation', '')
        try:
            if op == 'add_genre':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                genre = sparql_escape_literal(request.POST.get('genre', '').strip())
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

            elif op == 'edit_popularity':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                try:
                    popularity = float(request.POST.get('popularity', ''))
                    if not (0 <= popularity <= 100):
                        raise ValueError
                except ValueError:
                    raise SparqlClientError('Invalid popularity value (must be 0–100).')
                run_update(f"""
                    DELETE {{
                      ?song pred:popularity ?old .
                    }}
                    INSERT {{
                      ?song pred:popularity {popularity} .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} ;
                            pred:popularity ?old .
                    }}
                """)
                ctx['success_message'] = 'Popularity updated successfully.'

            elif op == 'remove_featured':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                run_update(f"""
                    DELETE WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} ;
                            pred:featuredArtist ?feat .
                    }}
                """)
                ctx['success_message'] = 'Featured artists removed successfully.'

            elif op == 'add_chart_entry':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                try:
                    rank = int(request.POST.get('rank', '0'))
                    weeks = int(request.POST.get('weeks', '0'))
                    if rank < 1 or weeks < 1:
                        raise ValueError
                except ValueError:
                    raise SparqlClientError('Invalid rank or weeks (must be positive integers).')
                date = request.POST.get('date', '').strip()
                if not date or len(date) != 10:
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

            else:
                ctx['error_message'] = 'Unknown operation.'

        except SparqlClientError as exc:
            ctx['error_message'] = str(exc)

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
        SELECT ?song ?songName ?mainArtist ?artistName ?energy ?danceability ?popularity
        WHERE {
          ?song a type:Song ;
                pred:name ?songName ;
                pred:mainArtist ?mainArtist ;
                pred:energy ?energy ;
                pred:danceability ?danceability ;
                pred:popularity ?popularity .
          ?mainArtist pred:name ?artistName .
          FILTER(?energy >= 0.75 && ?danceability >= 0.75 && ?popularity < 40)
        }
        ORDER BY DESC(?energy) DESC(?danceability)
        LIMIT 30
    """, lambda r: {
        'uri': _val(r, 'song'),
        'name': _val(r, 'songName'),
        'artist_uri': _val(r, 'mainArtist'),
        'artist': _clean_artist_label(_val(r, 'artistName')),
        'energy': _safe_float(_val(r, 'energy')),
        'danceability': _safe_float(_val(r, 'danceability')),
        'popularity': _safe_float(_val(r, 'popularity')),
    })

    ctx['insights']['versatile'] = safe_query("""
        SELECT ?artist ?artistName (COUNT(DISTINCT ?genre) AS ?genreCount)
        WHERE {
          ?song a type:Song ;
                pred:mainArtist ?artist ;
                pred:genre ?genre .
          ?artist pred:name ?artistName .
        }
        GROUP BY ?artist ?artistName
        ORDER BY DESC(?genreCount)
        LIMIT 20
    """, lambda r: {
        'uri': _val(r, 'artist'),
        'name': _clean_artist_label(_val(r, 'artistName')),
        'genre_count': _val(r, 'genreCount'),
    })

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

    return render(request, 'insights.html', ctx)


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
