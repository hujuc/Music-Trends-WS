import json
import requests
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GRAPHDB_URL = "http://localhost:7200"
REPOSITORY = "music"
FILE_PATH = os.path.join(BASE_DIR, "music.ttl")


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
    else:
        print(f"Failed to create repository: {response.status_code} - {response.text}")
        return False


def load_ttl_to_graphdb(file_path, repo, base_url):
    url = f"{base_url}/repositories/{repo}/statements"

    with open(file_path, "rb") as f:
        response = requests.post(url, headers={"Content-Type": "text/turtle"}, data=f)

    if response.status_code in (200, 204):
        print(f"Successfully loaded '{file_path}' into repository '{repo}'")
    else:
        print(f"Failed to load file: {response.status_code} - {response.text}")


if __name__ == "__main__":
    if create_repository_if_not_exists(REPOSITORY, GRAPHDB_URL):
        load_ttl_to_graphdb(FILE_PATH, REPOSITORY, GRAPHDB_URL)
