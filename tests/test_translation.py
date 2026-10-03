import json

import pytest

from app.ai.llm import InvalidModelOutputError
from app.ai.translations import (
    is_pending,
    source_fields,
    source_hash,
    validate_translation,
)
from app.catalog.names import display_name, pt_br_name
from tests.conftest import JOBS_KEY, auth_header
from tests.factories import CHARACTERS, seed_characters, seed_user
from tests.fakes import FakeLlm, chat_reply, json_reply

UID = "u1"
PT = {"Accept-Language": "pt-BR"}
EN = {"Accept-Language": "en"}


@pytest.fixture
def ready(container):
    seed_characters(container.store)
    seed_user(container.store, UID)
    container.settings.persona_model = "translator"
    container.settings.match_cutoff = 0.0
    return container


def h(extra):
    return {**auth_header(UID), **extra}


# --- nomes (tabela curada) --------------------------------------------------------------------


def test_curated_names_and_fallback_to_original():
    assert display_name("storm", "Storm", "pt-BR") == "Tempestade"
    assert display_name("storm", "Storm", "en") == "Storm"
    assert display_name("rocket", "Rocket Raccoon", "pt-BR") == "Rocket Raccoon"
    assert display_name("forge-77", "Forge", "pt-BR") == "Forge"
    assert pt_br_name("nao-existe") is None


def test_deck_names_follow_accept_language(client, ready):
    portuguese = {
        c["characterId"]: c["name"] for c in client.get("/v2/deck", headers=h(PT)).json()["cards"]
    }
    english = {
        c["characterId"]: c["name"] for c in client.get("/v2/deck", headers=h(EN)).json()["cards"]
    }

    assert portuguese["storm"] == "Tempestade" and english["storm"] == "Storm"
    assert portuguese["rocket"] == english["rocket"] == "Rocket Raccoon"


def test_match_keeps_original_name_and_adds_pt_br_name_for_the_app(client, ready):
    body = client.post(
        "/v2/decisions", json={"characterId": "storm", "choice": "ASSEMBLE"}, headers=h(PT)
    ).json()

    assert body["character"]["name"] == "Tempestade"
    match = ready.store.get(f"users/{UID}/matches/storm")
    assert match["characterName"] == "Storm"
    assert match["characterNamePtBR"] == "Tempestade"


def test_match_without_curated_name_has_no_pt_br_field(client, ready):
    client.post(
        "/v2/decisions", json={"characterId": "rocket", "choice": "ASSEMBLE"}, headers=h(PT)
    )

    assert "characterNamePtBR" not in ready.store.get(f"users/{UID}/matches/rocket")


def test_chat_character_uses_the_name_of_the_conversation_language(client, ready):
    client.post("/v2/decisions", json={"characterId": "storm", "choice": "ASSEMBLE"}, headers=h(EN))
    ready.llm.calls.clear()

    client.post("/v2/connections/storm/messages", json={"text": "Oi"}, headers=h(PT))

    assert '"name": "Tempestade"' in ready.llm.calls[0]["messages"][0]["content"]


# --- tradução dos textos longos ---------------------------------------------------------------

TRANSLATED = {
    "bio": "Ororo Munroe é uma mutante que controla o clima.",
    "occupation": "Aventureira",
}


def translator_reply(messages):
    sent = json.loads(messages[-1]["content"].split("<<<TEXTOS\n")[1].split("\nTEXTOS>>>")[0])
    return json_reply({key: TRANSLATED.get(key, f"PT {value}") for key, value in sent.items()})


def with_translator(container):
    container.llm = FakeLlm(translator_reply)
    container.store.update(
        "characters/storm", {"occupation": "Adventurer", "aliases": ["Windrider"]}
    )
    container.catalog.invalidate()


def test_source_fields_exclude_aliases_and_first_appearance():
    fields = source_fields(
        {**CHARACTERS["storm"], "aliases": ["Windrider"], "occupation": "Adventurer"}
    )

    assert set(fields) == {"bio", "occupation"}


def test_pending_until_translated_and_again_when_source_changes():
    doc = {"bio": "texto"}
    assert is_pending(doc) is True
    translated = {
        **doc,
        "translations": {"pt-BR": {"bio": "x"}},
        "translationHash": source_hash(doc),
    }
    assert is_pending(translated) is False
    assert is_pending({**translated, "bio": "texto novo"}) is True
    assert is_pending({"name": "Sem texto"}) is False


def test_validation_drops_empty_oversized_and_unknown_fields():
    source = {"bio": "curto", "occupation": "Spy"}
    output = {"bio": "x" * 1000, "occupation": "Espiã", "extra": "ignorado"}

    assert validate_translation(source, output) == {"occupation": "Espiã"}
    with pytest.raises(InvalidModelOutputError):
        validate_translation(source, {"bio": "", "occupation": 3})


def test_job_translates_pending_characters_and_stores_them(client, ready):
    with_translator(ready)

    response = client.post("/jobs/translations", headers={"X-Jobs-Key": JOBS_KEY})

    assert response.status_code == 202
    storm = ready.store.get("characters/storm")
    assert storm["translations"]["pt-BR"] == {
        "bio": TRANSLATED["bio"],
        "occupation": TRANSLATED["occupation"],
    }
    assert storm["translatedBy"] == "translator"
    assert storm["aliases"] == ["Windrider"]
    assert all(call["zdr"] is False for call in ready.llm.calls)
    # Sem texto traduzível, o personagem nem entra na fila.
    assert "translations" not in ready.store.get("characters/jean-grey")


def test_job_is_idempotent_and_does_not_retranslate(client, ready):
    with_translator(ready)
    client.post("/jobs/translations", headers={"X-Jobs-Key": JOBS_KEY})
    calls = len(ready.llm.calls)

    client.post("/jobs/translations", headers={"X-Jobs-Key": JOBS_KEY})

    assert len(ready.llm.calls) == calls


def test_source_text_is_delimited_as_untrusted(client, ready):
    with_translator(ready)

    client.post("/jobs/translations", headers={"X-Jobs-Key": JOBS_KEY})

    system = ready.llm.calls[0]["messages"][0]["content"]
    assert "NÃO são confiáveis" in system
    assert "<<<TEXTOS" in ready.llm.calls[0]["messages"][1]["content"]


def test_invalid_model_output_is_not_stored(client, ready):
    ready.llm = FakeLlm("não é json")

    client.post("/jobs/translations", headers={"X-Jobs-Key": JOBS_KEY})

    assert "translations" not in ready.store.get("characters/storm")


def test_translations_job_without_model_is_503(client):
    assert client.post("/jobs/translations", headers={"X-Jobs-Key": JOBS_KEY}).status_code == 503


def test_profile_uses_translation_only_in_portuguese(client, ready):
    with_translator(ready)
    client.post("/jobs/translations", headers={"X-Jobs-Key": JOBS_KEY})
    ready.llm = FakeLlm(chat_reply)  # a fala de abertura do match usa o modelo de chat
    client.post("/v2/decisions", json={"characterId": "storm", "choice": "ASSEMBLE"}, headers=h(PT))

    portuguese = client.get("/v2/characters/storm", headers=h(PT)).json()
    english = client.get("/v2/characters/storm", headers=h(EN)).json()

    assert portuguese["name"] == "Tempestade"
    assert portuguese["facts"]["bio"] == TRANSLATED["bio"]
    assert portuguese["facts"]["occupation"] == "Aventureira"
    assert sorted(portuguese["translatedFields"]) == ["bio", "occupation"]
    # Apelidos e 1ª aparição ficam no original.
    assert portuguese["facts"]["aliases"] == ["Windrider"]
    assert portuguese["facts"]["firstAppearance"] == "Giant-Size X-Men #1"
    assert english["name"] == "Storm"
    assert english["facts"]["occupation"] == "Adventurer"
    assert "translatedFields" not in english


def test_untranslated_character_falls_back_to_original_text(client, ready):
    client.post("/v2/decisions", json={"characterId": "storm", "choice": "ASSEMBLE"}, headers=h(PT))

    body = client.get("/v2/characters/storm", headers=h(PT)).json()

    assert body["facts"]["bio"].startswith("Ororo Munroe")
    assert "translatedFields" not in body


def test_ingest_preserves_translation_fields(clock):
    from datetime import timedelta

    from app.store.memory import MemoryStore
    from tests.test_ingest import FakeSource, build_service

    store = MemoryStore()
    build_service(FakeSource(), store, clock).run()
    store.update(
        "characters/storm",
        {"translations": {"pt-BR": {"bio": "texto"}}, "translationHash": "abc"},
    )

    clock.current += timedelta(days=31)
    build_service(FakeSource(), store, clock).run()

    storm = store.get("characters/storm")
    assert storm["translations"] == {"pt-BR": {"bio": "texto"}}
    assert storm["translationHash"] == "abc"
