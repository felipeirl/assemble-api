import pytest

from app.main import create_app
from tests.conftest import auth_header
from tests.factories import seed_characters, seed_user

PUBLIC_PATHS = {"/health"}


def protected_routes(container):
    paths = create_app(lambda: container).openapi()["paths"]
    return [
        (method.upper(), path)
        for path, operations in paths.items()
        if path not in PUBLIC_PATHS
        for method in operations
    ]


def concrete(path: str) -> str:
    return path.replace("{character_id}", "storm").replace("{connection_id}", "storm")


def test_every_v2_route_requires_firebase_token(client, container):
    routes = [r for r in protected_routes(container) if r[1].startswith("/v2/")]

    assert len(routes) == 9
    for method, path in routes:
        response = client.request(method, concrete(path), json={})
        assert response.status_code == 401, (method, path)


def test_every_jobs_route_requires_jobs_key(client, container):
    routes = [r for r in protected_routes(container) if r[1].startswith("/jobs/")]

    assert len(routes) == 4
    for method, path in routes:
        assert client.request(method, path, headers=auth_header("u1")).status_code == 401


@pytest.mark.parametrize("bad_id", ["a/b", "..", "x" * 201, "storm%2Fmatches"])
def test_ids_that_could_escape_firestore_paths_are_rejected(client, container, bad_id):
    seed_characters(container.store)
    seed_user(container.store, "u1")

    decision = client.post(
        "/v2/decisions",
        json={"characterId": bad_id, "choice": "PASS"},
        headers=auth_header("u1"),
    )

    assert decision.status_code == 400


def test_path_ids_are_validated(client, container):
    response = client.get("/v2/characters/" + "x" * 201, headers=auth_header("u1"))

    assert response.status_code == 400


def test_health_exposes_nothing_sensitive(client):
    assert client.get("/health").json() == {"status": "ok"}
