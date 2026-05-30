"""
Carrega os dados na GraphDB e materializa as inferencias.

Fluxo completo de um arranque limpo:
  1. cria o repositorio `music` (se nao existir);
  2. carrega os ficheiros RDF (factos + ontologia + shapes);
  3. aplica as regras de inferencia SPIN (ver spin_rules.py).

Uso:
    python load_ttl_to_graphdb.py
    GRAPHDB_URL=http://localhost:7200 REPOSITORY=music python load_ttl_to_graphdb.py
"""

import json
import os
import sys

import requests

import spin_rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GRAPHDB_URL = os.getenv("GRAPHDB_URL", "http://localhost:7200").rstrip("/")
REPOSITORY = os.getenv("REPOSITORY", "music")

# Ficheiros RDF a carregar (pela ordem). music.ttl ja inclui o esquema da
# ontologia; ontology.ttl e shapes.ttl sao carregados explicitamente para que o
# repositorio fique completo mesmo quando importado de forma isolada.
RDF_FILES = [
    os.path.join(BASE_DIR, "music.ttl"),
    os.path.join(BASE_DIR, "ontology.ttl"),
    os.path.join(BASE_DIR, "shapes.ttl"),
]


def create_repository_if_not_exists(repo, base_url):
    response = requests.get(
        f"{base_url}/rest/repositories", headers={"Accept": "application/json"}
    )

    if response.status_code != 200:
        print(f"Failed to list repositories: {response.status_code} - {response.text}")
        return False

    repos = [r["id"] for r in response.json()]
    if repo in repos:
        print(f"Repository '{repo}' already exists")
        return True

    config = {
        "id": repo,
        "title": repo,
        "type": "graphdb",
        "params": {
            "baseURL": {
                "name": "baseURL",
                "label": "Base URL",
                "value": "http://example.org/owlim#",
            },
            "repositoryType": {
                "name": "repositoryType",
                "label": "Repository type",
                "value": "file-repository",
            },
            "ruleset": {
                "name": "ruleset",
                "label": "Ruleset",
                "value": "rdfsplus-optimized",
            },
            "storageFolder": {
                "name": "storageFolder",
                "label": "Storage folder",
                "value": "storage",
            },
            "enableContextIndex": {
                "name": "enableContextIndex",
                "label": "Enable context index",
                "value": "true",
            },
            "entityIndexSize": {
                "name": "entityIndexSize",
                "label": "Entity index size",
                "value": "10000000",
            },
            "entityIdSize": {
                "name": "entityIdSize",
                "label": "Entity ID size",
                "value": "32",
            },
            "imports": {
                "name": "imports",
                "label": "Imported RDF files(';' delimited)",
                "value": "",
            },
            "defaultNS": {
                "name": "defaultNS",
                "label": "Default namespaces for imports(';' delimited)",
                "value": "",
            },
        },
    }

    response = requests.post(
        f"{base_url}/rest/repositories",
        headers={"Content-Type": "application/json"},
        data=json.dumps(config),
    )

    if response.status_code in (200, 201):
        print(f"Repository '{repo}' created successfully")
        return True

    print(f"Failed to create repository: {response.status_code} - {response.text}")
    return False


def load_ttl_to_graphdb(file_path, repo, base_url):
    if not os.path.exists(file_path):
        print(f"Skipping '{os.path.basename(file_path)}' (not found)")
        return True

    url = f"{base_url}/repositories/{repo}/statements"
    with open(file_path, "rb") as f:
        response = requests.post(
            url, headers={"Content-Type": "text/turtle"}, data=f
        )

    if response.status_code in (200, 204):
        print(f"Loaded '{os.path.basename(file_path)}' into '{repo}'")
        return True

    print(f"Failed to load {os.path.basename(file_path)}: "
          f"{response.status_code} - {response.text}")
    return False


def main():
    if not create_repository_if_not_exists(REPOSITORY, GRAPHDB_URL):
        sys.exit(1)

    for file_path in RDF_FILES:
        if not load_ttl_to_graphdb(file_path, REPOSITORY, GRAPHDB_URL):
            sys.exit(1)

    # Materializa as classificacoes/relacoes inferidas pelas regras SPIN.
    endpoint = f"{GRAPHDB_URL}/repositories/{REPOSITORY}"
    print("\nApplying SPIN inference rules...")
    spin_rules.apply_rules(endpoint=endpoint)


if __name__ == "__main__":
    main()
