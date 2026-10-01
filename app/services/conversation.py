"""Mensagens das conexões: fala de abertura do personagem e respostas (seção 10)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.ai.chat import ChatEngine, ChatRequest, ChatResult, character_context
from app.ai.guardrail import GuardrailUnavailableError
from app.ai.llm import InvalidModelOutputError, LlmUnavailableError
from app.ai.prompts import preview
from app.clock import Clock
from app.domain.enums import Author
from app.errors import ApiError
from app.repositories import MatchRepository, MessageRepository, PersonaRepository

STATUS_SENT = "sent"
PROVIDER_ERRORS = (LlmUnavailableError, GuardrailUnavailableError, InvalidModelOutputError)


def new_message_id() -> str:
    return f"m_{uuid.uuid4().hex}"


@contextmanager
def provider_errors_as_api_errors() -> Iterator[None]:
    """Falha técnica do modelo ou do guardrail vira 503 provider_unavailable."""
    try:
        yield
    except PROVIDER_ERRORS as exc:
        raise ApiError("provider_unavailable") from exc


class ConversationService:
    def __init__(
        self,
        chat: ChatEngine | None,
        personas: PersonaRepository,
        matches: MatchRepository,
        messages: MessageRepository,
        clock: Clock,
    ) -> None:
        self._chat = chat
        self._personas = personas
        self._matches = matches
        self._messages = messages
        self._clock = clock

    def generate_opener(
        self, character_id: str, character: dict[str, Any], locale: str
    ) -> ChatResult:
        request = ChatRequest(
            request_id=str(uuid.uuid4()),
            mode="opener",
            locale=locale,
            character=character_context(character_id, character),
            persona=self._personas.get(character_id) or {},
        )
        with provider_errors_as_api_errors():
            return self._engine().respond(request)

    def save_opener(self, uid: str, character_id: str, result: ChatResult) -> dict[str, Any]:
        """Grava a fala de abertura e devolve os campos de conversa para `matches/{id}`."""
        now = self._clock.now()
        self._messages.add(uid, character_id, new_message_id(), character_message(result, now))
        return {
            "lastMessageAt": now,
            "lastMessagePreview": preview(result.reply),
            "suggestions": result.suggestions,
        }

    def _engine(self) -> ChatEngine:
        if self._chat is None:
            raise ApiError("provider_unavailable")
        return self._chat


def character_message(result: ChatResult, created_at) -> dict[str, Any]:
    message: dict[str, Any] = {
        "author": Author.CHARACTER.value,
        "text": result.reply,
        "createdAt": created_at,
        "status": STATUS_SENT,
        "fictional": True,
        "blocked": result.blocked,
        "model": result.model,
        "promptVersion": result.prompt_version,
        "hidden": False,
    }
    if result.block_reason:
        message["blockReason"] = result.block_reason
    return message
