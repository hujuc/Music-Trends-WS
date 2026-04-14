# Operacoes SPARQL Recomendadas (validadas para este dataset)

Este documento lista operacoes SPARQL importantes, mais criativas e interessantes, com foco total no que **existe de facto** no dataset atual.

## 1) Validacao do esquema existente

Verificado diretamente em `normalizing_data/music.ttl`:

Classes existentes:
- `type:Song`
- `type:Artist`
- `type:ChartEntry`

Predicados existentes:
- `pred:name`
- `pred:mainArtist`
- `pred:featuredArtist`
- `pred:song`
- `pred:rank`
- `pred:weeks`
- `pred:date`
- `pred:genre`
- `pred:popularity`
- `pred:energy`
- `pred:danceability`
- `pred:tempo`
- `pred:valence`
- `pred:loudness`
- `pred:speechiness`
- `pred:acousticness`
- `pred:instrumentalness`
- `pred:liveness`
- `pred:duration_ms`
- `pred:explicit`
- `pred:albumName`

> Nota: estas queries evitam predicados/tipos que nao existem no RDF atual.

## 2) Prefixes base

```sparql
PREFIX pred: <http://music.org/pred/>
PREFIX type: <http://music.org/type/>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
```

## 3) Operacoes essenciais (SELECT)

### 3.1 Lista base de musicas + artista
```sparql
SELECT ?song ?songName ?artistName
WHERE {
  ?song a type:Song ;
        pred:name ?songName ;
        pred:mainArtist ?artist .
  ?artist pred:name ?artistName .
}
LIMIT 50
```

### 3.2 Pesquisa por artista (contains, case-insensitive)
```sparql
SELECT ?songName ?artistName
WHERE {
  ?song a type:Song ;
        pred:name ?songName ;
        pred:mainArtist ?artist .
  ?artist pred:name ?artistName .
  FILTER(CONTAINS(LCASE(STR(?artistName)), LCASE("drake")))
}
LIMIT 50
```

### 3.3 Pesquisa por genero + intervalo de popularidade
```sparql
SELECT ?songName ?genre ?popularity
WHERE {
  ?song a type:Song ;
        pred:name ?songName ;
        pred:genre ?genre ;
        pred:popularity ?popularity .
  FILTER(CONTAINS(LCASE(STR(?genre)), LCASE("pop")))
  FILTER(?popularity >= 60 && ?popularity <= 90)
}
ORDER BY DESC(?popularity)
LIMIT 50
```

### 3.4 Top songs por energy ou danceability
```sparql
SELECT ?songName ?artistName ?energy ?danceability
WHERE {
  ?song a type:Song ;
        pred:name ?songName ;
        pred:mainArtist ?artist ;
        pred:energy ?energy ;
        pred:danceability ?danceability .
  ?artist pred:name ?artistName .
}
ORDER BY DESC(?energy) DESC(?danceability)
LIMIT 20
```

### 3.5 Top artistas por numero de entradas em chart
```sparql
SELECT ?artistName (COUNT(?entry) AS ?entries)
WHERE {
  ?entry a type:ChartEntry ;
         pred:song ?song .
  ?song pred:mainArtist ?artist .
  ?artist pred:name ?artistName .
}
GROUP BY ?artistName
ORDER BY DESC(?entries)
LIMIT 20
```

### 3.6 Melhor rank e semanas por musica
```sparql
SELECT ?songName (MIN(?rank) AS ?bestRank) (MAX(?weeks) AS ?maxWeeks)
WHERE {
  ?entry a type:ChartEntry ;
         pred:song ?song ;
         pred:rank ?rank ;
         pred:weeks ?weeks .
  ?song pred:name ?songName .
}
GROUP BY ?songName
ORDER BY ?bestRank DESC(?maxWeeks)
LIMIT 50
```

## 4) Operacoes obrigatorias de alteracao (UPDATE)

### 4.1 INSERT: adicionar genero alternativo a uma musica
```sparql
INSERT {
  ?song pred:genre "alt-pop" .
}
WHERE {
  ?song a type:Song ;
        pred:name "Blinding Lights" .
}
```

### 4.2 DELETE/INSERT: corrigir popularidade
```sparql
DELETE {
  ?song pred:popularity ?oldPopularity .
}
INSERT {
  ?song pred:popularity 88.0 .
}
WHERE {
  ?song a type:Song ;
        pred:name "Blinding Lights" ;
        pred:popularity ?oldPopularity .
}
```

### 4.3 DELETE WHERE: remover relacao de featured artist
```sparql
DELETE WHERE {
  ?song a type:Song ;
        pred:name "Old Town Road" ;
        pred:featuredArtist ?feat .
}
```

### 4.4 INSERT: adicionar nova entrada de chart para musica existente
```sparql
INSERT {
  <http://music.org/entry/manual-2026-04-13-blinding-lights> a type:ChartEntry ;
    pred:song ?song ;
    pred:rank 10 ;
    pred:weeks 120 ;
    pred:date "2026-04-13" .
}
WHERE {
  ?song a type:Song ;
        pred:name "Blinding Lights" .
}
```

### 4.5 DELETE WHERE: remover entrada de chart por URI conhecida
```sparql
DELETE WHERE {
  <http://music.org/entry/manual-2026-04-13-blinding-lights> ?p ?o .
}
```

## 5) Operacoes mais criativas e interessantes (SELECT)

### 5.1 Festa score (energia + dancabilidade + valencia)
```sparql
SELECT ?songName ?artistName ?partyScore
WHERE {
  ?song a type:Song ;
        pred:name ?songName ;
        pred:mainArtist ?artist ;
        pred:energy ?energy ;
        pred:danceability ?danceability ;
        pred:valence ?valence .
  ?artist pred:name ?artistName .
  BIND((?energy + ?danceability + ?valence) / 3 AS ?partyScore)
}
ORDER BY DESC(?partyScore)
LIMIT 25
```

### 5.2 Hidden gems: alta danceability/energy, baixa popularidade
```sparql
SELECT ?songName ?artistName ?energy ?danceability ?popularity
WHERE {
  ?song a type:Song ;
        pred:name ?songName ;
        pred:mainArtist ?artist ;
        pred:energy ?energy ;
        pred:danceability ?danceability ;
        pred:popularity ?popularity .
  ?artist pred:name ?artistName .
  FILTER(?energy >= 0.75 && ?danceability >= 0.75 && ?popularity < 40)
}
ORDER BY DESC(?energy) DESC(?danceability)
LIMIT 30
```

### 5.3 Artistas mais versateis por numero de generos
```sparql
SELECT ?artistName (COUNT(DISTINCT ?genre) AS ?genreCount)
WHERE {
  ?song a type:Song ;
        pred:mainArtist ?artist ;
        pred:genre ?genre .
  ?artist pred:name ?artistName .
}
GROUP BY ?artistName
ORDER BY DESC(?genreCount)
LIMIT 20
```

### 5.4 Musicas mais resilientes (muitas semanas + bom melhor rank)
```sparql
SELECT ?songName (MAX(?weeks) AS ?weeksPeak) (MIN(?rank) AS ?bestRank)
WHERE {
  ?entry a type:ChartEntry ;
         pred:song ?song ;
         pred:weeks ?weeks ;
         pred:rank ?rank .
  ?song pred:name ?songName .
}
GROUP BY ?songName
ORDER BY DESC(?weeksPeak) ?bestRank
LIMIT 30
```

### 5.5 Sazonalidade por mes (baseado em pred:date como string YYYY-MM-DD)
```sparql
SELECT ?month (COUNT(?entry) AS ?entries)
WHERE {
  ?entry a type:ChartEntry ;
         pred:date ?date .
  BIND(SUBSTR(STR(?date), 6, 2) AS ?month)
}
GROUP BY ?month
ORDER BY ?month
```

## 6) Boas praticas para a app Django

- Sanitizar sempre inputs de texto antes de interpolar em FILTER.
- Validar campos numericos (`popularity`, `rank`, `weeks`) no backend.
- Em updates destrutivos, preferir primeiro um SELECT de preview.
- Guardar em log interno: query executada, timestamp, utilizador (se houver auth).

## 7) Prioridade de implementacao sugerida

1. SELECTs essenciais: 3.2, 3.3, 3.4
2. UPDATEs obrigatorios: 4.1, 4.2, 4.3
3. Queries criativas para demo: 5.1, 5.2, 5.4
