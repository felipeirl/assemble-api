from app.config import Settings


def test_settings_read_values_from_environment(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "modelo-teste")
    monkeypatch.setenv("JOBS_KEY", "segredo")

    settings = Settings(_env_file=None)

    assert settings.chat_model == "modelo-teste"
    assert settings.jobs_key.get_secret_value() == "segredo"


def test_settings_default_timezone(monkeypatch):
    monkeypatch.delenv("DEFAULT_TIMEZONE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.default_timezone == "America/Sao_Paulo"


def test_settings_hide_secrets_in_repr(monkeypatch):
    monkeypatch.setenv("COMMANDCODE_API_KEY", "chave-secreta")

    settings = Settings(_env_file=None)

    assert "chave-secreta" not in repr(settings)


def test_blank_values_from_env_example_count_as_unset(monkeypatch):
    monkeypatch.setenv("COMICVINE_API_KEY", "")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    monkeypatch.setenv("MESSAGES_PER_HOUR", "")

    settings = Settings(_env_file=None)

    assert settings.comicvine_api_key is None
    assert settings.firebase_service_account_json is None
    assert settings.messages_per_hour == 60


def test_chat_models_that_train_on_data_are_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="não pode ser usado no chat"):
        Settings(_env_file=None, chat_model="meta/muse-spark-1.3-contributor")
    with pytest.raises(ValidationError, match="não pode ser usado no chat"):
        Settings(_env_file=None, chat_fallback_model="meta/Muse-Spark-Contributor")


def test_contributor_model_is_still_allowed_for_public_persona_data():
    settings = Settings(_env_file=None, persona_model="meta/muse-spark-1.3-contributor")

    assert settings.persona_model == "meta/muse-spark-1.3-contributor"
