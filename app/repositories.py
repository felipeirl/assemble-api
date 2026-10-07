"""Acesso às coleções do Firestore (seção 5 do plano), sobre o DocumentStore."""

from datetime import datetime
from typing import Any

from app.domain.models import Preferences
from app.store.base import DELETE_FIELD, Document, DocumentStore

USER_STATUS_ACTIVE = "active"
USER_STATUS_DEACTIVATED = "deactivated"
ELIGIBLE_TIERS = ["A", "B"]
# "O que você procura numa conversa?", do cadastro; o app limita, aqui só se garante.
LOOKING_FOR_MAX_CHARS = 140


def user_path(uid: str) -> str:
    return f"users/{uid}"


def decisions_path(uid: str) -> str:
    return f"users/{uid}/decisions"


def matches_path(uid: str) -> str:
    return f"users/{uid}/matches"


def messages_path(uid: str, character_id: str) -> str:
    return f"users/{uid}/matches/{character_id}/messages"


def decks_path(uid: str) -> str:
    return f"users/{uid}/decks"


def taste_signals_path(uid: str) -> str:
    return f"users/{uid}/tasteSignals"


class UserRepository:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def get(self, uid: str) -> dict[str, Any] | None:
        return self._store.get(user_path(uid))

    def preferences(self, uid: str) -> Preferences:
        user = self.get(uid) or {}
        return Preferences.model_validate(user.get("preferences") or {})

    def looking_for(self, uid: str) -> str | None:
        """Frase escrita pelo usuário: dado não confiável, checado pelo guardrail antes do uso."""
        user = self.get(uid) or {}
        text = str(user.get("lookingFor") or "").strip()[:LOOKING_FOR_MAX_CHARS]
        return text or None

    def deactivate(self, uid: str, at: datetime) -> None:
        self._store.set(
            user_path(uid),
            {"status": USER_STATUS_DEACTIVATED, "deactivatedAt": at},
            merge=True,
        )

    def reactivate(self, uid: str) -> None:
        self._store.set(
            user_path(uid),
            {"status": USER_STATUS_ACTIVE, "deactivatedAt": DELETE_FIELD},
            merge=True,
        )

    def deactivated_before(self, cutoff: datetime) -> list[str]:
        candidates = self._store.query("users", filters=(("deactivatedAt", "<", cutoff),))
        return [uid for uid, data in candidates if data.get("status") == USER_STATUS_DEACTIVATED]

    def delete_everything(self, uid: str) -> None:
        self._store.delete_tree(user_path(uid))

    def all_ids(self) -> list[str]:
        return [uid for uid, _ in self._store.query("users")]


class DecisionRepository:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def create(self, uid: str, character_id: str, data: dict[str, Any]) -> bool:
        """Grava a decisão uma única vez por par (uid, characterId)."""
        return self._store.create(f"{decisions_path(uid)}/{character_id}", data)

    def get(self, uid: str, character_id: str) -> dict[str, Any] | None:
        return self._store.get(f"{decisions_path(uid)}/{character_id}")

    def delete(self, uid: str, character_id: str) -> None:
        self._store.delete(f"{decisions_path(uid)}/{character_id}")

    def update(self, uid: str, character_id: str, data: dict[str, Any]) -> None:
        self._store.update(f"{decisions_path(uid)}/{character_id}", data)

    def unresolved(self, uid: str) -> list[Document]:
        """Assembles ainda sem resultado: pendentes ou que falharam."""
        return self._store.query(
            decisions_path(uid), filters=(("status", "in", ["pending", "failed"]),)
        )

    def decided_ids(self, uid: str) -> set[str]:
        return {doc_id for doc_id, _ in self._store.query(decisions_path(uid))}

    def count(self, uid: str) -> int:
        return self._store.count(decisions_path(uid))

    def choices(self, uid: str) -> dict[str, str]:
        """characterId -> PASS ou ASSEMBLE de todas as decisões do usuário."""
        return {
            doc_id: doc.get("choice", "") for doc_id, doc in self._store.query(decisions_path(uid))
        }

    def count_on_date(self, uid: str, date: str) -> int:
        """Decisões tomadas no dia do baralho (a cota diária descontada)."""
        return self._store.count(decisions_path(uid), filters=(("deckDate", "==", date),))


class MatchRepository:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def create(self, uid: str, character_id: str, data: dict[str, Any]) -> bool:
        return self._store.create(f"{matches_path(uid)}/{character_id}", data)

    def get(self, uid: str, character_id: str) -> dict[str, Any] | None:
        return self._store.get(f"{matches_path(uid)}/{character_id}")

    def update(self, uid: str, character_id: str, data: dict[str, Any]) -> None:
        self._store.update(f"{matches_path(uid)}/{character_id}", data)

    def for_user(self, uid: str) -> list[Document]:
        return self._store.query(matches_path(uid))

    def hidden_before(self, uid: str, cutoff: datetime) -> list[Document]:
        return self._store.query(matches_path(uid), filters=(("hiddenAt", "<", cutoff),))

    def delete_with_messages(self, uid: str, character_id: str) -> None:
        self._store.delete_tree(f"{matches_path(uid)}/{character_id}")


class MessageRepository:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def add(self, uid: str, character_id: str, message_id: str, data: dict[str, Any]) -> None:
        self._store.set(f"{messages_path(uid, character_id)}/{message_id}", data)

    def get(self, uid: str, character_id: str, message_id: str) -> dict[str, Any] | None:
        return self._store.get(f"{messages_path(uid, character_id)}/{message_id}")

    def recent(self, uid: str, character_id: str, limit: int) -> list[Document]:
        """Últimas `limit` mensagens, da mais antiga para a mais recente."""
        newest_first = self._store.query(
            messages_path(uid, character_id), order_by="createdAt", descending=True, limit=limit
        )
        return list(reversed(newest_first))

    def by_idempotency_key(self, uid: str, character_id: str, key: str) -> list[Document]:
        return self._store.query(
            messages_path(uid, character_id), filters=(("idempotencyKey", "==", key),)
        )

    def update(self, uid: str, character_id: str, message_id: str, data: dict[str, Any]) -> None:
        self._store.update(f"{messages_path(uid, character_id)}/{message_id}", data)

    def delete(self, uid: str, character_id: str, message_id: str) -> None:
        self._store.delete(f"{messages_path(uid, character_id)}/{message_id}")

    def all_in_order(self, uid: str, character_id: str) -> list[Document]:
        return self._store.query(messages_path(uid, character_id), order_by="createdAt")

    def hide_all(self, uid: str, character_id: str) -> None:
        for message_id, _ in self._store.query(messages_path(uid, character_id)):
            self._store.update(f"{messages_path(uid, character_id)}/{message_id}", {"hidden": True})


class DeckRepository:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def get(self, uid: str, date: str) -> dict[str, Any] | None:
        return self._store.get(f"{decks_path(uid)}/{date}")

    def create(self, uid: str, date: str, data: dict[str, Any]) -> bool:
        return self._store.create(f"{decks_path(uid)}/{date}", data)

    def update(self, uid: str, date: str, data: dict[str, Any]) -> None:
        self._store.update(f"{decks_path(uid)}/{date}", data)


class TasteSignalRepository:
    """Curti/Pular da rodada de reação do cadastro: ensina o gosto, não é decisão."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def save(self, uid: str, character_id: str, data: dict[str, Any]) -> None:
        self._store.set(f"{taste_signals_path(uid)}/{character_id}", data)

    def liked_by_character(self, uid: str) -> dict[str, bool]:
        return {
            doc_id: bool(doc.get("liked"))
            for doc_id, doc in self._store.query(taste_signals_path(uid))
        }


class CharacterRepository:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def get(self, character_id: str) -> dict[str, Any] | None:
        return self._store.get(f"characters/{character_id}")

    def upsert(self, character_id: str, data: dict[str, Any]) -> None:
        self._store.set(f"characters/{character_id}", data, merge=True)

    def replace(self, character_id: str, data: dict[str, Any]) -> None:
        self._store.set(f"characters/{character_id}", data)

    def eligible(self) -> list[Document]:
        return self._store.query("characters", filters=(("tier", "in", ELIGIBLE_TIERS),))

    def all_documents(self) -> list[Document]:
        return self._store.query("characters")


class PersonaRepository:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def get(self, character_id: str) -> dict[str, Any] | None:
        return self._store.get(f"personas/{character_id}")

    def save(self, character_id: str, data: dict[str, Any]) -> None:
        self._store.set(f"personas/{character_id}", data)

    def ids(self) -> set[str]:
        return {doc_id for doc_id, _ in self._store.query("personas")}

    def ids_with_prompt_version(self, prompt_version: str) -> set[str]:
        """Fichas já geradas com a versão atual do prompt; as outras são refeitas."""
        return {
            doc_id
            for doc_id, doc in self._store.query("personas")
            if doc.get("promptVersion") == prompt_version
        }


class AccessLogRepository:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    def delete_expired(self, now: datetime) -> int:
        expired = self._store.query("accessLogs", filters=(("expiresAt", "<", now),))
        for log_id, _ in expired:
            self._store.delete(f"accessLogs/{log_id}")
        return len(expired)
