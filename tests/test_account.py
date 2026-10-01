from datetime import timedelta

import pytest

from tests.conftest import JOBS_KEY, auth_header
from tests.factories import seed_characters, seed_user

UID = "u1"
HEADERS = auth_header(UID)


@pytest.fixture
def with_chat(container, client):
    seed_characters(container.store)
    seed_user(container.store, UID)
    container.settings.match_cutoff = 0.0
    client.post(
        "/v2/decisions", json={"characterId": "storm", "choice": "ASSEMBLE"}, headers=HEADERS
    )
    client.post("/v2/connections/storm/messages", json={"text": "Oi"}, headers=HEADERS)
    return container


def purge(client):
    return client.post("/jobs/purge", headers={"X-Jobs-Key": JOBS_KEY})


def test_hide_chats_hides_connections_and_messages(client, with_chat, clock):
    response = client.post("/v2/chats/hide", headers=HEADERS)

    assert response.status_code == 204
    match = with_chat.store.get(f"users/{UID}/matches/storm")
    assert match["hidden"] is True
    assert match["hiddenAt"] == clock.now()
    messages = with_chat.store.query(f"users/{UID}/matches/storm/messages")
    assert messages and all(doc["hidden"] for _, doc in messages)


def test_hidden_chats_are_physically_removed_after_grace(client, with_chat, clock):
    client.post("/v2/chats/hide", headers=HEADERS)

    clock.current += timedelta(days=29)
    purge(client)
    assert with_chat.store.get(f"users/{UID}/matches/storm") is not None

    clock.current += timedelta(days=2)
    purge(client)
    assert with_chat.store.get(f"users/{UID}/matches/storm") is None
    assert with_chat.store.query(f"users/{UID}/matches/storm/messages") == []
    assert with_chat.store.get(f"users/{UID}") is not None


def test_deactivate_blocks_routes_and_returns_purge_date(client, with_chat, clock):
    response = client.post("/v2/account/deactivate", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {"purgeAt": "2026-10-31T15:00:00Z"}
    user = with_chat.store.get(f"users/{UID}")
    assert user["status"] == "deactivated"
    assert user["deactivatedAt"] == clock.now()
    assert client.get("/v2/deck", headers=HEADERS).status_code == 403


def test_reactivate_within_grace_restores_everything(client, with_chat, clock):
    client.post("/v2/account/deactivate", headers=HEADERS)
    clock.current += timedelta(days=29)

    response = client.post("/v2/account/reactivate", headers=HEADERS)

    assert response.status_code == 204
    assert with_chat.store.get(f"users/{UID}")["status"] == "active"
    assert client.get("/v2/me/stats", headers=HEADERS).json()["connections"] == 1


def test_reactivate_after_grace_is_refused(client, with_chat, clock):
    client.post("/v2/account/deactivate", headers=HEADERS)
    clock.current += timedelta(days=31)

    response = client.post("/v2/account/reactivate", headers=HEADERS)

    assert response.status_code == 403


def test_reactivate_active_account_is_noop(client, with_chat):
    assert client.post("/v2/account/reactivate", headers=HEADERS).status_code == 204


def test_purge_deletes_account_data_and_auth_user_after_grace(client, with_chat, clock):
    client.post("/v2/account/deactivate", headers=HEADERS)

    clock.current += timedelta(days=31)
    response = purge(client)

    assert response.status_code == 202
    assert with_chat.store.get(f"users/{UID}") is None
    assert with_chat.store.query(f"users/{UID}/decisions") == []
    assert with_chat.store.query(f"users/{UID}/matches/storm/messages") == []
    assert with_chat.token_verifier.deleted == [UID]
    assert with_chat.store.get("characters/storm") is not None


def test_purge_keeps_accounts_in_grace(client, with_chat, clock):
    client.post("/v2/account/deactivate", headers=HEADERS)

    clock.current += timedelta(days=10)
    purge(client)

    assert with_chat.store.get(f"users/{UID}") is not None
    assert with_chat.token_verifier.deleted == []


def test_purge_retries_later_when_auth_deletion_fails(client, with_chat, clock):
    def broken(uid):
        raise RuntimeError("rede")

    with_chat.token_verifier.delete_user = broken
    client.post("/v2/account/deactivate", headers=HEADERS)
    clock.current += timedelta(days=31)

    purge(client)

    assert with_chat.store.get(f"users/{UID}") is not None


def test_purge_removes_access_logs_after_six_months(client, with_chat, clock):
    assert with_chat.store.query("accessLogs")

    clock.current += timedelta(days=181)
    purge(client)

    remaining = with_chat.store.query("accessLogs")
    assert all(doc["timestamp"] == clock.now() for _, doc in remaining)


def test_purge_requires_jobs_key(client):
    assert client.post("/jobs/purge", headers=HEADERS).status_code == 401
