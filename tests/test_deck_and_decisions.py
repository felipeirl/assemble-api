import random
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.deck import Candidate, select_deck
from app.domain.match import (
    DECISION_VERSION,
    DECISION_VERSION_DEGRADED,
    MatchWeights,
    decide_match,
    seeded_chance,
)
from tests.conftest import auth_header
from tests.factories import seed_characters, seed_user

UID = "u1"
HEADERS = {**auth_header(UID), "X-Timezone": "America/Sao_Paulo"}
ELIGIBLE = {"storm", "iron-man", "rocket", "jean-grey"}


@pytest.fixture
def seeded(container):
    seed_characters(container.store)
    seed_user(container.store, UID)
    return container


def force_match(container, matched: bool) -> None:
    container.settings.match_cutoff = 0.0 if matched else 2.0


def deck(client):
    response = client.get("/v2/deck", headers=HEADERS)
    assert response.status_code == 200
    return response.json()


def decide(client, character_id, choice, key=None):
    headers = {**HEADERS, **({"Idempotency-Key": key} if key else {})}
    return client.post(
        "/v2/decisions", json={"characterId": character_id, "choice": choice}, headers=headers
    )


# --- regras puras ---------------------------------------------------------------------------


def test_select_deck_spreads_origins_and_teams():
    candidates = [
        Candidate("x1", 90, "Mutant", ("XMen",), False),
        Candidate("x2", 89, "Mutant", ("XMen",), False),
        Candidate("a1", 80, "Human", ("Avengers",), False),
    ]

    chosen = select_deck(candidates, 2, random.Random(0), luck=0.1)  # sem sorte: só a regra

    assert chosen == ["x1", "a1"]


def test_select_deck_favors_new_characters():
    candidates = [
        Candidate("old", 80, "Human", (), False),
        Candidate("new", 75, "Alien", (), True),
    ]

    assert select_deck(candidates, 1, random.Random(0), luck=0.1)[0] == "new"


def test_select_deck_respects_size():
    candidates = [Candidate(f"c{i}", 50, None, (), False) for i in range(40)]

    assert len(select_deck(candidates, 30, random.Random(0))) == 30


WEIGHTS = MatchWeights(compatibility=0.6, affinity=0.3, chance=0.1, cutoff=0.55)


def test_decide_match_with_affinity():
    decision = decide_match(80, affinity=0.5, luck=0.5, weights=WEIGHTS)

    assert decision.chance == pytest.approx(0.48 + 0.15 + 0.05)
    assert decision.matched is True
    assert decision.version == DECISION_VERSION


def test_decide_match_without_affinity_is_degraded():
    decision = decide_match(80, affinity=None, luck=0.5, weights=WEIGHTS)

    assert decision.chance == pytest.approx(0.53)
    assert decision.matched is False
    assert decision.version == DECISION_VERSION_DEGRADED


def test_seeded_chance_is_deterministic_per_pair():
    assert seeded_chance("u1", "storm") == seeded_chance("u1", "storm")
    assert seeded_chance("u1", "storm") != seeded_chance("u2", "storm")
    assert 0 <= seeded_chance("u1", "storm") < 1


# --- GET /v2/deck --------------------------------------------------------------------------


def test_deck_day_document_is_stored_and_the_cards_are_drawn(client, seeded):
    first = deck(client)

    stored = seeded.store.get(f"users/{UID}/decks/{first['date']}")
    assert stored["algorithmVersion"] == "deck-v3"
    assert "characterIds" not in stored  # a lista não é fixa: cada abertura sorteia de novo
    assert first["total"] == 4
    assert first["remaining"] == 4
    assert {c["characterId"] for c in first["cards"]} == ELIGIBLE

    seeded.store.set("characters/new-one", {"name": "Novo", "origin": "Alien", "tier": "B"})
    seeded.catalog.invalidate()
    assert deck(client)["total"] == 5  # um personagem novo entra no sorteio


def test_every_deck_request_draws_again(client, seeded):
    import random

    draws = []

    def factory():
        draws.append(len(draws))
        return random.Random(len(draws))

    seeded.deck_service._rng_factory = factory
    deck(client)
    deck(client)

    assert len(draws) == 2


def test_deck_card_has_no_compatibility(client, seeded):
    cards = {c["characterId"]: c for c in deck(client)["cards"]}

    storm = cards["storm"]
    assert storm == {
        "characterId": "storm",
        "name": "Storm",
        "imageUrl": "https://img/storm.jpg",
        "tagline": "Ororo Munroe é uma mutante que controla o clima.",
        "traitsInCommon": ["Mutant", "XMen", "Leadership"],
    }
    assert "imageUrl" not in cards["rocket"]


def test_deck_day_follows_user_timezone(client, seeded, clock):
    clock.current = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)  # 23h de 30/09 em São Paulo

    body = deck(client)

    assert body["date"] == "2026-09-30"
    assert body["nextDeckAt"] == "2026-10-01T03:00:00Z"


def test_deck_size_is_capped(client, seeded):
    seeded.settings.deck_size = 2

    body = deck(client)

    assert body["total"] == 2


def test_decided_characters_leave_the_deck_without_replacement(client, seeded):
    deck(client)

    assert decide(client, "storm", "PASS").status_code == 204

    body = deck(client)
    assert body["remaining"] == 3
    assert body["total"] == 4
    assert "storm" not in {c["characterId"] for c in body["cards"]}


def test_passed_character_never_returns_next_day(client, seeded, clock):
    deck(client)
    decide(client, "storm", "PASS")

    clock.current += timedelta(days=1)
    body = deck(client)

    assert "storm" not in {c["characterId"] for c in body["cards"]}
    assert body["total"] == 3


def test_deck_requires_active_account(client, seeded):
    seeded.store.update(f"users/{UID}", {"status": "deactivated"})

    assert client.get("/v2/deck", headers=HEADERS).status_code == 403


# --- POST /v2/decisions -------------------------------------------------------------------


def test_unknown_character_is_404(client, seeded):
    assert decide(client, "nobody", "PASS").status_code == 404
    assert decide(client, "out-of-tier", "PASS").status_code == 404


def test_invalid_choice_is_400(client, seeded):
    response = decide(client, "storm", "MAYBE")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_repeated_decision_without_key_is_409(client, seeded):
    decide(client, "storm", "PASS")

    response = decide(client, "storm", "ASSEMBLE")

    assert response.status_code == 409
    assert response.json()["error"] == "already_decided"


def test_repeated_pass_with_same_key_is_204(client, seeded):
    assert decide(client, "storm", "PASS", key="k1").status_code == 204
    assert decide(client, "storm", "PASS", key="k1").status_code == 204
    assert decide(client, "storm", "PASS", key="k2").status_code == 409


def test_assemble_without_match_returns_only_matched_false(client, seeded):
    force_match(seeded, matched=False)

    response = decide(client, "storm", "ASSEMBLE")

    assert response.status_code == 200
    assert response.json() == {"matched": False}
    assert seeded.store.get(f"users/{UID}/matches/storm") is None


def test_assemble_with_match_creates_connection(client, seeded, clock):
    force_match(seeded, matched=True)

    response = decide(client, "storm", "ASSEMBLE")

    assert response.status_code == 200
    assert response.json() == {
        "matched": True,
        "connectionId": "storm",
        "character": {
            "characterId": "storm",
            "name": "Storm",
            "imageUrl": "https://img/storm.jpg",
        },
        "score": 67,
        "reasons": ["Mutant", "XMen", "Leadership"],
    }
    match = seeded.store.get(f"users/{UID}/matches/storm")
    assert match["score"] == 67
    assert match["userMessageCount"] == 0
    assert match["characterName"] == "Storm"
    assert match["hidden"] is False
    assert match["createdAt"] == clock.now()
    assert match["decisionVersion"] == DECISION_VERSION_DEGRADED


def test_assemble_is_idempotent_with_same_key(client, seeded):
    force_match(seeded, matched=True)
    first = decide(client, "storm", "ASSEMBLE", key="k1").json()

    second = decide(client, "storm", "ASSEMBLE", key="k1")

    assert second.status_code == 200
    assert second.json() == first


# --- POST /v2/decisions/undo --------------------------------------------------------------


def test_undo_without_pass_is_409(client, seeded):
    response = client.post("/v2/decisions/undo", headers=HEADERS)

    assert response.status_code == 409
    assert response.json()["error"] == "nothing_to_undo"


def test_undo_restores_last_pass_once(client, seeded):
    deck(client)
    decide(client, "storm", "PASS")
    decide(client, "rocket", "PASS")
    assert deck(client)["canUndo"] is True

    response = client.post("/v2/decisions/undo", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["characterId"] == "rocket"
    body = deck(client)
    assert "rocket" in {c["characterId"] for c in body["cards"]}
    assert body["canUndo"] is False
    assert client.post("/v2/decisions/undo", headers=HEADERS).status_code == 409


def test_undo_reaches_last_pass_after_an_assemble(client, seeded):
    force_match(seeded, matched=False)
    decide(client, "storm", "PASS")
    decide(client, "iron-man", "ASSEMBLE")

    response = client.post("/v2/decisions/undo", headers=HEADERS)

    assert response.json()["characterId"] == "storm"


def test_undo_does_not_reach_previous_day(client, seeded, clock):
    decide(client, "storm", "PASS")

    clock.current += timedelta(days=1)

    assert client.post("/v2/decisions/undo", headers=HEADERS).status_code == 409


def test_select_deck_differs_between_people_with_the_same_scores():
    candidates = [Candidate(f"c{i}", 55, "Human", (), False) for i in range(40)]

    first = select_deck(candidates, 10, random.Random("user-a:1"))
    second = select_deck(candidates, 10, random.Random("user-b:1"))

    assert set(first) != set(second)


def test_select_deck_always_includes_a_much_better_match():
    candidates = [Candidate("best", 95, "Human", (), False)] + [
        Candidate(f"c{i}", 40, f"Origin{i}", (), False) for i in range(30)
    ]

    for seed in range(50):
        assert "best" in select_deck(candidates, 5, random.Random(seed))


def test_select_deck_favors_more_compatible_characters_on_average():
    candidates = [Candidate(f"c{i}", 40 + i, f"Origin{i % 6}", (), False) for i in range(40)]
    pool_mean = sum(c.score for c in candidates) / len(candidates)
    scores = {c.character_id: c.score for c in candidates}

    means = []
    for seed in range(40):
        chosen = select_deck(candidates, 10, random.Random(seed))
        means.append(sum(scores[c] for c in chosen) / len(chosen))

    assert sum(means) / len(means) > pool_mean + 8


def test_deck_reads_the_decisions_once(client, seeded, monkeypatch):
    decide(client, "rocket", "PASS")
    store = seeded.store
    original = store.query
    collections = []

    def spy(collection, filters=(), *args, **kwargs):
        if not filters:  # leitura completa; a contagem do dia usa filtro
            collections.append(collection)
        return original(collection, filters, *args, **kwargs)

    monkeypatch.setattr(store, "query", spy)

    cards = deck(client)["cards"]

    assert collections.count(f"users/{UID}/decisions") == 1
    assert "rocket" not in {card["characterId"] for card in cards}


def test_assembles_are_rate_limited_per_user(client, seeded):
    seeded.settings.assembles_per_hour = 1
    seeded.__dict__.pop("decision_service", None)
    force_match(seeded, False)

    assert decide(client, "storm", "ASSEMBLE").status_code == 200
    response = decide(client, "iron-man", "ASSEMBLE")

    assert response.status_code == 429
    assert response.json()["error"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 0
    assert decide(client, "rocket", "PASS").status_code == 204
    assert decide(client, "storm", "ASSEMBLE").status_code == 409  # já decidido, sem gastar cota
