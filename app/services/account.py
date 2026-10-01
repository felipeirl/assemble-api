"""Exclusão e retenção (seção 12, LGPD / Marco Civil)."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.clock import Clock
from app.errors import ApiError
from app.repositories import (
    USER_STATUS_DEACTIVATED,
    AccessLogRepository,
    MatchRepository,
    MessageRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from app.auth import TokenVerifier

GRACE_PERIOD = timedelta(days=30)

logger = logging.getLogger(__name__)


@dataclass
class PurgeReport:
    accounts_deleted: list[str] = field(default_factory=list)
    accounts_failed: list[str] = field(default_factory=list)
    chats_deleted: int = 0
    access_logs_deleted: int = 0


class AccountService:
    def __init__(
        self,
        users: UserRepository,
        matches: MatchRepository,
        messages: MessageRepository,
        access_logs: AccessLogRepository,
        auth_admin: "TokenVerifier",
        clock: Clock,
    ) -> None:
        self._users = users
        self._matches = matches
        self._messages = messages
        self._access_logs = access_logs
        self._auth_admin = auth_admin
        self._clock = clock

    def hide_chats(self, uid: str) -> None:
        """ "Delete chats": some na hora; a remoção física acontece após a carência."""
        now = self._clock.now()
        for character_id, match in self._matches.for_user(uid):
            if match.get("hidden"):
                continue
            self._messages.hide_all(uid, character_id)
            self._matches.update(uid, character_id, {"hidden": True, "hiddenAt": now})

    def deactivate(self, uid: str) -> datetime:
        now = self._clock.now()
        self._users.deactivate(uid, now)
        return now + GRACE_PERIOD

    def reactivate(self, uid: str) -> None:
        user = self._users.get(uid) or {}
        if user.get("status") != USER_STATUS_DEACTIVATED:
            return
        deactivated_at = user.get("deactivatedAt")
        if deactivated_at is not None and self._clock.now() - deactivated_at > GRACE_PERIOD:
            raise ApiError("account_deactivated")
        self._users.reactivate(uid)

    def purge(self) -> PurgeReport:
        report = PurgeReport()
        now = self._clock.now()
        cutoff = now - GRACE_PERIOD
        for uid in self._users.deactivated_before(cutoff):
            try:
                self._auth_admin.delete_user(uid)
            except Exception:  # o Admin SDK pode falhar por rede; tenta de novo no próximo job
                logger.exception("Falha ao remover %s do Firebase Auth.", uid)
                report.accounts_failed.append(uid)
                continue
            self._users.delete_everything(uid)
            report.accounts_deleted.append(uid)
        for uid in self._users.all_ids():
            for character_id, _ in self._matches.hidden_before(uid, cutoff):
                self._matches.delete_with_messages(uid, character_id)
                report.chats_deleted += 1
        report.access_logs_deleted = self._access_logs.delete_expired(now)
        logger.info(
            "Purge: %d contas, %d conversas, %d logs.",
            len(report.accounts_deleted),
            report.chats_deleted,
            report.access_logs_deleted,
        )
        return report
