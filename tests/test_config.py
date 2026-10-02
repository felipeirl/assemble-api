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
