from django.shortcuts import render
from django.http import HttpResponse

from .sparql_client import SparqlClientError, run_select, sparql_escape_literal

# Create your views here.

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

    top_metric_map = {
        'energy': 'energy',
        'danceability': 'danceability',
    }
    top_metric = top_metric_map.get(top_metric, '')

    order_clause = ''
    if top_metric:
        order_clause = f'ORDER BY DESC(?{top_metric})'

    filters_block = "\n        ".join(filters)

    query = f"""
    SELECT ?songname ?artistname ?genre ?popularity ?energy ?danceability
    WHERE {{
        ?song a type:Song ;
        pred:name ?songname ;
        pred:mainArtist ?artist .

        ?artist pred:name ?artistname .
        OPTIONAL {{ ?song pred:genre ?genre . }}
        OPTIONAL {{ ?song pred:popularity ?popularity . }}
        OPTIONAL {{ ?song pred:energy ?energy . }}
        OPTIONAL {{ ?song pred:danceability ?danceability . }}
        {filters_block}
    }}
    {order_clause}
    LIMIT 20
    """

    try:
        bindings = run_select(query)
    except SparqlClientError as exc:
        return render(
            request,
            'songs.html',
            {
                'songs': [],
                'error_message': str(exc),
                'artist_query': artist_query,
                'genre_query': genre_query,
                'popularity_min': popularity_min,
                'popularity_max': popularity_max,
                'top_metric': top_metric,
            },
        )

    results = [
        {
            'name': r['songname']['value'],
            'artist': r['artistname']['value'],
            'genre': r.get('genre', {}).get('value', '-'),
            'popularity': r.get('popularity', {}).get('value', '-'),
            'energy': r.get('energy', {}).get('value', '-'),
            'danceability': r.get('danceability', {}).get('value', '-'),
        }
        for r in bindings
    ]
    return render(
        request,
        'songs.html',
        {
            'songs': results,
            'artist_query': artist_query,
            'genre_query': genre_query,
            'popularity_min': popularity_min,
            'popularity_max': popularity_max,
            'top_metric': top_metric,
        },
    )

def home(request):
    return HttpResponse("Welcome to Music App")

