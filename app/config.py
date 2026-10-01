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

    # Ingestão (seção 9.1)
    ingest_max_requests_per_resource: int = 190
    ingest_request_interval_seconds: float = 1.0
    ingest_refresh_days: int = 30
    tier_b_min_appearances: int = 50
    bio_max_chars: int = 2000
    personality_max_chars: int = 2000


@lru_cache
def get_settings() -> Settings:
    return Settings()
