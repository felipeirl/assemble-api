import litellm
import pytest

from app.ai.llm import (
    InvalidModelOutputError,
    LiteLlmClient,
    LlmUnavailableError,
    parse_json_object,
)
from app.ai.personas import FIXED_BOUNDARIES, build_messages
from tests.conftest import JOBS_KEY
from tests.factories import CHARACTERS, seed_characters
from tests.fakes import FakeLlm, json_reply

SHEET = {
    "voice": "calma, solene, frases curtas",
    "values": ["proteger os outros", "liberdade"],
    "speechPatterns": ["trata o interlocutor com respeito formal"],
    "relationships": ["X-Men como família"],
    "boundaries": ["não fala de romance"],
    "sampleLines": ["Paciência também é um tipo de clima."],
    "styles": ["Leadership", "Idealist", "Wizardry"],
}


@pytest.fixture
def with_llm(container):
    seed_characters(container.store)
    container.settings.persona_model = "persona-model"
    container.llm = FakeLlm(json_reply(SHEET))
    return container


def test_parse_json_object_accepts_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(InvalidModelOutputError):
        parse_json_object("[1, 2]")
    with pytest.raises(InvalidModelOutputError):
        parse_json_object("não é json")


def test_prompt_delimits_untrusted_source_and_keeps_facts():
    messages = build_messages(CHARACTERS["storm"])

    user = messages[1]["content"]
    assert '"realName": "Ororo Munroe"' in user
    assert "<<<FONTE\nOroro Munroe é uma mutante" in user
    assert "NÃO confiável" in messages[0]["content"]


def test_generates_pending_personas_and_feeds_styles(with_llm, clock):
    report = with_llm.persona_service.run()

    assert sorted(report.generated) == ["iron-man", "jean-grey", "rocket", "storm"]
    persona = with_llm.store.get("personas/storm")
    assert persona["voice"] == "calma, solene, frases curtas"
    assert persona["styles"] == ["Leadership", "Idealist"]
    assert set(FIXED_BOUNDARIES) <= set(persona["boundaries"])
    assert persona["boundaries"].count("não fala de romance") == 1
    assert persona["reviewed"] is False
    assert persona["generatedBy"] == "persona-model"
    assert persona["generatedAt"] == clock.now()
    assert with_llm.store.get("characters/storm")["styles"] == ["Leadership", "Idealist"]


def test_persona_calls_never_use_user_data_and_skip_zdr(with_llm):
    with_llm.persona_service.run()

    assert all(call["zdr"] is False for call in with_llm.llm.calls)


def test_existing_personas_are_not_regenerated(with_llm):
    with_llm.store.set("personas/storm", {"id": "storm"})

    report = with_llm.persona_service.run()

    assert "storm" not in report.generated


def test_batch_size_limits_generation(with_llm):
    with_llm.settings.persona_batch_size = 1

    assert len(with_llm.persona_service.run().generated) == 1


def test_invalid_output_is_reported_and_not_saved(with_llm):
    with_llm.llm = FakeLlm("lixo")

    report = with_llm.persona_service.run()

    assert report.generated == []
    assert len(report.failed) == 4
    assert with_llm.store.get("personas/storm") is None


def test_unavailable_provider_stops_the_batch(with_llm):
    with_llm.llm = FakeLlm("", fail=True)

    report = with_llm.persona_service.run()

    assert len(report.failed) == 1


def test_jobs_personas_route(client, with_llm):
    response = client.post("/jobs/personas", headers={"X-Jobs-Key": JOBS_KEY})

    assert response.status_code == 202
    assert with_llm.store.get("personas/storm") is not None


def test_jobs_personas_without_model_is_503(client):
    assert client.post("/jobs/personas", headers={"X-Jobs-Key": JOBS_KEY}).status_code == 503


class _Choice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


def test_litellm_client_falls_back_to_reserve_model(monkeypatch):
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] == "openai/main":
            raise litellm.exceptions.ServiceUnavailableError(
                message="down", llm_provider="openai", model="main"
            )
        return _Response("oi")

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LiteLlmClient("key", "https://api.example/provider/v1", 10)

    response = client.complete(
        ["main", "reserve"],
        [{"role": "user", "content": "x"}],
        zdr=True,
        json_mode=True,
        max_tokens=10,
        temperature=0.5,
    )

    assert response.model == "reserve"
    assert calls[0]["extra_headers"] == {"x-cmd-zdr": "1"}
    assert calls[0]["api_base"] == "https://api.example/provider/v1"


def test_litellm_client_raises_when_all_models_fail(monkeypatch):
    def failing(**kwargs):
        raise litellm.exceptions.APIConnectionError(message="x", llm_provider="openai", model="m")

    monkeypatch.setattr(litellm, "completion", failing)

    with pytest.raises(LlmUnavailableError):
        LiteLlmClient("k", "u", 1).complete(
            ["a", "b"], [], zdr=False, json_mode=False, max_tokens=1, temperature=0
        )
