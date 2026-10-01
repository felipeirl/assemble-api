import json

import pytest

from app.domain.match import DECISION_VERSION, DECISION_VERSION_DEGRADED, seeded_chance
from tests.conftest import auth_header
from tests.factories import seed_characters, seed_user

UID = "u1"
HEADERS = auth_header(UID)
STORM_SCORE = 67


@pytest.fixture
def ready(container):
    seed_characters(container.store)
    seed_user(container.store, UID)
    container.store.update(f"users/{UID}", {"bio": "Gosto de estratégia e de ajudar."})
    container.store.set(
        "personas/storm",
        {"voice": "calma", "values": ["proteger os outros"], "styles": ["Leadership"]},
    )
    return container


def assemble(client):
    return client.post(
        "/v2/decisions", json={"characterId": "storm", "choice": "ASSEMBLE"}, headers=HEADERS
    )


def expected_chance(affinity: float | None) -> float:
    chance = 0.6 * STORM_SCORE / 100 + 0.1 * seeded_chance(UID, "storm")
    return chance + (0.3 * affinity if affinity is not None else 0.0)


def test_high_affinity_produces_match_with_full_formula(client, ready):
    ready.guardrail.affinity_value = 1.0

    response = assemble(client)

    assert response.json()["matched"] is True
    match = ready.store.get(f"users/{UID}/matches/storm")
    assert match["decisionVersion"] == DECISION_VERSION
    assert match["matchChance"] == pytest.approx(expected_chance(1.0), abs=1e-4)


def test_low_affinity_can_prevent_match(client, ready):
    ready.guardrail.affinity_value = 0.0
    ready.settings.match_cutoff = expected_chance(0.0) + 0.01

    response = assemble(client)

    assert response.json() == {"matched": False}
    assert ready.store.get(f"users/{UID}/decisions/storm")["matched"] is False


def test_guardrail_outage_falls_back_to_degraded_mode(client, ready):
    ready.guardrail.unavailable = True
    ready.settings.match_cutoff = 0.0

    response = assemble(client)

    # Sem Laya o chat também falha: a decisão fica gravada e a conexão espera nova tentativa.
    assert response.status_code == 503
    decision = ready.store.get(f"users/{UID}/decisions/storm")
    assert decision["match"]["decisionVersion"] == DECISION_VERSION_DEGRADED
    assert decision["match"]["matchChance"] == pytest.approx(expected_chance(None), abs=1e-4)


def test_missing_persona_uses_degraded_mode(client, ready):
    ready.store.delete("personas/storm")
    ready.settings.match_cutoff = 0.0

    assemble(client)

    match = ready.store.get(f"users/{UID}/matches/storm")
    assert match["decisionVersion"] == DECISION_VERSION_DEGRADED


def test_affinity_inputs_are_preferences_bio_and_persona(client, ready):
    calls = []
    original = ready.guardrail.affinity

    def spy(user_profile, persona):
        calls.append((json.loads(user_profile), json.loads(persona)))
        return original(user_profile, persona)

    ready.guardrail.affinity = spy

    assemble(client)

    profile, persona = calls[0]
    assert profile["bio"] == "Gosto de estratégia e de ajudar."
    assert profile["preferences"]["teams"] == ["XMen"]
    assert persona == {"voice": "calma", "values": ["proteger os outros"], "styles": ["Leadership"]}
