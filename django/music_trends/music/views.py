from django.shortcuts import render
from django.http import HttpResponse
import requests
from django.http import JsonResponse

# Create your views here.

# tá hardcoded tbm mas fonixxxx, o mm para os prefixos do SPARQL
GRAPHDB_ENDPOINT = "http://localhost:7200/repositories/music"

def songs(request):
    query = """
    PREFIX pred: <http://music.org/pred/>
    PREFIX type: <http://music.org/type/>

    SELECT ?songname ?artistname
    WHERE {
        ?song a type:Song ;
        pred:name ?songname ;
        pred:mainArtist ?artist .

        ?artist pred:name ?artistname .
    }
    LIMIT 20
    """

    response = requests.post(
        GRAPHDB_ENDPOINT,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"}
    )

    data = response.json()
    results = [
        {
            "name": r["songname"]["value"],
            "artist": r["artistname"]["value"]
        }
        for r in data["results"]["bindings"]
    ]
    return render(request, 'songs.html', {'songs': results})

def home(request):
    return HttpResponse("Welcome to Music App")

