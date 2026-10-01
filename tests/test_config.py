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
