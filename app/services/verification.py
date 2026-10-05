"""Envio do e-mail de confirmação da conta (cadastro por e-mail e senha)."""

from typing import TYPE_CHECKING

from app.clock import Clock
from app.errors import ApiError
from app.identity import Identity, InvalidTokenError
from app.mailer import MailerError, VerificationMailer
from app.rate_limit import SlidingWindowLimiter
from app.repositories import UserRepository

if TYPE_CHECKING:
    from app.auth import TokenVerifier

FALLBACK_NAME = "Hero"


class EmailVerificationService:
    def __init__(
        self,
        mailer: VerificationMailer | None,
        auth_admin: "TokenVerifier",
        users: UserRepository,
        limiter: SlidingWindowLimiter,
        clock: Clock,
    ) -> None:
        self._mailer = mailer
        self._auth_admin = auth_admin
        self._users = users
        self._limiter = limiter
        self._clock = clock

    def send(self, identity: Identity, locale: str) -> None:
        """Envia o link de confirmação em HTML.

        `provider_unavailable` quando não há SMTP ou o envio falha: o app então pede o e-mail
        padrão do Firebase. Conta já confirmada não recebe nada.
        """
        if identity.email_verified or not identity.email:
            return
        if self._mailer is None:
            raise ApiError("provider_unavailable")
        retry_after = self._limiter.hit(identity.uid)
        if retry_after is not None:
            raise ApiError("rate_limited", headers={"Retry-After": str(retry_after)})
        try:
            link = self._auth_admin.email_verification_link(identity.email)
            self._mailer.send_verification(identity.email, self._name(identity), link, locale)
        except (InvalidTokenError, MailerError) as exc:
            raise ApiError("provider_unavailable") from exc

    def _name(self, identity: Identity) -> str:
        user = self._users.get(identity.uid) or {}
        name = str(user.get("displayName") or "").strip()
        if name:
            return name
        return (identity.email or "").split("@")[0] or FALLBACK_NAME
