"""
SPIN inference rules — independent module (TP2, ponto 3 do relatorio).

As regras de inferencia estao DEFINIDAS AQUI, de forma explicita e isolada do
resto do projeto, conforme exigido no enunciado ("As regras de inferencia em
SPIN devem ser definidas num modulo python independente, por forma a serem
explicitamente identificadas").

Cada regra:
  * implementa uma classificacao automatica ou estabelece uma nova relacao que
    os motores RDFS/OWL nao conseguem inferir sozinhos (precisam de FILTER /
    comparacoes / agregacao);
  * e representada em SPIN (vocabulario sp:/spin:) e ligada a uma classe-alvo
    atraves de spin:rule, podendo ser exportada para `spin_rules.ttl` e
    carregada na GraphDB ou no Protege;
  * pode ser aplicada programaticamente a um repositorio GraphDB (materializa as
    triplas inferidas) para os casos em que o motor SPIN nao esta ativo.

Uso:
    python spin_rules.py --export                 # escreve spin_rules.ttl
    python spin_rules.py --apply                  # aplica as regras na GraphDB
    python spin_rules.py --apply --dry-run        # mostra os updates sem executar
    python spin_rules.py --endpoint http://localhost:7200/repositories/music --apply
"""

import argparse
import os
import sys

import requests
from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import RDF

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ENDPOINT = os.getenv(
    "GRAPHDB_ENDPOINT", "http://localhost:7200/repositories/music"
)
LONGTAIL_MIN_WEEKS = int(os.getenv("LONGTAIL_MIN_WEEKS", "20"))
SPIN_TTL_OUTPUT = os.path.join(BASE_DIR, "spin_rules.ttl")

# ── Namespaces ────────────────────────────────────────────────────────────────
SP = Namespace("http://spinrdf.org/sp#")
SPIN = Namespace("http://spinrdf.org/spin#")
BASE = Namespace("http://music.org/")
PRED = Namespace("http://music.org/pred/")
TYPE = Namespace("http://music.org/type/")

# Prefixos partilhados por todas as queries das regras.
QUERY_PREFIXES = (
    "PREFIX type: <http://music.org/type/>\n"
    "PREFIX pred: <http://music.org/pred/>\n"
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"
)


class SpinRule:
    """Uma regra de inferencia SPIN explicitamente identificada.

    head  -> triplas a inferir (clausula CONSTRUCT/INSERT)
    where -> condicao (clausula WHERE)
    target_class -> classe a que a regra fica ligada via spin:rule
    """

    def __init__(self, rule_id, label, comment, target_class, head, where):
        self.rule_id = rule_id
        self.label = label
        self.comment = comment
        self.target_class = target_class
        self.head = head.strip()
        self.where = where.strip()

    def construct_text(self):
        """Texto SPARQL CONSTRUCT (e o que fica guardado no sp:text da regra SPIN)."""
        return (
            f"{QUERY_PREFIXES}\n"
            f"CONSTRUCT {{\n  {self.head}\n}}\n"
            f"WHERE {{\n  {self.where}\n}}"
        )

    def insert_update(self):
        """Versao INSERT ... WHERE, usada para materializar a regra na GraphDB."""
        return (
            f"{QUERY_PREFIXES}\n"
            f"INSERT {{\n  {self.head}\n}}\n"
            f"WHERE {{\n  {self.where}\n}}"
        )


# ── Definicao das regras ──────────────────────────────────────────────────────
# A ordem importa para a materializacao: regras que dependem do resultado de
# outras (ex.: HitArtist depende de HitSong) vem depois.
RULES = [
    SpinRule(
        rule_id="ChartedSongRule",
        label="Charted song classification",
        comment=(
            "Uma musica referida por pelo menos uma entrada de chart e uma "
            "ChartedSong. Classificacao condicional (existencia de ChartEntry)."
        ),
        target_class=TYPE.Song,
        head="?this a type:ChartedSong .",
        where="?entry a type:ChartEntry ;\n         pred:song ?this .",
    ),
    SpinRule(
        rule_id="HitSongRule",
        label="Hit song classification",
        comment=(
            "Uma musica que entrou no top 10 (rank <= 10) e uma HitSong. "
            "Requer comparacao numerica (FILTER), fora do alcance de RDFS/OWL."
        ),
        target_class=TYPE.Song,
        head="?this a type:HitSong .",
        where=(
            "?entry pred:song ?this ;\n"
            "         pred:rank ?rank .\n"
            "  FILTER(?rank <= 10)"
        ),
    ),
    SpinRule(
        rule_id="LongTailSongRule",
        label="Long-tail song classification",
        comment=(
            "Uma musica e LongTailSong quando a sua longevidade no chart e alta "
            f"(MAX(weeks) >= {LONGTAIL_MIN_WEEKS}). Mede persistencia, nao pico."
        ),
        target_class=TYPE.Song,
        head="?this a type:LongTailSong .",
        where=(
            "{\n"
            "    SELECT ?this (MAX(?weeks) AS ?maxWeeks)\n"
            "    WHERE {\n"
            "      ?entry a type:ChartEntry ;\n"
            "             pred:song ?this ;\n"
            "             pred:weeks ?weeks .\n"
            "    }\n"
            "    GROUP BY ?this\n"
            "  }\n"
            f"  FILTER(?maxWeeks >= {LONGTAIL_MIN_WEEKS})"
        ),
    ),
    SpinRule(
        rule_id="HitArtistRule",
        label="Hit artist classification",
        comment=(
            "Um artista que interpreta uma HitSong e um HitArtist. Encadeia com "
            "a regra HitSong e usa pred:performer (inferido por subPropertyOf)."
        ),
        target_class=TYPE.Artist,
        head="?this a type:HitArtist .",
        where=(
            "?song a type:HitSong ;\n"
            "         pred:performer ?this ."
        ),
    ),
    SpinRule(
        rule_id="TrendingArtistRule",
        label="Trending artist classification",
        comment=(
            "Um artista com um top 10 a partir de 2024-01-01 e um TrendingArtist. "
            "Combina comparacao de rank e de data (FILTER sobre xsd:date)."
        ),
        target_class=TYPE.Artist,
        head="?this a type:TrendingArtist .",
        where=(
            "?entry pred:song ?song ;\n"
            "         pred:rank ?rank ;\n"
            "         pred:date ?date .\n"
            "  ?song pred:performer ?this .\n"
            '  FILTER(?rank <= 10 && ?date >= "2024-01-01"^^xsd:date)'
        ),
    ),
    SpinRule(
        rule_id="AppearsInChartRule",
        label="Artist appears in chart (new relation)",
        comment=(
            "Estabelece uma NOVA relacao artista -> chart, derivada das entradas "
            "das suas musicas. Liga entidades que nao tinham ligacao direta."
        ),
        target_class=TYPE.Artist,
        head="?this pred:appearsInChart ?chart .",
        where=(
            "?entry pred:song ?song ;\n"
            "         pred:inChart ?chart .\n"
            "  ?song pred:performer ?this ."
        ),
    ),
    SpinRule(
        rule_id="CollaboratedWithRule",
        label="Artist collaboration (new symmetric relation)",
        comment=(
            "Estabelece uma NOVA relacao simetrica entre artistas que partilham "
            "uma musica (mesmo performer). Cria ligacoes inexistentes nos dados."
        ),
        target_class=TYPE.Artist,
        head="?this pred:collaboratedWith ?other .",
        where=(
            "?song pred:performer ?this , ?other .\n"
            "  FILTER(?this != ?other)"
        ),
    ),
]


# ── Exportacao em SPIN (sp:/spin:) ────────────────────────────────────────────
def build_spin_graph():
    """Constroi o grafo RDF com as regras representadas em SPIN."""
    g = Graph()
    g.bind("sp", SP)
    g.bind("spin", SPIN)
    g.bind("music", BASE)
    g.bind("pred", PRED)
    g.bind("type", TYPE)

    for rule in RULES:
        rule_node = BASE[f"rule/{rule.rule_id}"]
        g.add((rule_node, RDF.type, SP.Construct))
        g.add((rule_node, SP.text, Literal(rule.construct_text())))
        g.add((rule_node, RDF.type, SPIN.Rule))
        g.add((rule_node, SPIN.labelTemplate, Literal(rule.label)))
        # Liga a regra a classe-alvo atraves de spin:rule (semantica SPIN).
        g.add((rule.target_class, SPIN.rule, rule_node))

    return g


def export_spin_ttl(path=SPIN_TTL_OUTPUT):
    g = build_spin_graph()
    g.serialize(destination=path, format="turtle")
    print(f"SPIN rules exported to {path} ({len(RULES)} rules).")
    return path


# ── Aplicacao na GraphDB (materializacao) ─────────────────────────────────────
def apply_rules(endpoint=DEFAULT_ENDPOINT, dry_run=False, timeout=60):
    """Aplica cada regra como INSERT ... WHERE no repositorio GraphDB.

    A GraphDB recente nao executa SPIN automaticamente, por isso materializamos
    as inferencias correndo as regras pela ordem definida (encadeamento simples).
    """
    update_endpoint = endpoint.rstrip("/") + "/statements"
    for rule in RULES:
        update = rule.insert_update()
        print(f"\n# Rule: {rule.rule_id} — {rule.label}")
        if dry_run:
            print(update)
            continue
        try:
            response = requests.post(
                update_endpoint, data={"update": update}, timeout=timeout
            )
            response.raise_for_status()
            print(f"  applied ok ({response.status_code}).")
        except requests.RequestException as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            raise
    if not dry_run:
        print(f"\nAll {len(RULES)} SPIN rules applied to {endpoint}.")


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="SPIN inference rules for the Music Trends ontology."
    )
    parser.add_argument(
        "--export", action="store_true", help="export the rules to spin_rules.ttl"
    )
    parser.add_argument(
        "--apply", action="store_true", help="materialize the rules on GraphDB"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --apply, print the SPARQL updates without executing them",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"GraphDB repository endpoint (default: {DEFAULT_ENDPOINT})",
    )
    args = parser.parse_args(argv)

    if not args.export and not args.apply:
        # Por omissao, exporta o ttl (acao segura, sem rede).
        export_spin_ttl()
        return

    if args.export:
        export_spin_ttl()
    if args.apply:
        apply_rules(endpoint=args.endpoint, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
