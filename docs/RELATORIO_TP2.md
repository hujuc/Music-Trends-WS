# Relatorio TP2 - Music Trends WS

## 1. Introducao ao tema

O projeto Music Trends WS explora tendencias musicais com base em dados de charts,
modelados em RDF e enriquecidos semanticamente. O objetivo principal e transformar
um conjunto de dados tabular num sistema de conhecimento com ontologia explicita,
inferencias, e funcionalidades de pesquisa/analise com SPARQL.

A aplicacao Django atua como interface do sistema de informacao, enquanto a
GraphDB funciona como repositorio semantico para consulta e materializacao de
conhecimento derivado.

## 2. Definicao da ontologia (RDFS e OWL)

A ontologia foi definida em `normalizing_data/ontology.ttl` com classes centrais
(`type:Song`, `type:Artist`, `type:ChartEntry`, `type:Chart`, `type:Genre`,
`type:Album`, `type:Country`) e propriedades de ligacao entre entidades e medidas
analiticas (`pred:rank`, `pred:weeks`, `pred:date`, `pred:popularity`, etc.).

Foram usados mecanismos OWL/RDFS como:

- `rdfs:subClassOf` para hierarquias conceptuais;
- `owl:inverseOf` para navegacao bidirecional entre entidades;
- `rdfs:subPropertyOf` e `owl:equivalentProperty` para compatibilidade semantica;
- `owl:SymmetricProperty` para colaboracoes entre artistas.

Para aumentar a exaustividade para alem dos dados brutos, foram adicionados
conceitos de analise temporal e de industria musical, por exemplo:
`type:TimePeriod`, `type:Decade`, `type:Season`, `type:RecordLabel`,
`type:SoloArtist`, `type:BandOrGroup`, e propriedades associadas.

A ontologia inclui anotacoes (`rdfs:label`, `rdfs:comment`) nas classes e
propriedades para melhorar legibilidade, manutencao e validacao em ferramentas
como Protégé.

## 3. Conjunto de inferencias (SPIN)

As inferencias foram implementadas de forma independente em
`normalizing_data/spin_rules.py`, conforme exigido no enunciado.

Regras implementadas:

- `ChartedSongRule` -> classifica musicas presentes em charts;
- `HitSongRule` -> classifica musicas com rank <= 10;
- `LongTailSongRule` -> classifica musicas com longevidade (`MAX(weeks) >= 20`);
- `HitArtistRule` -> classifica artistas com hit songs;
- `TrendingArtistRule` -> classifica artistas com top 10 recente;
- `AppearsInChartRule` -> cria relacao artista -> chart;
- `CollaboratedWithRule` -> cria relacao simetrica de colaboracao.

Estas regras complementam o que o motor RDFS/OWL nao deriva sozinho, por
exigirem filtros numericos, comparacoes temporais e agregacao.

## 4. Novas operacoes sobre os dados (SPARQL)

O sistema inclui operacoes de leitura (SELECT) e alteracao/materializacao
(UPDATE via SPIN) sobre a GraphDB.

Exemplos de operacoes novas:

- contagem de classes inferidas (`type:HitSong`, `type:LongTailSong`);
- tabelas de analise no dashboard (longest charting songs, long-tail por artista);
- consolidacao de enriquecimento externo no detalhe de artista;
- materializacao programatica das regras SPIN com `spin_rules.py --apply`.

As queries de demonstracao estao em `docs/semantic_demo_queries.rq`.

## 5. Uso e integracao de dados da Wikidata e/ou DBpedia

A integracao externa foi implementada em `normalizing_data/enrich_artists.py`, com
acesso programatico aos endpoints SPARQL da Wikidata e DBpedia via
`SPARQLWrapper`.

Dados enriquecidos:

- Wikidata: pais de origem, genero externo, imagem, website, datas, MusicBrainz;
- DBpedia: thumbnail, local de nascimento e abstract textual;
- ligacoes `owl:sameAs` para rastreabilidade entre fontes.

Na UI, a pagina de artista apresenta:

- dados estruturados enriquecidos;
- biografia textual com prioridade ao `abstract` da DBpedia;
- links diretos para Wikidata, DBpedia e MusicBrainz.

## 6. Publicacao de dados semanticos via RDFa e micro-formatos

Estado atual: por implementar integralmente.

Trabalho futuro previsto:

- anotar templates principais (`artist_detail`, `song_detail`) com RDFa
  (`typeof`, `property`, `resource`);
- adicionar micro-formatos para entidades centrais (artista, musica, album).

## 7. Funcionalidades da aplicacao (UI) nao presentes no TP1 ou complementares

Foram adicionadas funcionalidades semanticas e analiticas relevantes:

- secao de Insights com metricas por pais de origem;
- drill-down por pais (`country_detail`) com top artistas e musicas;
- dashboard com metricas de `LongTailSong`;
- visualizacao de enriquecimento externo no detalhe de artista;
- rede de colaboracoes entre artistas.

Estas funcionalidades dependem diretamente de inferencias e enriquecimento,
complementando o SI alem da navegacao basica de dados.

## 8. Conclusoes

O TP2 permitiu evoluir de um modelo de dados descritivo para uma camada
semantica operacional, com ontologia explicita, inferencias materializadas e
enriquecimento por linked data. O resultado foi um sistema com melhor capacidade
de explicacao, navegacao e analise de tendencias.

O maior ganho foi combinar:

- semantica estrutural (RDFS/OWL),
- semantica derivada (SPIN),
- semantica externa (Wikidata/DBpedia),

numa experiencia coerente para o utilizador final.

## 9. Configuracao para executar a aplicacao

Requisitos:

- Python 3.10+
- GraphDB a correr em `http://localhost:7200`

Fluxo recomendado:

```bash
./setup.sh full
```

Este comando instala dependencias, gera RDF base, enriquece artistas,
carrega os dados na GraphDB, aplica regras SPIN e arranca o servidor Django.

Para artefactos de entrega TP2:

```bash
cd normalizing_data
python build_delivery_files.py
```

Gera:

- `facts_only.ttl` (factos sem tipologia)
- `integration_protege.ttl` (integracao para validacao no Protégé)

Validacao Protégé: ver `docs/protege_validation.md`.
