from datetime import timedelta

import pytest

from tests.conftest import auth_header
from tests.factories import seed_characters, seed_user
from tests.fakes import DEFAULT_SUGGESTIONS

UID = "u1"
HEADERS = {**auth_header(UID), "Accept-Language": "pt-BR"}


@pytest.fixture
def connected(container, client):
    seed_characters(container.store)
    seed_user(container.store, UID)
    container.settings.match_cutoff = 0.0
    response = client.post(
        "/v2/decisions", json={"characterId": "storm", "choice": "ASSEMBLE"}, headers=HEADERS
    )
    assert response.json()["matched"] is True
    return container


def send(client, text, key=None, connection="storm"):
    headers = {**HEADERS, **({"Idempotency-Key": key} if key else {})}
    return client.post(
        f"/v2/connections/{connection}/messages", json={"text": text}, headers=headers
    )


def messages(container, connection="storm"):
    docs = container.store.query(f"users/{UID}/matches/{connection}/messages", order_by="createdAt")
    return [doc for _, doc in docs]


# --- GET /v2/characters/{id} --------------------------------------------------------------


def test_preview_without_connection_hides_bio_and_compatibility(client, container):
    seed_characters(container.store)
    seed_user(container.store, UID)

    response = client.get("/v2/characters/storm", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "characterId": "storm",
        "name": "Tempestade",
        "imageUrl": "https://img/storm.jpg",
        "traitsInCommon": ["Mutant", "XMen", "Leadership"],
        "connected": False,
    }


def test_full_profile_with_connection(client, connected):
    response = client.get("/v2/characters/storm", headers=HEADERS)

    body = response.json()
    assert body["connected"] is True
    assert body["connectionId"] == "storm"
    assert body["score"] == 67
    assert body["whyYouMatch"] == [
        {"category": "origin", "traits": ["Mutant"]},
        {"category": "teams", "traits": ["XMen"]},
        {"category": "style", "traits": ["Leadership"]},
    ]
    assert body["facts"] == {
        "realName": "Ororo Munroe",
        "origin": "Mutant",
        "powers": ["Flight", "Energy"],
        "teams": ["XMen"],
        "firstAppearance": "Giant-Size X-Men #1",
        "issueAppearances": 4000,
        "bio": "Ororo Munroe é uma mutante que controla o clima.",
    }
    assert body["sources"] == [
        {"name": "Comic Vine", "url": "https://comicvine.gamespot.com/storm/4005-1468/"}
    ]
    assert "source" not in body and "sourceUrl" not in body
    assert "traitsInCommon" not in body


STORM_POWERSTATS = {
    "intelligence": 75,
    "strength": 10,
    "speed": 47,
    "durability": 30,
    "power": 88,
    "combat": 75,
}


def test_full_profile_has_enriched_facts_and_their_sources(client, connected):
    connected.store.update(
        "characters/storm",
        {
            "aliases": ["Windrider"],
            "alignment": "Good",
            "powerstats": STORM_POWERSTATS,
            "appearance": {"heightCm": 180, "eyeColor": "Blue"},
            "factSources": {
                "realName": "ComicVine",
                "aliases": "SuperheroApi",
                "powerstats": "SuperheroApi",
                "placeOfBirth": "SuperheroApi",
            },
            "sources": [
                {"name": "Comic Vine", "url": "https://cv/storm"},
                {"name": "Superhero API", "url": "https://akabab.github.io/superhero-api/"},
            ],
        },
    )

    body = client.get("/v2/characters/storm", headers=HEADERS).json()

    assert body["facts"]["aliases"] == ["Windrider"]
    assert body["facts"]["powerstats"] == STORM_POWERSTATS
    assert body["facts"]["appearance"] == {"heightCm": 180, "eyeColor": "Blue"}
    # Fonte só dos fatos presentes: placeOfBirth não existe no personagem.
    assert body["factSources"] == {
        "realName": "ComicVine",
        "aliases": "SuperheroApi",
        "powerstats": "SuperheroApi",
    }
    assert [s["name"] for s in body["sources"]] == ["Comic Vine", "Superhero API"]


def test_teammates_put_connected_first_and_skip_solo(client, connected):
    connected.store.set(
        "characters/cyclops",
        {"name": "Cyclops", "origin": "Mutant", "teams": ["XMen"], "tier": "A"},
    )
    connected.store.set(
        "characters/loner",
        {"name": "Loner", "origin": "Human", "teams": ["Solo"], "tier": "B"},
    )
    connected.catalog.invalidate()
    client.post(
        "/v2/decisions", json={"characterId": "jean-grey", "choice": "ASSEMBLE"}, headers=HEADERS
    )

    teammates = client.get("/v2/characters/storm", headers=HEADERS).json()["teammates"]

    assert teammates == [
        {
            "characterId": "jean-grey",
            "name": "Jean Grey",
            "imageUrl": "https://img/jean.jpg",
            "connected": True,
        },
        {"characterId": "cyclops", "name": "Ciclope", "connected": False},
    ]


def test_teammates_are_capped_at_eight(client, connected):
    for index in range(10):
        connected.store.set(
            f"characters/xman-{index}",
            {"name": f"X {index}", "origin": "Mutant", "teams": ["XMen"], "tier": "B"},
        )
    connected.catalog.invalidate()

    teammates = client.get("/v2/characters/storm", headers=HEADERS).json()["teammates"]

    assert len(teammates) == 8


def test_compare_with_lists_other_connections_with_powerstats(client, connected):
    connected.store.update("characters/storm", {"powerstats": STORM_POWERSTATS})
    connected.store.update("characters/iron-man", {"powerstats": STORM_POWERSTATS})
    connected.catalog.invalidate()
    for character_id in ("iron-man", "rocket"):
        client.post(
            "/v2/decisions",
            json={"characterId": character_id, "choice": "ASSEMBLE"},
            headers=HEADERS,
        )

    body = client.get("/v2/characters/storm", headers=HEADERS).json()

    assert body["compareWith"] == [
        {"characterId": "iron-man", "name": "Homem de Ferro", "powerstats": STORM_POWERSTATS}
    ]


def test_preview_hides_every_new_field(client, connected):
    connected.store.update("characters/rocket", {"powerstats": STORM_POWERSTATS})
    connected.catalog.invalidate()

    body = client.get("/v2/characters/rocket", headers=HEADERS).json()

    assert set(body) == {"characterId", "name", "traitsInCommon", "connected"}


def test_full_profile_omits_missing_facts(client, connected):
    connected.store.update("characters/storm", {"realName": None, "firstAppearance": ""})

    facts = client.get("/v2/characters/storm", headers=HEADERS).json()["facts"]

    assert "realName" not in facts and "firstAppearance" not in facts


def test_unknown_character_is_404(client, container):
    seed_characters(container.store)

    assert client.get("/v2/characters/nobody", headers=HEADERS).status_code == 404


# --- POST /v2/connections/{id}/messages ---------------------------------------------------


def test_send_message_returns_reply_and_updates_connection(client, connected, clock):
    response = send(client, "  Oi, Storm!  ")

    assert response.status_code == 200
    body = response.json()
    assert body["userMessage"]["author"] == "USER"
    assert body["userMessage"]["text"] == "Oi, Storm!"
    assert body["userMessage"]["fictional"] is False
    assert body["reply"]["author"] == "CHARACTER"
    assert body["reply"]["fictional"] is True
    assert body["reply"]["blocked"] is False
    assert body["reply"]["text"] == "Resposta a: Oi, Storm!"
    assert body["suggestions"] == DEFAULT_SUGGESTIONS

    match = connected.store.get(f"users/{UID}/matches/storm")
    assert match["userMessageCount"] == 1
    assert match["lastMessagePreview"] == "Resposta a: Oi, Storm!"
    stored = messages(connected)
    assert [m["author"] for m in stored] == ["CHARACTER", "USER", "CHARACTER"]


def test_history_is_sent_to_the_model(client, connected):
    send(client, "Primeira")
    send(client, "Segunda")

    last_call = connected.llm.calls[-1]["messages"]
    contents = [m["content"] for m in last_call[1:]]
    assert contents[-1].startswith("Segunda")
    assert "Primeira" in contents


def test_history_is_limited(client, connected):
    connected.settings.chat_history_limit = 2
    connected.__dict__.pop("conversation_service", None)
    send(client, "a")
    send(client, "b")

    send(client, "c")

    assert len(connected.llm.calls[-1]["messages"]) == 1 + 2 + 1


def test_blocked_input_is_422_without_storing_text(client, connected):
    response = send(client, "meu email é ana@x.com")

    assert response.status_code == 422
    assert response.json()["error"] == "blocked_content"
    blocked = messages(connected)[-1]
    assert blocked["blocked"] is True
    assert blocked["blockReason"] == "personal_data"
    assert blocked["text"] == ""
    assert connected.store.get(f"users/{UID}/matches/storm")["userMessageCount"] == 0


def test_self_harm_gets_referral_and_text_is_not_stored(client, connected):
    response = send(client, "penso em suicidio")

    body = response.json()
    assert response.status_code == 200
    assert "188" in body["reply"]["text"]
    assert body["reply"]["blocked"] is True
    stored_user = messages(connected)[-2]
    assert stored_user["text"] == ""
    assert stored_user["blockReason"] == "self_harm"


def test_text_length_rules(client, connected):
    assert send(client, "   ").status_code == 400
    assert send(client, "x" * 1001).status_code == 400
    assert send(client, "x" * 1000).status_code == 200


def test_unknown_or_hidden_connection_is_404(client, connected):
    assert send(client, "oi", connection="rocket").status_code == 404

    connected.store.update(f"users/{UID}/matches/storm", {"hidden": True})

    assert send(client, "oi").status_code == 404


def test_same_idempotency_key_returns_same_reply_without_new_call(client, connected):
    first = send(client, "Oi", key="k1").json()
    calls = len(connected.llm.calls)

    second = send(client, "Oi", key="k1")

    assert second.status_code == 200
    assert second.json() == first
    assert len(connected.llm.calls) == calls
    assert connected.store.get(f"users/{UID}/matches/storm")["userMessageCount"] == 1


def test_provider_down_is_503_and_nothing_is_stored(client, connected):
    before = len(messages(connected))
    connected.llm.fail = True

    response = send(client, "Oi")

    assert response.status_code == 503
    assert len(messages(connected)) == before


def test_rate_limit_returns_429_with_retry_after(client, connected, clock):
    connected.settings.messages_per_hour = 2
    connected.__dict__.pop("conversation_service", None)
    send(client, "1")
    clock.current += timedelta(minutes=10)
    send(client, "2")

    response = send(client, "3")

    assert response.status_code == 429
    assert response.json()["error"] == "rate_limited"
    assert response.headers["Retry-After"] == str(50 * 60)

    clock.current += timedelta(minutes=51)
    assert send(client, "4").status_code == 200


# --- GET /v2/me/stats ---------------------------------------------------------------------


def test_stats_count_connections_messages_seen_and_teams(client, connected):
    client.post(
        "/v2/decisions", json={"characterId": "iron-man", "choice": "ASSEMBLE"}, headers=HEADERS
    )
    client.post("/v2/decisions", json={"characterId": "rocket", "choice": "PASS"}, headers=HEADERS)
    send(client, "oi")
    send(client, "tudo bem?")

    response = client.get("/v2/me/stats", headers=HEADERS)

    assert response.json() == {
        "connections": 2,
        "messagesSent": 2,
        "charactersSeen": 3,
        "distinctTeams": 2,
    }


# --- regenerar e voltar a conversa -------------------------------------------------------


def talk(client, clock, text):
    """Envia com o relógio avançando antes e depois: a ordem por createdAt fica estável."""
    clock.current += timedelta(seconds=30)
    reply = send(client, text)
    clock.current += timedelta(seconds=30)
    return reply


def regenerate(client, connection="storm"):
    return client.post(f"/v2/connections/{connection}/messages/regenerate", headers=HEADERS)


def rewind(client, message_id, connection="storm"):
    return client.post(
        f"/v2/connections/{connection}/messages/rewind",
        json={"messageId": message_id},
        headers=HEADERS,
    )


def message_ids(container, connection="storm"):
    docs = container.store.query(f"users/{UID}/matches/{connection}/messages", order_by="createdAt")
    return [message_id for message_id, _ in docs]


def test_regenerate_replaces_the_last_reply_in_place(client, connected, clock):
    first = talk(client, clock, "Oi, tudo bem?").json()
    before = message_ids(connected)

    response = regenerate(client)

    assert response.status_code == 200
    body = response.json()
    assert body["reply"]["id"] == first["reply"]["id"]
    assert body["reply"]["author"] == "CHARACTER"
    assert message_ids(connected) == before
    stored = connected.store.get(f"users/{UID}/matches/storm/messages/{body['reply']['id']}")
    assert stored["text"] == body["reply"]["text"]
    assert "regeneratedAt" in stored
    assert len(body["suggestions"]) == 3


def test_regenerate_asks_the_model_for_the_same_user_message(client, connected, clock):
    talk(client, clock, "Qual é o seu maior sonho?")
    connected.llm.calls.clear()

    regenerate(client)

    messages_sent = connected.llm.calls[-1]["messages"]
    assert messages_sent[-1]["role"] == "user"
    assert messages_sent[-1]["content"].startswith("Qual é o seu maior sonho?")
    assert [m["role"] for m in messages_sent].count("assistant") == 1  # só a fala de abertura


def test_regenerate_the_opener_when_the_chat_has_only_that(client, connected, clock):
    opener_ids = message_ids(connected)
    assert len(opener_ids) == 1

    response = regenerate(client)

    assert response.status_code == 200
    assert response.json()["reply"]["id"] == opener_ids[0]
    assert connected.llm.calls[-1]["messages"][-1]["content"].startswith("The user and")


def test_regenerate_does_not_count_as_a_new_user_message(client, connected, clock):
    talk(client, clock, "Oi")
    count_before = connected.store.get(f"users/{UID}/matches/storm")["userMessageCount"]

    regenerate(client)

    assert connected.store.get(f"users/{UID}/matches/storm")["userMessageCount"] == count_before


def test_regenerate_without_a_character_reply_is_409(client, connected, clock):
    talk(client, clock, "meu email é fulano@exemplo.com")  # recusada: fica só a mensagem do usuário

    response = regenerate(client)

    assert response.status_code == 409
    assert response.json()["error"] == "nothing_to_regenerate"


def test_regenerate_unknown_connection_is_404(client, connected, clock):
    assert regenerate(client, connection="wolverine").status_code == 404


def test_regenerate_provider_failure_keeps_the_old_reply(client, connected, clock):
    reply = talk(client, clock, "Oi").json()["reply"]
    connected.llm.fail = True

    response = regenerate(client)

    assert response.status_code == 503
    stored = connected.store.get(f"users/{UID}/matches/storm/messages/{reply['id']}")
    assert stored["text"] == reply["text"]


def test_rewind_deletes_everything_after_the_chosen_reply(client, connected, clock):
    first = talk(client, clock, "Primeira").json()
    talk(client, clock, "Segunda")
    talk(client, clock, "Terceira")

    response = rewind(client, first["reply"]["id"])

    assert response.status_code == 204
    kept = message_ids(connected)
    assert kept[-1] == first["reply"]["id"]
    assert len(kept) == 3  # abertura, primeira pergunta e a resposta dela
    match = connected.store.get(f"users/{UID}/matches/storm")
    assert match["userMessageCount"] == 1
    assert len(match["suggestions"]) == 3


def test_rewind_to_the_opener_keeps_only_the_opener(client, connected, clock):
    opener = message_ids(connected)[0]
    talk(client, clock, "Oi")

    assert rewind(client, opener).status_code == 204

    assert message_ids(connected) == [opener]
    assert connected.store.get(f"users/{UID}/matches/storm")["userMessageCount"] == 0


def test_rewind_only_to_a_character_message(client, connected, clock):
    sent = talk(client, clock, "Oi").json()

    response = rewind(client, sent["userMessage"]["id"])

    assert response.status_code == 400
    assert len(message_ids(connected)) == 3


def test_rewind_unknown_message_is_404(client, connected, clock):
    assert rewind(client, "m_inexistente").status_code == 404


def test_rewound_messages_are_not_in_the_model_history(client, connected, clock):
    first = talk(client, clock, "Primeira").json()
    talk(client, clock, "Segunda pergunta apagada")
    rewind(client, first["reply"]["id"])
    connected.llm.calls.clear()

    talk(client, clock, "Nova pergunta")

    sent_texts = [m["content"] for m in connected.llm.calls[-1]["messages"]]
    assert not any("Segunda pergunta apagada" in text for text in sent_texts)


def test_concurrent_requests_with_the_same_key_are_processed_once(client, connected, clock):
    import threading
    import time

    from tests.fakes import FakeLlm, chat_reply

    def slow(messages):
        time.sleep(0.3)
        return chat_reply(messages)

    connected.llm.__dict__.update(FakeLlm(slow).__dict__)
    connected.llm.calls.clear()
    clock.current += timedelta(seconds=30)
    results = []

    def call():
        results.append(send(client, "Oi, Storm!", key="same-key"))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json()["reply"]["id"] == results[1].json()["reply"]["id"]
    assert len(connected.llm.calls) == 1
    assert len(message_ids(connected)) == 3  # abertura, mensagem e resposta, uma vez só
