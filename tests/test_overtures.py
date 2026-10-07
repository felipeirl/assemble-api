import pytest

from app.config import Settings
from tests.conftest import auth_header
from tests.factories import seed_characters, seed_user

UID = "u1"
HEADERS = {**auth_header(UID), "X-Timezone": "America/Sao_Paulo"}


@pytest.fixture
def ready(container):
    seed_characters(container.store)
    seed_user(container.store, UID)
    user = container.store.get(f"users/{UID}")
    container.store.set(f"users/{UID}", {**user, "onboardingCompletedAt": container.clock.now()})
    container.settings.match_cutoff = 0.0
    return container


def overtures(container):
    return dict(container.store.query(f"users/{UID}/overtures"))


def test_an_overture_with_match_creates_a_pending_proposal(ready):
    assert ready.decision_service.overture(UID) is True

    ((character_id, proposal),) = overtures(ready).items()
    assert proposal["status"] == "pending"
    assert proposal["match"]["score"] >= 0
    assert ready.store.get(f"users/{UID}/decisions/{character_id}") is None
    assert ready.store.get(f"users/{UID}/matches/{character_id}") is None


def test_an_overture_without_match_is_recorded_as_skipped(ready):
    ready.settings.match_cutoff = 2.0
    ready.__dict__.pop("decision_service", None)

    assert ready.decision_service.overture(UID) is False

    ((_, proposal),) = overtures(ready).items()
    assert proposal["status"] == "skipped"
    assert "match" not in proposal


def test_only_one_pending_proposal_at_a_time(ready):
    ready.decision_service.overture(UID)

    assert ready.decision_service.overture(UID) is False
    assert len(overtures(ready)) == 1


def test_characters_already_decided_or_tried_are_not_drawn(ready, client):
    client.post("/v2/decisions", json={"characterId": "storm", "choice": "PASS"}, headers=HEADERS)
    ready.settings.match_cutoff = 2.0  # cada tentativa vira skipped e libera a próxima
    ready.__dict__.pop("decision_service", None)  # os pesos são lidos ao montar o serviço

    for _ in range(10):
        ready.decision_service.overture(UID)

    tried = set(overtures(ready))
    assert "storm" not in tried
    assert len(tried) == 3  # os quatro elegíveis menos o que já recebeu Pass


def test_accepting_the_overture_always_matches_and_skips_the_assemble_limit(ready, client):
    ready.decision_service.overture(UID)
    ((character_id, _),) = overtures(ready).items()
    ready.settings.match_cutoff = 2.0  # sozinho, o usuário não conseguiria o match
    ready.settings.assembles_per_hour = 0
    ready.__dict__.pop("decision_service", None)

    response = client.post(
        "/v2/decisions", json={"characterId": character_id, "choice": "ASSEMBLE"}, headers=HEADERS
    )

    assert response.status_code == 202
    decision = ready.store.get(f"users/{UID}/decisions/{character_id}")
    assert decision["status"] == "matched" and decision["overture"] is True
    assert ready.store.get(f"users/{UID}/matches/{character_id}") is not None
    assert overtures(ready)[character_id]["status"] == "accepted"


def test_passing_on_an_overture_declines_it(ready, client):
    ready.decision_service.overture(UID)
    ((character_id, _),) = overtures(ready).items()

    client.post(
        "/v2/decisions", json={"characterId": character_id, "choice": "PASS"}, headers=HEADERS
    )

    assert overtures(ready)[character_id]["status"] == "declined"


def test_a_round_visits_only_active_users_who_finished_onboarding(ready):
    seed_user(ready.store, "no-onboarding")
    seed_user(ready.store, "gone")
    gone = ready.store.get("users/gone")
    ready.store.set(
        "users/gone", {**gone, "onboardingCompletedAt": ready.clock.now(), "status": "deactivated"}
    )

    created = ready.overture_service.run()

    assert created == 1
    assert ready.store.query("users/no-onboarding/overtures") == []
    assert ready.store.query("users/gone/overtures") == []


def test_a_failure_for_one_user_does_not_stop_the_round(ready, monkeypatch):
    seed_user(ready.store, "u2")
    ready.store.set(
        "users/u2", {**ready.store.get("users/u2"), "onboardingCompletedAt": ready.clock.now()}
    )
    service = ready.decision_service
    original = service.overture

    def flaky(uid):
        if uid == UID:
            raise RuntimeError("falhou")
        return original(uid)

    monkeypatch.setattr(service, "overture", flaky)

    assert ready.overture_service.run() == 1


def test_the_interval_can_be_turned_off():
    assert Settings(_env_file=None, overture_interval_minutes=0).overture_interval_minutes == 0
    assert Settings(_env_file=None).overture_interval_minutes == 30
