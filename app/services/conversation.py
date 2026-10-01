"""Mensagens das conexões: fala de abertura do personagem e respostas (seção 10)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from app.ai.chat import BlockedInputError, ChatEngine, ChatRequest, ChatResult, character_context
from app.ai.guardrail import GuardrailUnavailableError
from app.ai.llm import InvalidModelOutputError, LlmUnavailableError
from app.ai.prompts import preview
from app.api.schemas import CharacterReply, Message
from app.clock import Clock
from app.domain.enums import Author
from app.errors import ApiError
from app.rate_limit import SlidingWindowLimiter
from app.repositories import (
    CharacterRepository,
    MatchRepository,
    MessageRepository,
    PersonaRepository,
)
from app.store.base import Increment

STATUS_SENT = "sent"
STATUS_BLOCKED = "blocked"
PROVIDER_ERRORS = (LlmUnavailableError, GuardrailUnavailableError, InvalidModelOutputError)
# Garante que a resposta fique depois da mensagem do usuário na ordenação por createdAt.
REPLY_MIN_GAP = timedelta(milliseconds=1)


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
        characters: CharacterRepository,
        matches: MatchRepository,
        messages: MessageRepository,
        limiter: SlidingWindowLimiter,
        clock: Clock,
        history_limit: int,
    ) -> None:
        self._chat = chat
        self._personas = personas
        self._characters = characters
        self._matches = matches
        self._messages = messages
        self._limiter = limiter
        self._clock = clock
        self._history_limit = history_limit

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

    def send(
        self,
        uid: str,
        connection_id: str,
        text: str,
        idempotency_key: str | None,
        locale: str,
    ) -> CharacterReply:
        match = self._matches.get(uid, connection_id)
        if match is None or match.get("hidden"):
            raise ApiError("not_found")
        if idempotency_key is not None:
            replayed = self._replay(uid, connection_id, text, idempotency_key)
            if replayed is not None:
                return replayed
        character = self._characters.get(connection_id)
        if character is None:
            raise ApiError("not_found")
        retry_after = self._limiter.hit(uid)
        if retry_after is not None:
            raise ApiError("rate_limited", headers={"Retry-After": str(retry_after)})

        user_at = self._clock.now()
        request = ChatRequest(
            request_id=str(uuid.uuid4()),
            mode="reply",
            locale=locale,
            character=character_context(connection_id, character),
            persona=self._personas.get(connection_id) or {},
            history=self._history(uid, connection_id),
            message=text,
        )
        try:
            with provider_errors_as_api_errors():
                result = self._engine().respond(request)
        except BlockedInputError as exc:
            self._save_blocked_input(uid, connection_id, exc.reason, user_at, idempotency_key)
            raise ApiError("blocked_content") from exc
        return self._save_exchange(uid, connection_id, text, result, user_at, idempotency_key)

    def _save_exchange(
        self,
        uid: str,
        connection_id: str,
        text: str,
        result: ChatResult,
        user_at: datetime,
        idempotency_key: str | None,
    ) -> CharacterReply:
        reply_at = max(self._clock.now(), user_at + REPLY_MIN_GAP)
        user_id, reply_id = new_message_id(), new_message_id()
        input_blocked = result.blocked and result.block_reason == "self_harm"
        user_doc: dict[str, Any] = {
            "author": Author.USER.value,
            # Texto recusado pelo guardrail nunca é guardado, só o motivo.
            "text": "" if input_blocked else text,
            "createdAt": user_at,
            "status": STATUS_BLOCKED if input_blocked else STATUS_SENT,
            "fictional": False,
            "blocked": input_blocked,
            "hidden": False,
            "replyId": reply_id,
        }
        if input_blocked:
            user_doc["blockReason"] = result.block_reason
        if idempotency_key is not None:
            user_doc["idempotencyKey"] = idempotency_key
        reply_doc = character_message(result, reply_at)

        self._messages.add(uid, connection_id, user_id, user_doc)
        self._messages.add(uid, connection_id, reply_id, reply_doc)
        self._matches.update(
            uid,
            connection_id,
            {
                "lastMessageAt": reply_at,
                "lastMessagePreview": preview(result.reply),
                "suggestions": result.suggestions,
                "userMessageCount": Increment(1),
            },
        )
        return CharacterReply(
            userMessage=to_message(user_id, connection_id, {**user_doc, "text": text}),
            reply=to_message(reply_id, connection_id, reply_doc),
            suggestions=result.suggestions,
        )

    def _save_blocked_input(
        self,
        uid: str,
        connection_id: str,
        reason: str,
        created_at: datetime,
        idempotency_key: str | None,
    ) -> None:
        doc: dict[str, Any] = {
            "author": Author.USER.value,
            "text": "",
            "createdAt": created_at,
            "status": STATUS_BLOCKED,
            "fictional": False,
            "blocked": True,
            "blockReason": reason,
            "hidden": False,
        }
        if idempotency_key is not None:
            doc["idempotencyKey"] = idempotency_key
        self._messages.add(uid, connection_id, new_message_id(), doc)

    def _replay(
        self, uid: str, connection_id: str, text: str, idempotency_key: str
    ) -> CharacterReply | None:
        """Mesma Idempotency-Key devolve a mesma resposta, sem chamar o modelo de novo."""
        found = self._messages.by_idempotency_key(uid, connection_id, idempotency_key)
        if not found:
            return None
        user_id, user_doc = found[0]
        if user_doc.get("replyId") is None:
            raise ApiError("blocked_content")
        reply_doc = self._messages.get(uid, connection_id, user_doc["replyId"])
        if reply_doc is None:
            return None
        match = self._matches.get(uid, connection_id) or {}
        shown_text = user_doc["text"] or text
        return CharacterReply(
            userMessage=to_message(user_id, connection_id, {**user_doc, "text": shown_text}),
            reply=to_message(user_doc["replyId"], connection_id, reply_doc),
            suggestions=match.get("suggestions") or [],
        )

    def _history(self, uid: str, connection_id: str) -> list[dict[str, str]]:
        history = []
        for _, doc in self._messages.recent(uid, connection_id, self._history_limit):
            if not doc.get("text") or doc.get("hidden"):
                continue
            role = "user" if doc.get("author") == Author.USER.value else "character"
            history.append({"role": role, "text": doc["text"]})
        return history

    def _engine(self) -> ChatEngine:
        if self._chat is None:
            raise ApiError("provider_unavailable")
        return self._chat


def character_message(result: ChatResult, created_at: datetime) -> dict[str, Any]:
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


def to_message(message_id: str, connection_id: str, doc: dict[str, Any]) -> Message:
    return Message(
        id=message_id,
        connectionId=connection_id,
        author=doc["author"],
        text=doc["text"],
        createdAt=doc["createdAt"],
        fictional=bool(doc.get("fictional")),
        blocked=bool(doc.get("blocked")),
    )
