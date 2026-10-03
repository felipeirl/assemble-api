"""Chamada aos modelos do Command Code via LiteLLM (provedor compatível com OpenAI), com reserva."""

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

# O litellm, no modo padrão, copia o .env para os.environ ao ser importado. A configuração
# vem só do pydantic-settings; sem isto, um .env local vazaria para o processo e os testes.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

import litellm  # noqa: E402

JSON_ATTEMPTS = 2
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
    finish_reason: str | None = None


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
        timeout: float | None = None,
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
        timeout: float | None = None,
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
                    timeout=timeout or self._timeout,
                    num_retries=0,
                )
            except LITELLM_ERRORS as exc:
                logger.warning("Modelo %s falhou: %s", model, type(exc).__name__)
                continue
            choice = response.choices[0]
            return LlmResponse(
                content=choice.message.content or "",
                model=model,
                finish_reason=getattr(choice, "finish_reason", None),
            )
        raise LlmUnavailableError(", ".join(models))


def complete_and_parse(
    llm: "LlmClient",
    models: list[str],
    messages: list[dict[str, str]],
    parse: Callable[[str], Any],
    subject: str,
    log: logging.Logger,
    attempts: int = JSON_ATTEMPTS,
    **kwargs: Any,
) -> tuple["LlmResponse", Any]:
    """Pede a resposta e a interpreta; se vier fora do formato, tenta de novo antes de desistir.

    Só para jobs com dados públicos (fichas, traduções): o trecho da saída inválida vai ao log.
    `parse` levanta InvalidModelOutputError ou ValueError (inclui o ValidationError do pydantic).
    """
    for attempt in range(1, attempts + 1):
        response = llm.complete(models, messages, **kwargs)
        try:
            return response, parse(response.content)
        except (InvalidModelOutputError, ValueError):
            log_invalid_output(log, subject, response)
            if attempt == attempts:
                raise
            log.info("Nova tentativa para %s (%d/%d).", subject, attempt + 1, attempts)
    raise AssertionError("attempts deve ser pelo menos 1")


def log_invalid_output(log: logging.Logger, subject: str, response: "LlmResponse") -> None:
    """Registra o começo da saída recusada. Só para jobs com dados públicos (fichas, traduções):
    nunca para o chat, onde o texto depende de mensagens de usuários."""
    log.warning(
        "Saída inválida para %s (finish_reason=%s, %d caracteres): %r",
        subject,
        response.finish_reason,
        len(response.content),
        response.content[:300],
    )


def _first_json_object(text: str) -> Any:
    """Objeto JSON entre o primeiro "{" e o último "}", quando o modelo escreve texto em volta."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise InvalidModelOutputError("JSON inválido")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise InvalidModelOutputError("JSON inválido") from exc


def parse_json_object(content: str) -> dict[str, Any]:
    """JSON da resposta do modelo, aceitando cercas ```json."""
    text = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = _first_json_object(text)
    if not isinstance(value, dict):
        raise InvalidModelOutputError("Esperado objeto JSON")
    return value
