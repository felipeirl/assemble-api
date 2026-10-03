"""Chamada aos modelos do Command Code via LiteLLM (provedor compatível com OpenAI), com reserva."""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

# O litellm, no modo padrão, copia o .env para os.environ ao ser importado. A configuração
# vem só do pydantic-settings; sem isto, um .env local vazaria para o processo e os testes.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

import litellm  # noqa: E402

ZDR_HEADER = {"x-cmd-zdr": "1"}
OPENAI_COMPATIBLE_PREFIX = "openai/"

LITELLM_ERRORS = (
    litellm.exceptions.APIError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.Timeout,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.BadRequestError,
    litellm.exceptions.AuthenticationError,
    litellm.exceptions.NotFoundError,
)

logger = logging.getLogger(__name__)


class LlmUnavailableError(Exception):
    """Nenhum modelo (principal ou reserva) respondeu."""


class InvalidModelOutputError(Exception):
    pass


@dataclass(frozen=True)
class LlmResponse:
    content: str
    model: str


class LlmClient(Protocol):
    def complete(
        self,
        models: list[str],
        messages: list[dict[str, str]],
        *,
        zdr: bool,
        json_mode: bool,
        max_tokens: int,
        temperature: float,
    ) -> LlmResponse: ...


class LiteLlmClient:
    def __init__(self, api_key: str, base_url: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout_seconds

    def complete(
        self,
        models: list[str],
        messages: list[dict[str, str]],
        *,
        zdr: bool,
        json_mode: bool,
        max_tokens: int,
        temperature: float,
    ) -> LlmResponse:
        """Tenta cada modelo na ordem (principal, depois reserva)."""
        for model in models:
            try:
                response = litellm.completion(
                    model=OPENAI_COMPATIBLE_PREFIX + model,
                    api_base=self._base_url,
                    api_key=self._api_key,
                    messages=messages,
                    extra_headers=ZDR_HEADER if zdr else None,
                    response_format={"type": "json_object"} if json_mode else None,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=self._timeout,
                    num_retries=0,
                )
            except LITELLM_ERRORS as exc:
                logger.warning("Modelo %s falhou: %s", model, type(exc).__name__)
                continue
            content = response.choices[0].message.content or ""
            return LlmResponse(content=content, model=model)
        raise LlmUnavailableError(", ".join(models))


def parse_json_object(content: str) -> dict[str, Any]:
    """JSON da resposta do modelo, aceitando cercas ```json."""
    text = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidModelOutputError("JSON inválido") from exc
    if not isinstance(value, dict):
        raise InvalidModelOutputError("Esperado objeto JSON")
    return value
