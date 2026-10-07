"""Mensagens das conexões: fala de abertura do personagem e respostas (seção 10)."""

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.ai.chat import BlockedInputError, ChatEngine, ChatRequest, ChatResult, character_context
from app.ai.guardrail import GuardrailUnavailableError
from app.ai.llm import InvalidModelOutputError, LlmUnavailableError
from app.ai.memory import MemorySummarizer
from app.ai.prompts import fallback_suggestions, preview
from app.api.schemas import Message, RegeneratedReply
from app.clock import Clock
from app.domain.enums import Author
from app.errors import ApiError
from app.rate_limit import SlidingWindowLimiter
from app.repositories import (
    CharacterRepository,
    MatchRepository,
    MessageRepository,
    PersonaRepository,
    UserRepository,
)
from app.store.base import DELETE_FIELD, DocumentNotFoundError, Increment
from app.timing import timed
from app.work_queue import WorkQueue

logger = logging.getLogger(__name__)
timing_logger = logging.getLogger("app.timing")

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"
# Fila cheia: o app tenta de novo depois deste tempo, com a mesma Idempotency-Key.
QUEUE_FULL_RETRY_AFTER = 10
PROVIDER_ERRORS = (LlmUnavailableError, GuardrailUnavailableError, InvalidModelOutputError)
# Garante que a resposta fique depois da mensagem do usuário na ordenação por createdAt.
REPLY_MIN_GAP = timedelta(milliseconds=1)


def memorable(docs: list) -> list:
    """Mensagens que entram no resumo: com texto e não ocultas (as bloqueadas não têm texto)."""
    return [(i, doc) for i, doc in docs if doc.get("text") and not doc.get("hidden")]


def memory_text(match: dict[str, Any] | None) -> str | None:
    return ((match or {}).get("memory") or {}).get("text") or None


def new_message_id() -> str:
    return f"m_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class ReplyJob:
    """Resposta a gerar na fila. O texto só fica em memória até passar pelo filtro de entrada."""

    uid: str
    connection_id: str
    message_id: str
    text: str
    locale: str
    user_at: datetime


def pending_user_message(created_at: datetime, idempotency_key: str) -> dict[str, Any]:
    return {
        "author": Author.USER.value,
        "text": "",
        "createdAt": created_at,
        "status": STATUS_PENDING,
        "fictional": False,
        "blocked": False,
        "hidden": False,
        "idempotencyKey": idempotency_key,
    }


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
        users: UserRepository,
        limiter: SlidingWindowLimiter,
        clock: Clock,
        history_limit: int,
        replies: WorkQueue,
        background: WorkQueue,
        memory: MemorySummarizer | None = None,
        memory_batch: int = 10,
        memory_chunk: int = 30,
    ) -> None:
        self._chat = chat
        self._personas = personas
        self._characters = characters
        self._matches = matches
        self._messages = messages
        self._users = users
        self._limiter = limiter
        self._clock = clock
        self._history_limit = history_limit
        self._memory = memory
        self._memory_batch = memory_batch
        self._memory_chunk = memory_chunk
        self._memory_running: set[tuple[str, str]] = set()
        self._replies = replies
        self._background = background
        self._conversation_locks: dict[tuple[str, str], list[Any]] = {}
        # (uid, conversa) -> id da mensagem do usuário que está na fila.
        self._queued: dict[tuple[str, str], str] = {}
        self._locks_guard = threading.Lock()

    def generate_opener(
        self, uid: str, character_id: str, character: dict[str, Any], locale: str
    ) -> ChatResult:
        request = ChatRequest(
            request_id=str(uuid.uuid4()),
            mode="opener",
            locale=locale,
            character=character_context(character_id, character, locale),
            persona=self._personas.get(character_id) or {},
            looking_for=self._users.looking_for(uid),
        )
        with provider_errors_as_api_errors(), timed("fala de abertura (total)"):
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
    ) -> Message:
        """Grava a mensagem como pendente e põe a resposta na fila; devolve a mensagem do usuário.

        A resposta do personagem chega pelo Firestore. A mensagem pendente é gravada sem o texto:
        ele só vai para o Firestore depois de passar pelo filtro de entrada.
        """
        self._open_connection(uid, connection_id)
        self._engine()
        key = idempotency_key or new_message_id()
        with self._serialized((uid, connection_id)):
            found = self._messages.by_idempotency_key(uid, connection_id, key)
            if found:
                message_id, doc = found[0]
                return self._resume(uid, connection_id, message_id, doc, text, locale)
            self._ensure_idle(uid, connection_id)
            self._hit_rate_limit(uid)
            user_at = self._clock.now()
            message_id = new_message_id()
            doc = pending_user_message(user_at, key)
            self._messages.add(uid, connection_id, message_id, doc)
            self._enqueue(ReplyJob(uid, connection_id, message_id, text, locale, user_at))
            return to_message(message_id, connection_id, {**doc, "text": text})

    def _resume(
        self,
        uid: str,
        connection_id: str,
        message_id: str,
        doc: dict[str, Any],
        text: str,
        locale: str,
    ) -> Message:
        """Mesma Idempotency-Key: devolve o estado gravado ou retoma o que falhou ou se perdeu.

        Uma mensagem pendente fora da fila ficou órfã (o processo reiniciou) e volta para a fila.
        """
        status = doc.get("status")
        retry = status == STATUS_FAILED or (
            status == STATUS_PENDING and not self._is_queued(uid, connection_id, message_id)
        )
        if retry:
            self._ensure_idle(uid, connection_id)
            self._hit_rate_limit(uid)
            self._messages.update(
                uid,
                connection_id,
                message_id,
                {"status": STATUS_PENDING, "errorCode": DELETE_FIELD},
            )
            job = ReplyJob(uid, connection_id, message_id, text, locale, doc["createdAt"])
            self._enqueue(job)
            doc = {**doc, "status": STATUS_PENDING}
        return to_message(message_id, connection_id, {**doc, "text": doc.get("text") or text})

    @contextmanager
    def _serialized(self, key: tuple[str, str]) -> Iterator[None]:
        """Envios da mesma conversa, um por vez: a repetição de um pedido que estourou o tempo
        não pode correr junto com o original (a mensagem entraria duas vezes na fila)."""
        with self._locks_guard:
            entry = self._conversation_locks.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._locks_guard:
                entry[1] -= 1
                if entry[1] == 0:
                    self._conversation_locks.pop(key, None)

    def _is_queued(self, uid: str, connection_id: str, message_id: str) -> bool:
        with self._locks_guard:
            return self._queued.get((uid, connection_id)) == message_id

    def _ensure_idle(self, uid: str, connection_id: str) -> None:
        """Uma resposta pendente por conversa: ninguém ocupa a fila com uma rajada de mensagens."""
        with self._locks_guard:
            if (uid, connection_id) in self._queued:
                raise ApiError("reply_pending")

    def _enqueue(self, job: ReplyJob) -> None:
        key = (job.uid, job.connection_id)
        with self._locks_guard:
            self._queued[key] = job.message_id
        queued_at = time.perf_counter()
        if self._replies.submit(lambda: self._answer(job, queued_at)):
            return
        with self._locks_guard:
            self._queued.pop(key, None)
        self._settle(job, {"status": STATUS_FAILED, "errorCode": "provider_unavailable"})
        raise ApiError("provider_unavailable", headers={"Retry-After": str(QUEUE_FULL_RETRY_AFTER)})

    def _answer(self, job: ReplyJob, queued_at: float) -> None:
        """Roda na fila: gera a resposta, grava a troca e agenda o resumo da conversa.

        Qualquer falha marca a mensagem como `failed`: ela nunca fica pendente para sempre.
        """
        timing_logger.info("tempo espera na fila: %d ms", (time.perf_counter() - queued_at) * 1000)
        try:
            self._reply(job)
        except Exception:
            logger.exception("Resposta do chat falhou sem tratamento.")
            self._settle(job, {"status": STATUS_FAILED, "errorCode": "provider_unavailable"})
        finally:
            with self._locks_guard:
                self._queued.pop((job.uid, job.connection_id), None)
        self._background.submit(lambda: self.refresh_memory(job.uid, job.connection_id, job.locale))

    def _reply(self, job: ReplyJob) -> None:
        match = self._matches.get(job.uid, job.connection_id)
        character = self._characters.get(job.connection_id)
        if match is None or match.get("hidden") or character is None:
            logger.info("Resposta descartada: a conversa não está mais aberta.")
            return
        if self._messages.get(job.uid, job.connection_id, job.message_id) is None:
            logger.info("Resposta descartada: a mensagem do usuário foi apagada.")
            return
        request = ChatRequest(
            request_id=str(uuid.uuid4()),
            mode="reply",
            locale=job.locale,
            character=character_context(job.connection_id, character, job.locale),
            persona=self._personas.get(job.connection_id) or {},
            history=self._history(job.uid, job.connection_id),
            message=job.text,
            memory=memory_text(match),
        )
        try:
            with timed("resposta do chat (total)"):
                result = self._engine().respond(request)
        except BlockedInputError as exc:
            self._settle(
                job, {"status": STATUS_BLOCKED, "blocked": True, "blockReason": exc.reason}
            )
            return
        except (*PROVIDER_ERRORS, ApiError) as exc:
            logger.warning("Resposta do chat falhou: %s", type(exc).__name__)
            self._settle(job, {"status": STATUS_FAILED, "errorCode": "provider_unavailable"})
            return
        with timed("gravacao da troca"):
            self._save_exchange(job, result)

    def _settle(self, job: ReplyJob, fields: dict[str, Any]) -> bool:
        """Atualiza a mensagem do usuário; False se ela já não existe (voltar a conversa, conta
        apagada): nesse caso nada mais é gravado."""
        try:
            self._messages.update(job.uid, job.connection_id, job.message_id, fields)
        except DocumentNotFoundError:
            logger.info("Resposta descartada: a mensagem do usuário foi apagada.")
            return False
        return True

    def regenerate(self, uid: str, connection_id: str, locale: str) -> RegeneratedReply:
        """Gera outra resposta no lugar da última do personagem (mesma mensagem, texto novo)."""
        character = self._open_connection(uid, connection_id)
        visible = [
            (message_id, doc)
            for message_id, doc in self._messages.recent(
                uid, connection_id, self._history_limit + 2
            )
            if not doc.get("hidden")
        ]
        if not visible or visible[-1][1].get("author") != Author.CHARACTER.value:
            raise ApiError("nothing_to_regenerate")
        last_id, last_doc = visible[-1]
        earlier = visible[:-1]
        if not earlier:
            mode, text, history_docs = "opener", "", []
        elif earlier[-1][1].get("author") == Author.USER.value and earlier[-1][1].get("text"):
            mode, text, history_docs = "reply", earlier[-1][1]["text"], earlier[:-1]
        else:
            raise ApiError("nothing_to_regenerate")
        self._hit_rate_limit(uid)

        request = ChatRequest(
            request_id=str(uuid.uuid4()),
            mode=mode,
            locale=locale,
            character=character_context(connection_id, character, locale),
            persona=self._personas.get(connection_id) or {},
            history=self._history_from(history_docs),
            message=text,
            looking_for=self._users.looking_for(uid) if mode == "opener" else None,
            memory=memory_text(self._matches.get(uid, connection_id)),
        )
        try:
            with provider_errors_as_api_errors():
                result = self._engine().respond(request)
        except BlockedInputError as exc:
            raise ApiError("blocked_content") from exc

        now = self._clock.now()
        self._messages.update(
            uid,
            connection_id,
            last_id,
            {
                "text": result.reply,
                "blocked": result.blocked,
                "blockReason": result.block_reason or DELETE_FIELD,
                "model": result.model,
                "promptVersion": result.prompt_version,
                "regeneratedAt": now,
            },
        )
        self._matches.update(
            uid,
            connection_id,
            {"lastMessagePreview": preview(result.reply), "suggestions": result.suggestions},
        )
        updated = {**last_doc, "text": result.reply, "blocked": result.blocked}
        return RegeneratedReply(
            reply=to_message(last_id, connection_id, updated), suggestions=result.suggestions
        )

    def rewind(self, uid: str, connection_id: str, message_id: str, locale: str) -> None:
        """Volta a conversa até uma resposta do personagem: apaga tudo o que veio depois."""
        character = self._open_connection(uid, connection_id)
        docs = self._messages.all_in_order(uid, connection_id)
        position = next((i for i, (found, _) in enumerate(docs) if found == message_id), None)
        if position is None:
            raise ApiError("not_found")
        target = docs[position][1]
        if target.get("author") != Author.CHARACTER.value or target.get("hidden"):
            raise ApiError("invalid_request")
        for removed_id, _ in docs[position + 1 :]:
            self._messages.delete(uid, connection_id, removed_id)
        kept = docs[: position + 1]
        match = self._matches.get(uid, connection_id) or {}
        # Um resumo que cobre mensagens apagadas lembraria do que não aconteceu mais.
        memory_stale = (match.get("memory") or {}).get("folded", 0) > len(memorable(kept))
        sent = sum(
            1 for _, doc in kept if doc.get("author") == Author.USER.value and doc.get("replyId")
        )
        self._matches.update(
            uid,
            connection_id,
            {
                "lastMessageAt": target["createdAt"],
                "lastMessagePreview": preview(target.get("text", "")),
                "suggestions": fallback_suggestions(character, locale),
                "userMessageCount": sent,
                **({"memory": DELETE_FIELD} if memory_stale else {}),
            },
        )

    def refresh_memory(self, uid: str, connection_id: str, locale: str) -> None:
        """Dobra no resumo as mensagens que saíram da janela do histórico (roda em segundo plano).

        Nunca levanta: se falhar, o chat segue como está e a próxima chamada tenta de novo.
        """
        if self._memory is None:
            return
        key = (uid, connection_id)
        with self._locks_guard:
            if key in self._memory_running:
                return
            self._memory_running.add(key)
        try:
            self._fold_into_memory(uid, connection_id, locale)
        except (LlmUnavailableError, GuardrailUnavailableError, InvalidModelOutputError):
            logger.warning("Resumo da conversa adiado: provedor indisponível.")
        except Exception:
            logger.exception("Resumo da conversa falhou.")
        finally:
            with self._locks_guard:
                self._memory_running.discard(key)

    def _fold_into_memory(self, uid: str, connection_id: str, locale: str) -> None:
        match = self._matches.get(uid, connection_id)
        if match is None or match.get("hidden") or self._memory is None:
            return
        stored = match.get("memory") or {}
        folded = stored.get("folded", 0)
        # Estimativa barata, sem ler a conversa: 2 mensagens por envio mais a abertura.
        estimate = 2 * match.get("userMessageCount", 0) + 1 - self._history_limit - folded
        if estimate < self._memory_batch:
            return
        character = self._characters.get(connection_id)
        if character is None:
            return
        docs = self._messages.all_in_order(uid, connection_id)
        older = memorable(docs[: max(0, len(docs) - self._history_limit)])
        pending = older[folded:]
        text = stored.get("text")
        name = character_context(connection_id, character, locale)["name"]
        while len(pending) >= self._memory_batch:
            chunk, pending = pending[: self._memory_chunk], pending[self._memory_chunk :]
            with timed("resumo da conversa"):
                updated = self._memory.fold(text, self._history_from(chunk), name, locale)
            if updated is None:
                return
            text, folded = updated, folded + len(chunk)
            self._matches.update(
                uid,
                connection_id,
                {"memory": {"text": text, "folded": folded, "updatedAt": self._clock.now()}},
            )

    def _open_connection(self, uid: str, connection_id: str) -> dict[str, Any]:
        match = self._matches.get(uid, connection_id)
        if match is None or match.get("hidden"):
            raise ApiError("not_found")
        character = self._characters.get(connection_id)
        if character is None:
            raise ApiError("not_found")
        return character

    def _hit_rate_limit(self, uid: str) -> None:
        retry_after = self._limiter.hit(uid)
        if retry_after is not None:
            raise ApiError("rate_limited", headers={"Retry-After": str(retry_after)})

    def _save_exchange(self, job: ReplyJob, result: ChatResult) -> None:
        match = self._matches.get(job.uid, job.connection_id)
        if match is None or match.get("hidden"):
            logger.info("Resposta descartada: a conversa foi apagada enquanto era gerada.")
            return
        reply_at = max(self._clock.now(), job.user_at + REPLY_MIN_GAP)
        reply_id = new_message_id()
        input_blocked = result.blocked and result.block_reason == "self_harm"
        user_fields: dict[str, Any] = {
            # Texto recusado pelo guardrail nunca é guardado, só o motivo.
            "text": "" if input_blocked else job.text,
            "status": STATUS_BLOCKED if input_blocked else STATUS_SENT,
            "blocked": input_blocked,
            "replyId": reply_id,
        }
        if input_blocked:
            user_fields["blockReason"] = result.block_reason
        if not self._settle(job, user_fields):
            return
        self._messages.add(
            job.uid, job.connection_id, reply_id, character_message(result, reply_at)
        )
        self._matches.update(
            job.uid,
            job.connection_id,
            {
                "lastMessageAt": reply_at,
                "lastMessagePreview": preview(result.reply),
                "suggestions": result.suggestions,
                "userMessageCount": Increment(1),
            },
        )

    def _history(self, uid: str, connection_id: str) -> list[dict[str, str]]:
        return self._history_from(self._messages.recent(uid, connection_id, self._history_limit))

    @staticmethod
    def _history_from(docs: list) -> list[dict[str, str]]:
        history = []
        for _, doc in docs:
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
        status=doc.get("status", STATUS_SENT),
    )
