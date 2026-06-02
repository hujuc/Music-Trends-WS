# Protégé Validation Guide (TP2)

This guide provides an explicit validation workflow for the ontology and its
integration with facts, as required by TP2.

## 1) Generate delivery files

From repository root:

```bash
cd normalizing_data
python build_delivery_files.py
```

Artifacts generated:

- `normalizing_data/facts_only.ttl` -> instance data only (no schema/type definitions)
- `normalizing_data/integration_protege.ttl` -> ontology + facts + enrichment (+ SPIN RDF when available)

## 2) Open integration file in Protégé

1. Open Protégé.
2. `File -> Open...`
3. Select `normalizing_data/integration_protege.ttl`.
4. Confirm prefix resolution (`music`, `pred`, `type`, `spin`, `sp`).

## 3) Validate ontology consistency (reasoner)

1. Open tab `Reasoner`.
2. Start reasoner (`HermiT` or `ELK`).
3. Verify:
- Ontology is **consistent** (no inconsistency warning).
- Class hierarchy resolves correctly, including:
  - `type:HitSong rdfs:subClassOf type:ChartedSong`
  - `type:LongTailSong rdfs:subClassOf type:ChartedSong`
  - `type:HitArtist rdfs:subClassOf type:Artist`
  - `type:TrendingArtist rdfs:subClassOf type:Artist`
  - `type:Decade rdfs:subClassOf type:TimePeriod`
  - `type:Season rdfs:subClassOf type:TimePeriod`

## 4) Validate object/datatype modeling

In the Entities/Class axioms and Object/Data properties views, confirm:

- `pred:performer` inverse `pred:performed`
- `pred:song` inverse `pred:hasChartEntry`
- `pred:collaboratedWith` is symmetric
- Domain/range constraints are present for core properties
- Annotation coverage (`rdfs:label`, `rdfs:comment`) exists for classes/properties

## 5) Validate SPIN rule presence (structural)

`integration_protege.ttl` includes `spin_rules.ttl` when available. Confirm:

- Instances under `music:rule/*` are present
- Each rule has `sp:text`
- Rules are linked via `spin:rule` to target classes

Note: Protégé reasoners validate OWL/RDFS semantics. SPIN execution/materialization
is performed in GraphDB through `normalizing_data/spin_rules.py --apply`.

## 6) Evidence to include in report

Capture screenshots for:

1. Protégé open with `integration_protege.ttl`
2. Reasoner run with consistency status
3. Class hierarchy showing inferred/declared subclasses
4. SPIN rule resources and `sp:text` content

## 7) Quick troubleshooting

- If file is too heavy to open, test first with:
  - `ontology.ttl`
  - then `ontology.ttl + facts_only.ttl`
- If prefixes are missing, re-open with Turtle parser enabled.
- If reasoner takes long, start with ELK then HermiT.
