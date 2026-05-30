# TODO — Trabalho Prático 2 (WS)

Lista exaustiva de tudo o que o enunciado ([docs/ws.tp2.pdf](ws.tp2.pdf)) pede.

**Legenda:** ✅ feito · 🟡 parcial · ❌ por fazer

---

## 1. Objetivos / funcionalidades obrigatórias

- [ ] 🟡 **Ontologia exaustiva do domínio** — descrever exaustivamente o domínio de
  conhecimento dos dados, **indo para além dos conceitos presentes nos dados**.
  - ✅ Ontologia base em [normalizing_data/ontology.ttl](../normalizing_data/ontology.ttl)
    (classes, subclasses, domain/range, inverse/sub/equivalent/symmetric).
  - ❌ Rever exaustividade: garantir conceitos para **além** dos dados (ex.: géneros
    como hierarquia, álbuns, editoras/labels, países, períodos temporais, etc.).
  - ❌ Documentar anotações (`rdfs:label`, `rdfs:comment`) em classes e propriedades.

- [ ] 🟡 **Usar a ontologia junto aos dados** — classificar automaticamente o uso dos
  dados e **otimizar a pesquisa**, feito **na GraphDB E no Protégé**.
  - ✅ Classificação automática na GraphDB (via SPIN + ruleset `rdfsplus-optimized`).
  - ❌ **Validar a classificação/inferência no Protégé** (abrir o ficheiro de
    integração, correr reasoner).
  - ❌ **Otimizar a pesquisa** na app usando as classes inferidas (ex.: filtrar por
    `HitSong`, `TrendingArtist`, `ChartedSong`).

- [x] ✅ **Conjunto de regras de inferência** — (a) estabelecer **novas relações**
  entre entidades; (b) implementar **classificações automáticas** que os motores de
  inferência não fazem sozinhos.
  - ✅ Módulo [normalizing_data/spin_rules.py](../normalizing_data/spin_rules.py) com 6 regras:
    `ChartedSongRule`, `HitSongRule`, `HitArtistRule`, `TrendingArtistRule`
    (classificações), `AppearsInChartRule`, `CollaboratedWithRule` (novas relações).
  - ⚠️ Rever se se justificam **mais** regras para enriquecer a demonstração.

- [ ] 🟡 **Complementar funcionalidades do sistema** — à custa da informação
  **inferida** e **enriquecida**.
  - ✅ Dados enriquecidos (DBpedia/Wikidata) expostos no detalhe do artista.
  - ❌ Expor na UI as classes/relações inferidas (HitSong, HitArtist,
    TrendingArtist, appearsInChart, collaboratedWith) — ainda não aparecem.

- [x] ✅ **Complementar os dados via DBpedia + Wikidata** — acesso programático ao
  endpoint SPARQL de **ambas** com SPARQLwrapper.
  - ✅ `SPARQLWrapper` no `requirements.txt`.
  - ✅ Módulo [normalizing_data/enrich_artists.py](../normalizing_data/enrich_artists.py):
    artistas → país, género, imagem, datas, website, MusicBrainz, descrição
    (Wikidata) + thumbnail, local de nascimento, abstract (DBpedia) + `owl:sameAs`.
  - ✅ Resultado em `artists_external.ttl`; integra na GraphDB via `--apply`.
  - ✅ Exposto na UI: cartão "About" no detalhe do artista (foto, país, datas,
    géneros, descrição, links Wikidata/DBpedia/site/MusicBrainz).
  - ✅ Enriquecimento corrido para todos os artistas (via mirror QLever quando o
    WDQS oficial esteve em outage): **1692/2565** artistas (Wikidata 1692, DBpedia
    1536), ancorado por QID `owl:sameAs` (sem falsos positivos por homónimos).

- [ ] ❌ **Publicar a semântica nas páginas web** — RDFa e micro-formatos nas próprias
  páginas do SI.
  - ❌ Anotar templates (ex.: `song_detail`, `artist_detail`) com RDFa
    (`vocab`/`typeof`/`property`) e/ou micro-formatos.

---

## 2. Tecnologias obrigatórias

- [x] ✅ Python/Django (programação da aplicação)
- [x] ✅ GraphDB (repositório de dados)
- [x] ✅ SPARQL — **pesquisa E alteração** dos dados (SELECT + UPDATE/CRUD)
- [x] ✅ RDF (formato dos dados)
- [x] ✅ RDFS e OWL (ontologia)
- [ ] ❌ **Protégé** (criação e validação da ontologia) — falta usar/validar
- [x] ✅ SPIN (conjunto de inferências)
- [x] ✅ **SPARQLwrapper** (acesso a DBpedia e Wikidata) — `enrich_artists.py`
- [ ] ❌ **RDFa e micro-formatos** (publicação da semântica) — falta usar

---

## 3. Itens valorizados / opcionais

- [ ] ⭐ Maior nível de **exploração** das tecnologias mencionadas
- [ ] ⭐ Maior nível de **inter-relação** entre as tecnologias
- [ ] ⭐ Interfaces de utilizador **mais funcionais e amigáveis**

---

## 4. Entrega — componentes obrigatórios

- [x] ✅ Projeto Web Python/Django para **venv python3**, requisitos via **um único
  `requirements.txt`** (sem outros formatos)
- [ ] ❌ **Ficheiro só com os factos, sem tipologia** → para a GraphDB
  - ⚠️ Atualmente `music.ttl` inclui o esquema da ontologia; é preciso emitir um
    ficheiro **só de factos** (sem definições de classes/propriedades).
- [x] ✅ **Ficheiro só com a ontologia** → para a GraphDB —
  [normalizing_data/ontology.ttl](../normalizing_data/ontology.ttl)
  - ⚠️ Confirmar que está completo e carregável isoladamente.
- [ ] 🟡 **Ficheiro de integração ontologia + factos** → para validar no **Protégé**
  - ⚠️ `music.ttl` (factos + esquema) serve de base, mas falta **validar no Protégé**
    e confirmar que abre/valida sem erros.
- [x] ✅ **Regras SPIN num módulo python independente**, explicitamente identificadas —
  [normalizing_data/spin_rules.py](../normalizing_data/spin_rules.py)
- [ ] 🟡 Tudo **facilmente configurável e executável** em python3, GraphDB **e
  Protégé**, em qualquer máquina
  - ✅ `setup.sh` (python3 + GraphDB).
  - ❌ Instruções de Protégé (que ficheiro abrir, como correr o reasoner).
- [x] ✅ **Sem containers/Docker**

---

## 5. Relatório — 9 secções, pela ordem

> O relatório tem importância **vital** na avaliação.

- [ ] ❌ 1. Introdução ao tema
- [ ] ❌ 2. Definição da ontologia (RDFS e OWL)
- [ ] ❌ 3. Conjunto de inferências (SPIN)
- [ ] ❌ 4. Novas operações sobre os dados (SPARQL)
- [ ] ❌ 5. Uso e integração de dados da Wikidata e/ou DBpedia
- [ ] ❌ 6. Publicação de dados semânticos via RDFa e micro-formatos
- [ ] ❌ 7. Funcionalidades da aplicação (UI) **não presentes no TP1 ou complementares**
- [ ] ❌ 8. Conclusões
- [ ] ❌ 9. Configuração para executar a aplicação

> Nota: existe [docs/WS RELATORIO.pdf](WS%20RELATORIO.pdf) — confirmar se é do TP1
> ou já o do TP2; reestruturar para estas 9 secções e esta ordem.

---

## 6. Apresentação (carry-over do TP1)

> O enunciado do TP2 não a menciona explicitamente, mas o TP1 exige-a. Confirmar com
> o docente.

- [ ] Introdução ao tema
- [ ] Demonstração de **todas** as funcionalidades
- [ ] **Todos** os membros do grupo participam

---

## Resumo do que falta (prioridades)

1. ❌ **RDFa/micro-formatos** nas páginas (objetivo + tecnologia + relatório §6)
2. ❌ **Protégé** — validar ontologia/inferência + ficheiro de integração + instruções
3. ❌ **Ficheiro só de factos** (sem tipologia) para a entrega
4. ❌ **Expor na UI** a informação inferida + enriquecida (complementar funcionalidades)
5. ❌ **Relatório** completo (9 secções)
6. 🟡 Rever **exaustividade da ontologia** (ir além dos dados)
7. 🟡 Correr **enriquecimento completo** DBpedia/Wikidata (cobertura total)
