"""
Generate TP2 delivery artifacts:
  1) facts_only.ttl            -> instance data only (without ontology schema)
  2) integration_protege.ttl   -> ontology + facts (+ enrichment, + SPIN rules)

Usage:
    python build_delivery_files.py
    python build_delivery_files.py --no-external
    python build_delivery_files.py --no-spin
"""

from __future__ import annotations

import argparse
import os

from rdflib import Graph, Namespace
from rdflib.namespace import OWL, RDF, RDFS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MUSIC_TTL = os.path.join(BASE_DIR, "music.ttl")
ONTOLOGY_TTL = os.path.join(BASE_DIR, "ontology.ttl")
ENRICHMENT_TTL = os.path.join(BASE_DIR, "artists_external.ttl")
SPIN_TTL = os.path.join(BASE_DIR, "spin_rules.ttl")

FACTS_ONLY_TTL = os.path.join(BASE_DIR, "facts_only.ttl")
INTEGRATION_TTL = os.path.join(BASE_DIR, "integration_protege.ttl")

BASE = Namespace("http://music.org/")
PRED = Namespace("http://music.org/pred/")
TYPE = Namespace("http://music.org/type/")

SCHEMA_PREDICATES = {
    RDF.type,
    RDFS.domain,
    RDFS.range,
    RDFS.subClassOf,
    RDFS.subPropertyOf,
    RDFS.label,
    RDFS.comment,
    OWL.inverseOf,
    OWL.equivalentProperty,
    OWL.disjointWith,
}

SCHEMA_TYPES = {
    OWL.Class,
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.SymmetricProperty,
    OWL.Ontology,
}


def _is_schema_subject(subject) -> bool:
    if not hasattr(subject, "startswith"):
        return False
    s = str(subject)
    return s.startswith(str(PRED)) or s.startswith(str(TYPE)) or s == str(BASE["MusicOntology"])


def _is_schema_triple(triple, ontology_graph: Graph) -> bool:
    if triple in ontology_graph:
        return True

    s, p, o = triple
    if _is_schema_subject(s):
        if p in SCHEMA_PREDICATES:
            return True
        if p == RDF.type and o in SCHEMA_TYPES:
            return True

    return False


def build_facts_only() -> tuple[Graph, int]:
    music_graph = Graph()
    ontology_graph = Graph()

    music_graph.parse(MUSIC_TTL, format="turtle")
    ontology_graph.parse(ONTOLOGY_TTL, format="turtle")

    facts_graph = Graph()
    facts_graph.bind("music", BASE)
    facts_graph.bind("pred", PRED)
    facts_graph.bind("type", TYPE)
    facts_graph.bind("rdf", RDF)
    facts_graph.bind("rdfs", RDFS)
    facts_graph.bind("owl", OWL)

    skipped = 0
    for triple in music_graph:
        if _is_schema_triple(triple, ontology_graph):
            skipped += 1
            continue
        facts_graph.add(triple)

    facts_graph.serialize(destination=FACTS_ONLY_TTL, format="turtle")
    return facts_graph, skipped


def build_integration_graph(facts_graph: Graph, include_external: bool, include_spin: bool) -> Graph:
    integration_graph = Graph()
    integration_graph.parse(ONTOLOGY_TTL, format="turtle")

    for triple in facts_graph:
        integration_graph.add(triple)

    if include_external and os.path.exists(ENRICHMENT_TTL):
        integration_graph.parse(ENRICHMENT_TTL, format="turtle")

    if include_spin and os.path.exists(SPIN_TTL):
        integration_graph.parse(SPIN_TTL, format="turtle")

    integration_graph.serialize(destination=INTEGRATION_TTL, format="turtle")
    return integration_graph


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build TP2 delivery RDF files.")
    parser.add_argument(
        "--no-external",
        action="store_true",
        help="do not include artists_external.ttl in integration_protege.ttl",
    )
    parser.add_argument(
        "--no-spin",
        action="store_true",
        help="do not include spin_rules.ttl in integration_protege.ttl",
    )
    args = parser.parse_args(argv)

    facts_graph, skipped = build_facts_only()
    integration_graph = build_integration_graph(
        facts_graph,
        include_external=not args.no_external,
        include_spin=not args.no_spin,
    )

    print(f"facts_only.ttl generated: {len(facts_graph)} triples")
    print(f"schema triples removed from music.ttl: {skipped}")
    print(f"integration_protege.ttl generated: {len(integration_graph)} triples")


if __name__ == "__main__":
    main()
