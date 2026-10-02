from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

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

    # Baralho diário (seção 8)
    deck_size: int = 30
    catalog_cache_seconds: int = 600

    # IA (seções 9.3 e 10)
    llm_timeout_seconds: float = 30.0
    persona_batch_size: int = 20
    guardrail_enabled: bool = True
    guardrail_threshold: float = 0.5
    chat_history_limit: int = 20
    messages_per_hour: int = 60

    # Decisão de match (seção 7) — valores iniciais, a calibrar
    match_weight_compatibility: float = 0.6
    match_weight_affinity: float = 0.3
    match_weight_chance: float = 0.1
    match_cutoff: float = 0.55


@lru_cache
def get_settings() -> Settings:
    return Settings()
