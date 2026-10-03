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


def test_parse_json_object_tolerates_text_around_the_object():
    wrapped = 'Aqui está o resultado:\n{"voice": "calma", "values": ["a"]}\nEspero que ajude!'

    assert parse_json_object(wrapped) == {"voice": "calma", "values": ["a"]}
    with pytest.raises(InvalidModelOutputError):
        parse_json_object("sem objeto nenhum")
    with pytest.raises(InvalidModelOutputError):
        parse_json_object("texto { quebrado")


def test_invalid_persona_output_is_logged_with_a_preview(with_llm, caplog):
    with_llm.llm = FakeLlm("resposta sem json " * 40)

    with caplog.at_level("WARNING", logger="app.ai.personas"):
        with_llm.persona_service.run()

    messages = [r.getMessage() for r in caplog.records if "Saída inválida" in r.getMessage()]
    assert messages and "resposta sem json" in messages[0]
    assert len(messages[0]) < 600


def test_batch_timeout_reaches_the_model_call(with_llm):
    captured = []
    original = with_llm.llm.complete

    def spy(models, messages, **kwargs):
        captured.append(kwargs.get("timeout"))
        return original(models, messages, **kwargs)

    with_llm.llm.complete = spy
    with_llm.settings.batch_llm_timeout_seconds = 77.0
    with_llm.__dict__.pop("persona_service", None)

    with_llm.persona_service.run()

    assert captured and set(captured) == {77.0}


def test_persona_retries_once_when_the_model_answers_with_a_list(with_llm):
    answers = iter(["[]", json_reply(SHEET)])
    with_llm.llm = FakeLlm(lambda messages: next(answers))
    with_llm.settings.persona_batch_size = 1

    report = with_llm.persona_service.run()

    assert len(report.generated) == 1 and report.failed == []
    assert len(with_llm.llm.calls) == 2


def test_persona_gives_up_after_two_invalid_answers(with_llm):
    with_llm.llm = FakeLlm("[]")
    with_llm.settings.persona_batch_size = 1

    report = with_llm.persona_service.run()

    assert report.generated == [] and len(report.failed) == 1
    assert len(with_llm.llm.calls) == 2


def test_persona_prompt_asks_for_a_single_object_with_the_expected_keys():
    from app.ai.personas import SYSTEM_PROMPT

    assert "UM objeto JSON (nunca uma lista" in SYSTEM_PROMPT
    assert '{"voice": "..."' in SYSTEM_PROMPT


def test_failure_description_hides_the_reason_in_private_chat():
    from app.ai.llm import describe_failure

    error = litellm.exceptions.RateLimitError(
        message="limite do plano atingido: texto do usuário", llm_provider="openai", model="m"
    )

    assert "texto do usuário" not in describe_failure(error, private=True)
    assert "HTTP 429" in describe_failure(error, private=True)
    batch = describe_failure(error, private=False)
    assert "RateLimitError" in batch and "limite do plano atingido" in batch
