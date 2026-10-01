from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    firebase_service_account_json: SecretStr | None = None
    comicvine_api_key: SecretStr | None = None
    commandcode_api_key: SecretStr | None = None
    commandcode_base_url: str | None = None
    chat_model: str | None = None
    chat_fallback_model: str | None = None
    persona_model: str | None = None
    jobs_key: SecretStr | None = None
    default_timezone: str = "America/Sao_Paulo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
