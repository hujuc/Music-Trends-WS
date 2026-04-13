import hashlib

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
            LIMIT 10
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
    artist_query = request.GET.get('artist', '').strip()
    genre_query = request.GET.get('genre', '').strip()
    popularity_min = request.GET.get('popularity_min', '').strip()
    popularity_max = request.GET.get('popularity_max', '').strip()
    top_metric = request.GET.get('top_metric', '').strip()

    filters = []

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

    top_metric = top_metric if top_metric in ('energy', 'danceability', 'popularity') else ''
    order_clause = f'ORDER BY DESC(?{top_metric})' if top_metric else ''
    filters_block = "\n        ".join(filters)

    query = f"""
    SELECT ?song ?songname ?mainArtist ?artistname ?genre ?popularity ?energy ?danceability
    WHERE {{
        ?song a type:Song ;
        pred:name ?songname ;
        pred:mainArtist ?mainArtist .
        ?mainArtist pred:name ?artistname .
        OPTIONAL {{ ?song pred:genre ?genre . }}
        OPTIONAL {{ ?song pred:popularity ?popularity . }}
        OPTIONAL {{ ?song pred:energy ?energy . }}
        OPTIONAL {{ ?song pred:danceability ?danceability . }}
        {filters_block}
    }}
    {order_clause}
    LIMIT 50
    """

    try:
        bindings = run_select(query)
    except SparqlClientError as exc:
        return render(request, 'songs.html', {
            'songs': [], 'error_message': str(exc),
            'artist_query': artist_query, 'genre_query': genre_query,
            'popularity_min': popularity_min, 'popularity_max': popularity_max,
            'top_metric': top_metric,
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
                'popularity': _safe_float(_val(r, 'popularity', '-')),
                'energy': _safe_float(_val(r, 'energy', '-')),
                'danceability': _safe_float(_val(r, 'danceability', '-')),
            })

    return render(request, 'songs.html', {
        'songs': results,
        'artist_query': artist_query, 'genre_query': genre_query,
        'popularity_min': popularity_min, 'popularity_max': popularity_max,
        'top_metric': top_metric,
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

        pop_values = [s['popularity'] for s in songs_list if isinstance(s['popularity'], float)]
        avg_pop = round(sum(pop_values) / len(pop_values), 1) if pop_values else '—'

        ctx['artist'] = {
            'name': artist_name,
            'genres': genres,
            'song_count': len(songs_list),
            'best_rank': best_rank,
            'avg_popularity': avg_pop,
        }
        ctx['songs'] = songs_list

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
        'artist': _val(r, 'artistName'),
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
        'artist': _val(r, 'artistName'),
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
