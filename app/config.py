from functools import lru_cache

from pydantic import SecretStr, field_validator
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
    # Esforço de raciocínio por modelo de chat. Raciocinar custa de 10 a 30 s por resposta e o chat
    # precisa ser rápido; cada modelo aceita valores diferentes (o Gemini não desliga, o DeepSeek
    # sim). Modelo fora da tabela é chamado sem o parâmetro.
    chat_reasoning_efforts: dict[str, str] = {
        "google/gemini-3.8-flash": "low",
        "deepseek/deepseek-v4.1-flash": "off",
    }
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
    batch_llm_timeout_seconds: float = 300.0
    persona_batch_size: int = 20
    translation_batch_size: int = 20
    translation_concurrency: int = 1
    guardrail_enabled: bool = True
    guardrail_threshold: float = 0.5
    chat_history_limit: int = 20
    messages_per_hour: int = 60

    # Decisão de match (seção 7) — valores iniciais, a calibrar
    match_weight_compatibility: float = 0.6
    match_weight_affinity: float = 0.3
    match_weight_chance: float = 0.1
    match_cutoff: float = 0.55

    @field_validator("chat_model", "chat_fallback_model")
    @classmethod
    def _chat_model_must_not_train_on_messages(cls, value: str | None) -> str | None:
        """Modelos "contributor" treinam com o que recebem: proibidos no chat (mensagens de
        usuários). Eles só servem para dados públicos de personagens (PERSONA_MODEL)."""
        if value and "contributor" in value.lower():
            raise ValueError(
                f"{value!r} treina com os dados enviados e não pode ser usado no chat. "
                "Use um modelo com retenção zero, como qwen/qwen3.7-flash."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
