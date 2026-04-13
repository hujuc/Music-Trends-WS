from __future__ import annotations

from typing import Any

import requests
from django.conf import settings


class SparqlClientError(Exception):
    """Raised when the SPARQL endpoint is unavailable or returns invalid data."""


def build_prefixes(prefixes: dict[str, str]) -> str:
    return "\n".join(f"PREFIX {alias}: <{uri}>" for alias, uri in prefixes.items())


def sparql_escape_literal(value: str) -> str:
    escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
    return f'"{escaped}"'


def run_select(query_body: str) -> list[dict[str, Any]]:
    prefixes = build_prefixes(settings.SPARQL_PREFIXES)
    full_query = f"{prefixes}\n\n{query_body.strip()}"

    try:
        response = requests.post(
            settings.GRAPHDB_ENDPOINT,
            data={"query": full_query},
            headers={"Accept": "application/sparql-results+json"},
            timeout=settings.GRAPHDB_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise SparqlClientError("Nao foi possivel ligar ao GraphDB.") from exc
    except ValueError as exc:
        raise SparqlClientError("Resposta invalida do GraphDB.") from exc

    bindings = payload.get("results", {}).get("bindings")
    if bindings is None:
        raise SparqlClientError("Resposta SPARQL sem campo de resultados.")

    return bindings


def run_update(query_body: str) -> None:
    prefixes = build_prefixes(settings.SPARQL_PREFIXES)
    full_query = f"{prefixes}\n\n{query_body.strip()}"

    try:
        response = requests.post(
            settings.GRAPHDB_ENDPOINT,
            data={"update": full_query},
            timeout=settings.GRAPHDB_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SparqlClientError("Falha ao executar update SPARQL.") from exc
