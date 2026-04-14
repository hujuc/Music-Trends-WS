from __future__ import annotations

import time
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


def _post_with_retry(url: str, data: dict[str, str], headers: dict[str, str] | None = None) -> requests.Response:
    last_exc: requests.RequestException | None = None
    for attempt in range(2):
        try:
            response = requests.post(
                url,
                data=data,
                headers=headers,
                timeout=settings.GRAPHDB_TIMEOUT,
            )
            response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(0.4)
                continue
            break

    if last_exc is not None:
        raise last_exc
    raise requests.RequestException("Unknown GraphDB request failure.")


def run_select(query_body: str) -> list[dict[str, Any]]:
    prefixes = build_prefixes(settings.SPARQL_PREFIXES)
    full_query = f"{prefixes}\n\n{query_body.strip()}"

    try:
        response = _post_with_retry(
            url=settings.GRAPHDB_ENDPOINT,
            data={"query": full_query},
            headers={"Accept": "application/sparql-results+json"},
        )
        payload = response.json()
    except requests.RequestException as exc:
        raise SparqlClientError(
            f"Nao foi possivel ligar ao GraphDB em {settings.GRAPHDB_ENDPOINT}."
        ) from exc
    except ValueError as exc:
        raise SparqlClientError("Resposta invalida do GraphDB.") from exc

    bindings = payload.get("results", {}).get("bindings")
    if bindings is None:
        raise SparqlClientError("Resposta SPARQL sem campo de resultados.")

    return bindings


def run_update(query_body: str) -> None:
    prefixes = build_prefixes(settings.SPARQL_PREFIXES)
    full_query = f"{prefixes}\n\n{query_body.strip()}"

    update_endpoint = settings.GRAPHDB_ENDPOINT.rstrip('/') + '/statements'
    try:
        _post_with_retry(url=update_endpoint, data={"update": full_query})
    except requests.RequestException as exc:
        raise SparqlClientError(
            f"Falha ao executar update SPARQL em {update_endpoint}."
        ) from exc
