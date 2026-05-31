# TODO — Trabalho Prático 2 (WS)

Lista exaustiva de tudo o que o enunciado ([docs/ws.tp2.pdf](ws.tp2.pdf)) pede.

**Legenda:** ✅ feito · 🟡 parcial · ❌ por fazer

---

## 1. Objetivos / funcionalidades obrigatórias

- [x] ✅ **Ontologia exaustiva do domínio** — descrever exaustivamente o domínio de
  conhecimento dos dados, **indo para além dos conceitos presentes nos dados**.
  - ✅ Ontologia base em [normalizing_data/ontology.ttl](../normalizing_data/ontology.ttl)
    (classes, subclasses, domain/range, inverse/sub/equivalent/symmetric).
  - ✅ Exaustividade reforçada com conceitos para além dos dados brutos (ex.: `type:RecordLabel`,
    `type:TimePeriod`, `type:Decade`, `type:Season`, `type:SoloArtist`, `type:BandOrGroup`,
    `pred:hasSubGenre`, `pred:signedTo`, `pred:releasedInPeriod`).
  - ✅ Anotações (`rdfs:label`, `rdfs:comment`) documentadas em classes e propriedades.

- [ ] 🟡 **Usar a ontologia junto aos dados** — classificar automaticamente o uso dos
  dados e **otimizar a pesquisa**, feito **na GraphDB E no Protégé**.
  - ✅ Classificação automática na GraphDB (via SPIN + ruleset `rdfsplus-optimized`).
  - 🟡 **Validação no Protégé preparada**: ficheiro de integração e guia explícito
    em [docs/protege_validation.md](protege_validation.md); falta registar evidências
    finais (screenshots/checklist) da execução manual.
  - ❌ **Otimizar a pesquisa** na app usando as classes inferidas (ex.: filtrar por
    `HitSong`, `TrendingArtist`, `ChartedSong`).

- [x] ✅ **Conjunto de regras de inferência** — (a) estabelecer **novas relações**
  entre entidades; (b) implementar **classificações automáticas** que os motores de
  inferência não fazem sozinhos.
  - ✅ Módulo [normalizing_data/spin_rules.py](../normalizing_data/spin_rules.py) com 7 regras:
    `ChartedSongRule`, `HitSongRule`, `HitArtistRule`, `TrendingArtistRule`
    (classificações), `LongTailSongRule` (classificação de longevidade),
    `AppearsInChartRule`, `CollaboratedWithRule` (novas relações).
  - ✅ Reforço demonstrativo via `LongTailSongRule` e queries em
    [docs/semantic_demo_queries.rq](semantic_demo_queries.rq).

- [ ] 🟡 **Complementar funcionalidades do sistema** — à custa da informação
  **inferida** e **enriquecida**.
  - ✅ Dados enriquecidos (DBpedia/Wikidata) expostos no detalhe do artista.
  - ✅ Classe inferida `LongTailSong` exposta no dashboard (card, top songs e top artists).
  - 🟡 Exposição de mais classes/relações inferidas (`HitSong`, `HitArtist`,
    `TrendingArtist`, `appearsInChart`, `collaboratedWith`) pode ser ampliada.

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
    WDQS oficial esteve em outage): **1903/2565** artistas (Wikidata 1903, DBpedia
    1758). Matching robusto: Wikidata por `rdfs:label`/`skos:altLabel` com
    desambiguação de homónimos (rdfs:label > altLabel, Wikipedia EN, MusicBrainz)
    e tipos de banda por subclasses (`P279*`); DBpedia ancorada por QID
    `owl:sameAs` excluindo lugares (`dbo:Place`).

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
- [ ] 🟡 **Protégé** (criação e validação da ontologia)
  - ✅ Guia e workflow de validação explícitos em [docs/protege_validation.md](protege_validation.md).
  - ❌ Falta anexar evidências finais de execução manual no Protégé.
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
- [x] ✅ **Ficheiro só com os factos, sem tipologia** → para a GraphDB
  - ✅ Gerado em [normalizing_data/facts_only.ttl](../normalizing_data/facts_only.ttl)
    via [normalizing_data/build_delivery_files.py](../normalizing_data/build_delivery_files.py).
- [x] ✅ **Ficheiro só com a ontologia** → para a GraphDB —
  [normalizing_data/ontology.ttl](../normalizing_data/ontology.ttl)
  - ⚠️ Confirmar que está completo e carregável isoladamente.
- [x] ✅ **Ficheiro de integração ontologia + factos** → para validar no **Protégé**
  - ✅ Gerado em [normalizing_data/integration_protege.ttl](../normalizing_data/integration_protege.ttl)
    via [normalizing_data/build_delivery_files.py](../normalizing_data/build_delivery_files.py).
  - 🟡 Execução manual no Protégé pendente de evidências finais (ver guia).
- [x] ✅ **Regras SPIN num módulo python independente**, explicitamente identificadas —
  [normalizing_data/spin_rules.py](../normalizing_data/spin_rules.py)
- [ ] 🟡 Tudo **facilmente configurável e executável** em python3, GraphDB **e
  Protégé**, em qualquer máquina
  - ✅ `setup.sh` (python3 + GraphDB).
  - ✅ Instruções de Protégé (ficheiro, reasoner, validação) em
    [docs/protege_validation.md](protege_validation.md).
- [x] ✅ **Sem containers/Docker**

---

## 5. Relatório — 9 secções, pela ordem

> O relatório tem importância **vital** na avaliação.

- [x] ✅ 1. Introdução ao tema
- [x] ✅ 2. Definição da ontologia (RDFS e OWL)
- [x] ✅ 3. Conjunto de inferências (SPIN)
- [x] ✅ 4. Novas operações sobre os dados (SPARQL)
- [x] ✅ 5. Uso e integração de dados da Wikidata e/ou DBpedia
- [x] ✅ 6. Publicação de dados semânticos via RDFa e micro-formatos (estado atual e plano)
- [x] ✅ 7. Funcionalidades da aplicação (UI) **não presentes no TP1 ou complementares**
- [x] ✅ 8. Conclusões
- [x] ✅ 9. Configuração para executar a aplicação

> Rascunho estruturado já criado em [docs/RELATORIO_TP2.md](RELATORIO_TP2.md).

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
2. 🟡 **Protégé** — falta concluir validação manual e recolher evidências
3. 🟡 **Expor na UI** mais classes/relações inferidas (além de LongTailSong)
4. 🟡 **Relatório** — converter rascunho final para versão de entrega (PDF)
5. 🟡 Confirmar cobertura final de enriquecimento DBpedia/Wikidata para apresentação
