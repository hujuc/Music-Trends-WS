import hashlib
from collections import Counter
from datetime import datetime

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


def _valid_music_uri(uri):
    return isinstance(uri, str) and uri.startswith('http://music.org/')


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
            LIMIT 5
        """)
        ctx['top_artists'] = [
            {
                'uri': _val(row, 'artist'),
                'name': _val(row, 'artistName'),
                'entries': _val(row, 'entries'),
            }
            for row in r
        ]

        r = run_select("""
            SELECT ?song ?songName (MIN(?rank) AS ?bestRank)
            WHERE {
              ?entry a type:ChartEntry ;
                     pred:song ?song ;
                     pred:rank ?rank .
              ?song a type:Song ;
                    pred:name ?songName .
            }
            GROUP BY ?song ?songName
            ORDER BY ?bestRank
            LIMIT 5
        """)
        ctx['top_songs'] = [
            {
                'uri': _val(row, 'song'),
                'name': _val(row, 'songName'),
                'best_rank': _val(row, 'bestRank'),
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
        {filters_block}
    }}
    """

    query = f"""
    SELECT ?song ?songname ?mainArtist ?artistname ?genre ?energy ?danceability ?valence
    WHERE {{
        ?song a type:Song ;
        pred:name ?songname ;
        pred:mainArtist ?mainArtist .
        ?mainArtist pred:name ?artistname .
        OPTIONAL {{ ?song pred:genre ?genre . }}
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
        total_count = int(_val(count_bindings[0], 'count', '0')) if count_bindings else 0
        bindings = run_select(query)
    except SparqlClientError as exc:
        return render(request, 'songs.html', {
            'songs': [], 'error_message': str(exc),
            'song_query': song_query,
            'artist_query': artist_query, 'genre_query': genre_query,
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
                'artist': _val(r, 'artistname'),
                'genre': _val(r, 'genre', '-'),
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
                 ?genre ?energy ?danceability ?tempo ?valence
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
                featured_artists.append({'uri': fa_uri, 'name': _val(r, 'featuredArtistName')})

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
            'main_artist_name': _val(row0, 'mainArtistName'),
            'featured_artists': featured_artists,
            'genres': genres,
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
                        SELECT ?artistName ?song ?songName ?genre ?energy ?danceability ?valence
            WHERE {{
              BIND(<{uri}> AS ?artist)
              ?artist pred:name ?artistName .
              ?song a type:Song ;
                    pred:mainArtist ?artist ;
                    pred:name ?songName .
              OPTIONAL {{ ?song pred:genre ?genre . }}
              OPTIONAL {{ ?song pred:energy ?energy . }}
              OPTIONAL {{ ?song pred:danceability ?danceability . }}
                            OPTIONAL {{ ?song pred:valence ?valence . }}
            }}
            ORDER BY ?songName
        """)

        if not bindings:
            return render(request, 'artist_detail.html', {'error_message': 'Artist not found.'})

        artist_name = _val(bindings[0], 'artistName')
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
                    'energy': _safe_float(_val(r, 'energy', None)),
                    'danceability': _safe_float(_val(r, 'danceability', None)),
                    'valence': _safe_float(_val(r, 'valence', None)),
                })

        chart_bindings = run_select(f"""
            SELECT (COUNT(?entry) AS ?entries) (MIN(?rank) AS ?bestRank)
            WHERE {{
              BIND(<{uri}> AS ?artist)
              ?entry a type:ChartEntry ;
                     pred:song ?song ;
                     pred:rank ?rank .
              ?song pred:mainArtist ?artist .
            }}
        """)
        chart_entries = _val(chart_bindings[0], 'entries') if chart_bindings else '—'
        best_rank = _val(chart_bindings[0], 'bestRank') if chart_bindings else '—'

        energy_values = [s['energy'] for s in songs_list if isinstance(s['energy'], float)]
        dance_values = [s['danceability'] for s in songs_list if isinstance(s['danceability'], float)]
        valence_values = [s['valence'] for s in songs_list if isinstance(s['valence'], float)]

        genre_counter = Counter()
        for song in songs_list:
            if song['genre'] and song['genre'] != '—':
                genre_counter[song['genre']] += 1

        ctx['artist'] = {
            'name': artist_name,
            'genres': genres,
            'song_count': len(songs_list),
            'chart_entries': chart_entries,
            'best_rank': best_rank,
            'avg_energy': round(sum(energy_values) / len(energy_values), 2) if energy_values else '—',
            'avg_danceability': round(sum(dance_values) / len(dance_values), 2) if dance_values else '—',
            'avg_valence': round(sum(valence_values) / len(valence_values), 2) if valence_values else '—',
            'top_genres': genre_counter.most_common(5),
        }
        ctx['songs'] = songs_list

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
        'artist_delete_name': '',
        'artist_delete_songs': [],
    }

    allowed_attributes = {
        'energy': {'predicate': 'pred:energy', 'min': 0.0, 'max': 1.0},
        'danceability': {'predicate': 'pred:danceability', 'min': 0.0, 'max': 1.0},
        'valence': {'predicate': 'pred:valence', 'min': 0.0, 'max': 1.0},
        'tempo': {'predicate': 'pred:tempo', 'min': 0.0, 'max': 300.0},
    }

    def _load_options():
        # Options for searchable dropdowns (HTML datalist) in Operations forms.
        try:
            song_rows = run_select("""
                SELECT ?songName
                       (MAX(IF(BOUND(?energy), 1, 0)) AS ?hasEnergy)
                       (MAX(IF(BOUND(?danceability), 1, 0)) AS ?hasDanceability)
                       (MAX(IF(BOUND(?valence), 1, 0)) AS ?hasValence)
                       (MAX(IF(BOUND(?tempo), 1, 0)) AS ?hasTempo)
                WHERE {
                  ?song a type:Song ;
                        pred:name ?songName .
                  OPTIONAL { ?song pred:energy ?energy }
                  OPTIONAL { ?song pred:danceability ?danceability }
                  OPTIONAL { ?song pred:valence ?valence }
                  OPTIONAL { ?song pred:tempo ?tempo }
                }
                GROUP BY ?songName
                ORDER BY ?songName
                LIMIT 5000
            """)

            song_options = []
            attr_map = {}
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
                if _val(row, 'hasTempo') == '1':
                    attrs.append('tempo')
                attr_map[song_name] = attrs

            ctx['song_options'] = song_options
            ctx['song_attribute_map'] = attr_map

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
        except (SparqlClientError, StopIteration):
            # Keep form functional even if options cannot be loaded.
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
        # Keep legacy behavior: preload options before processing POST.
        _load_options()
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

            # ── Attributes CRUD ──────────────────────────────────────────────
            elif op == 'attribute_add':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                attribute = request.POST.get('attribute', '').strip()
                attr_config = allowed_attributes.get(attribute)
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                if not attr_config:
                    raise SparqlClientError('Invalid attribute. Allowed: energy, danceability, valence, tempo.')
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

            elif op in ('edit_attribute', 'attribute_edit'):
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                attribute = request.POST.get('attribute', '').strip()
                attr_config = allowed_attributes.get(attribute)
                if not attr_config:
                    raise SparqlClientError('Invalid attribute. Allowed: energy, danceability, valence, tempo.')

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
                verify_rows = run_select(f"""
                    SELECT ?v
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} ;
                            {predicate} ?v .
                    }}
                    LIMIT 1
                """)
                if not verify_rows:
                    raise SparqlClientError(f'Failed to update {attribute}.')
                ctx['success_message'] = f'{attribute.capitalize()} updated successfully.'

            elif op == 'attribute_delete':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                attribute = request.POST.get('attribute', '').strip()
                attr_config = allowed_attributes.get(attribute)
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                if not attr_config:
                    raise SparqlClientError('Invalid attribute. Allowed: energy, danceability, valence, tempo.')
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
                if artist_name_raw not in ctx['artist_options']:
                    ctx['artist_options'].append(artist_name_raw)
                    ctx['artist_options'].sort(key=str.lower)
                ctx['success_message'] = 'Artist added successfully.'

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
                if old_name_raw in ctx['artist_options']:
                    ctx['artist_options'].remove(old_name_raw)
                if new_name_raw and new_name_raw not in ctx['artist_options']:
                    ctx['artist_options'].append(new_name_raw)
                ctx['artist_options'].sort(key=str.lower)
                ctx['success_message'] = 'Artist name updated successfully.'

            elif op in ('artist_delete', 'remove_artist'):
                artist_name = sparql_escape_literal(request.POST.get('artist_name', '').strip())
                artist_name_raw = request.POST.get('artist_name', '').strip()
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
                if artist_name_raw in ctx['artist_options']:
                    ctx['artist_options'].remove(artist_name_raw)
                if linked_song_names:
                    deleted_songs = len(linked_song_names)
                    ctx['success_message'] = f'Artist deleted successfully. Also removed {deleted_songs} linked song(s) and related chart entries.'
                    for song_name in linked_song_names:
                        if song_name in ctx['song_options']:
                            ctx['song_options'].remove(song_name)
                        ctx['song_attribute_map'].pop(song_name, None)
                else:
                    ctx['success_message'] = 'Artist deleted successfully.'

            # ── Featured Artist relation (legacy command kept) ─────────────
            elif op == 'remove_featured':
                song_name = sparql_escape_literal(request.POST.get('song_name', '').strip())
                if not _song_exists_exact(song_name):
                    raise SparqlClientError('Song not found (exact name required).')
                featured_rows = run_select(f"""
                    SELECT ?feat
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} ;
                            pred:featuredArtist ?feat .
                    }}
                    LIMIT 1
                """)
                if not featured_rows:
                    raise SparqlClientError('Song has no featured artists to remove.')
                run_update(f"""
                    DELETE {{
                      ?song pred:featuredArtist ?feat .
                    }}
                    WHERE {{
                      ?song a type:Song ;
                            pred:name {song_name} ;
                            pred:featuredArtist ?feat .
                    }}
                """)
                ctx['success_message'] = 'Featured artists removed successfully.'

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

            elif op == 'chart_edit':
                entry_uri = request.POST.get('entry_uri', '').strip()
                if not entry_uri:
                    song_name_raw = request.POST.get('song_name', '').strip()
                    current_date_raw = request.POST.get('current_date', '').strip()
                    if not song_name_raw or not current_date_raw:
                        raise SparqlClientError('Provide ChartEntry URI or Song Name + Current Date.')
                    try:
                        datetime.strptime(current_date_raw, '%Y-%m-%d')
                    except ValueError:
                        raise SparqlClientError('Invalid current date format (expected YYYY-MM-DD).')
                    song_name_lit = sparql_escape_literal(song_name_raw)
                    current_date_lit = sparql_escape_literal(current_date_raw)
                    entry_uri = _entry_uri_by_song_and_date(song_name_lit, current_date_lit)
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
                ctx['success_message'] = 'Chart entry updated successfully (rank, weeks and date).'

            elif op == 'remove_chart_entry':
                entry_uri = request.POST.get('entry_uri', '').strip()
                if not _valid_music_uri(entry_uri):
                    raise SparqlClientError('Invalid chart entry URI.')
                run_update(f"""
                    DELETE WHERE {{
                      <{entry_uri}> ?p ?o .
                    }}
                """)
                ctx['success_message'] = 'Chart entry removed successfully.'

            elif op == 'chart_delete':
                entry_uri = request.POST.get('entry_uri', '').strip()
                if not entry_uri:
                    song_name_raw = request.POST.get('song_name', '').strip()
                    current_date_raw = request.POST.get('current_date', '').strip()
                    if not song_name_raw or not current_date_raw:
                        raise SparqlClientError('Provide ChartEntry URI or Song Name + Date.')
                    try:
                        datetime.strptime(current_date_raw, '%Y-%m-%d')
                    except ValueError:
                        raise SparqlClientError('Invalid date format (expected YYYY-MM-DD).')
                    song_name_lit = sparql_escape_literal(song_name_raw)
                    current_date_lit = sparql_escape_literal(current_date_raw)
                    entry_uri = _entry_uri_by_song_and_date(song_name_lit, current_date_lit)
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

            elif op == 'run_validation':
                validation_type = request.POST.get('validation_type', '').strip()
                validation_results = []
                validation_columns = []

                if validation_type == 'base_list':
                    query = """
                        SELECT ?song ?songName ?artistName
                        WHERE {
                          ?song a type:Song ;
                                pred:name ?songName ;
                                pred:mainArtist ?artist .
                          ?artist pred:name ?artistName .
                        }
                        ORDER BY ?songName
                        LIMIT 25
                    """
                    rows = run_select(query)
                    validation_columns = ['songName', 'artistName', 'song']
                    validation_results = [
                        {
                            'songName': _val(row, 'songName'),
                            'artistName': _val(row, 'artistName'),
                            'song': _val(row, 'song'),
                        }
                        for row in rows
                    ]

                elif validation_type == 'by_artist':
                    artist_name_raw = request.POST.get('artist_name', '').strip()
                    if not artist_name_raw:
                        raise SparqlClientError('Artist name is required for artist validation.')
                    artist_name = sparql_escape_literal(artist_name_raw)
                    query = f"""
                        SELECT ?songName ?genre
                        WHERE {{
                          ?song a type:Song ;
                                pred:name ?songName ;
                                pred:mainArtist ?artist .
                          ?artist pred:name ?artistName .
                          OPTIONAL {{ ?song pred:genre ?genre . }}
                          FILTER(CONTAINS(LCASE(STR(?artistName)), LCASE(STR({artist_name}))))
                        }}
                        ORDER BY ?songName
                        LIMIT 25
                    """
                    rows = run_select(query)
                    validation_columns = ['songName', 'genre']
                    validation_results = [
                        {'songName': _val(row, 'songName'), 'genre': _val(row, 'genre', '—')}
                        for row in rows
                    ]

                elif validation_type == 'by_genre':
                    genre_raw = request.POST.get('genre', '').strip()
                    if not genre_raw:
                        raise SparqlClientError('Genre is required for genre validation.')
                    genre = sparql_escape_literal(genre_raw)
                    query = f"""
                        SELECT ?songName ?artistName ?energy ?danceability
                        WHERE {{
                          ?song a type:Song ;
                                pred:name ?songName ;
                                pred:mainArtist ?artist ;
                                pred:genre ?genreValue .
                          ?artist pred:name ?artistName .
                          OPTIONAL {{ ?song pred:energy ?energy . }}
                          OPTIONAL {{ ?song pred:danceability ?danceability . }}
                          FILTER(CONTAINS(LCASE(STR(?genreValue)), LCASE(STR({genre}))))
                        }}
                        ORDER BY ?songName
                        LIMIT 25
                    """
                    rows = run_select(query)
                    validation_columns = ['songName', 'artistName', 'energy', 'danceability']
                    validation_results = [
                        {
                            'songName': _val(row, 'songName'),
                            'artistName': _val(row, 'artistName'),
                            'energy': _safe_float(_val(row, 'energy', '—')),
                            'danceability': _safe_float(_val(row, 'danceability', '—')),
                        }
                        for row in rows
                    ]
                else:
                    raise SparqlClientError('Unknown validation query type.')

                ctx['validation_type'] = validation_type
                ctx['validation_columns'] = validation_columns
                ctx['validation_results'] = validation_results
                ctx['validation_rows'] = [
                    [row.get(col, '—') for col in validation_columns]
                    for row in validation_results
                ]
                ctx['success_message'] = f'Validation query executed: {validation_type}.'

            else:
                ctx['error_message'] = 'Unknown operation.'

        except SparqlClientError as exc:
            ctx['error_message'] = str(exc)

    else:
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
        'artist': _val(r, 'artistName'),
        'score': _safe_float(_val(r, 'partyScore')),
    })

    ctx['insights']['hidden_gems'] = safe_query("""
                SELECT ?song ?songName ?mainArtist ?artistName ?energy ?danceability (COUNT(?entry) AS ?chartCount)
        WHERE {
          ?song a type:Song ;
                pred:name ?songName ;
                pred:mainArtist ?mainArtist ;
                pred:energy ?energy ;
                                pred:danceability ?danceability .
          ?mainArtist pred:name ?artistName .
                    OPTIONAL {
                        ?entry a type:ChartEntry ;
                                     pred:song ?song .
                    }
                    FILTER(?energy >= 0.75 && ?danceability >= 0.75)
        }
                GROUP BY ?song ?songName ?mainArtist ?artistName ?energy ?danceability
                HAVING(COUNT(?entry) <= 2)
                ORDER BY ASC(COUNT(?entry)) DESC(?energy) DESC(?danceability)
        LIMIT 30
    """, lambda r: {
        'uri': _val(r, 'song'),
        'name': _val(r, 'songName'),
        'artist_uri': _val(r, 'mainArtist'),
        'artist': _val(r, 'artistName'),
        'energy': _safe_float(_val(r, 'energy')),
        'danceability': _safe_float(_val(r, 'danceability')),
                'chart_count': _val(r, 'chartCount'),
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
        'name': _val(r, 'artistName'),
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

    return render(request, 'insights.html', ctx)


# ── About Data ────────────────────────────────────────────────────────────────

def about_data(request):
    return render(request, 'about_data.html', {})
