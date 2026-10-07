import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.auth import ActiveUid, AnyStatusUid, require_jobs_key
from app.errors import ApiError
from app.main import create_app
from tests.conftest import JOBS_KEY, auth_header


@pytest.fixture
def probe_client(container):
    app = create_app(lambda: container)

    @app.get("/v2/probe")
    def probe(uid: ActiveUid) -> dict[str, str]:
        return {"uid": uid}

    @app.get("/v2/probe-fails")
    def probe_fails(uid: ActiveUid) -> dict[str, str]:
        raise ApiError("not_found")

    @app.get("/v2/probe-any-status")
    def probe_any_status(uid: AnyStatusUid) -> dict[str, str]:
        return {"uid": uid}

    @app.post("/jobs/probe", status_code=202, dependencies=[Depends(require_jobs_key)])
    def jobs_probe() -> None:
        return None

    with TestClient(app) as client:
        yield client


def test_missing_token_returns_401(probe_client):
    response = probe_client.get("/v2/probe")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthenticated"


def test_invalid_token_returns_401(probe_client):
    response = probe_client.get("/v2/probe", headers={"Authorization": "Bearer lixo"})

    assert response.status_code == 401


def test_non_bearer_scheme_returns_401(probe_client):
    response = probe_client.get("/v2/probe", headers={"Authorization": "Basic token-u1"})

    assert response.status_code == 401


def test_valid_token_returns_uid_from_token(probe_client):
    response = probe_client.get("/v2/probe", headers=auth_header("u1"))

    assert response.status_code == 200
    assert response.json() == {"uid": "u1"}


def test_deactivated_account_returns_403(probe_client, container):
    container.store.set("users/u1", {"status": "deactivated"})

    response = probe_client.get("/v2/probe", headers=auth_header("u1"))

    assert response.status_code == 403
    assert response.json()["error"] == "account_deactivated"


def test_deactivated_account_passes_status_free_dependency(probe_client, container):
    container.store.set("users/u1", {"status": "deactivated"})

    response = probe_client.get("/v2/probe-any-status", headers=auth_header("u1"))

    assert response.status_code == 200


def test_error_message_follows_accept_language(probe_client):
    response = probe_client.get("/v2/probe", headers={"Accept-Language": "pt-BR"})

    assert response.json() == {
        "error": "unauthenticated",
        "message": "Entre novamente para continuar.",
    }


def test_authenticated_request_writes_access_log(probe_client, container, clock):
    probe_client.get(
        "/v2/probe", headers={**auth_header("u1"), "X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
    )

    logs = container.store.query("accessLogs")
    assert len(logs) == 1
    log = logs[0][1]
    assert log["uid"] == "u1"
    assert log["route"] == "GET /v2/probe"
    assert log["ip"] == "203.0.113.7"
    assert log["timestamp"] == clock.now()
    assert (log["expiresAt"] - log["timestamp"]).days == 180


def test_access_log_is_written_when_the_route_fails(probe_client, container):
    response = probe_client.get("/v2/probe-fails", headers=auth_header("u1"))

    assert response.status_code == 404
    logs = container.store.query("accessLogs")
    assert [log["route"] for _, log in logs] == ["GET /v2/probe-fails"]


def test_jobs_route_requires_key(probe_client):
    assert probe_client.post("/jobs/probe").status_code == 401
    assert probe_client.post("/jobs/probe", headers={"X-Jobs-Key": "errada"}).status_code == 401


def test_jobs_route_rejects_user_token(probe_client):
    response = probe_client.post("/jobs/probe", headers=auth_header("u1"))

    assert response.status_code == 401


def test_jobs_route_accepts_key(probe_client, container):
    response = probe_client.post("/jobs/probe", headers={"X-Jobs-Key": JOBS_KEY})

    assert response.status_code == 202
    assert container.store.query("accessLogs")[0][1]["uid"] is None


def test_unknown_route_uses_error_format(probe_client):
    response = probe_client.get("/v2/nao-existe")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
