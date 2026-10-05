import secrets
from typing import Annotated, Protocol

from fastapi import Depends, Header, Request

from app.access_log import record_access
from app.container import ContainerDep
from app.errors import ApiError
from app.identity import Identity, InvalidTokenError

BEARER_PREFIX = "bearer "


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Identity:
        """Valida o ID token do Firebase; levanta InvalidTokenError."""
        ...

    def delete_user(self, uid: str) -> None: ...

    def email_verification_link(self, email: str) -> str:
        """Link do Firebase que confirma o e-mail do usuário."""
        ...


def authenticated_identity(
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Identity:
    """Identidade do token, sem checar conta nem e-mail (reativar conta e verificar e-mail)."""
    if not authorization or not authorization.lower().startswith(BEARER_PREFIX):
        raise ApiError("unauthenticated")
    token = authorization[len(BEARER_PREFIX) :].strip()
    if not token:
        raise ApiError("unauthenticated")
    try:
        identity = container.token_verifier.verify(token)
    except InvalidTokenError as exc:
        raise ApiError("unauthenticated") from exc
    record_access(container, request, identity.uid)
    return identity


AnyStatusIdentity = Annotated[Identity, Depends(authenticated_identity)]


def authenticated_uid(identity: AnyStatusIdentity) -> str:
    """uid do token, sem checar o status da conta (usado só por /v2/account/reactivate)."""
    return identity.uid


AnyStatusUid = Annotated[str, Depends(authenticated_uid)]


def active_uid(identity: AnyStatusIdentity, container: ContainerDep) -> str:
    """uid de uma conta ativa e com e-mail confirmado.

    Conta em carência recebe 403 account_deactivated; login por e-mail e senha sem o e-mail
    confirmado recebe 403 email_not_verified (desligável em REQUIRE_EMAIL_VERIFICATION).
    """
    user = container.store.get(f"users/{identity.uid}")
    if user is not None and user.get("status") == "deactivated":
        raise ApiError("account_deactivated")
    needs_verification = container.settings.require_email_verification
    if needs_verification and identity.password_login and not identity.email_verified:
        raise ApiError("email_not_verified")
    return identity.uid


ActiveUid = Annotated[str, Depends(active_uid)]


def require_jobs_key(
    request: Request,
    container: ContainerDep,
    x_jobs_key: Annotated[str | None, Header()] = None,
) -> None:
    expected = container.settings.jobs_key
    if expected is None or not x_jobs_key:
        raise ApiError("unauthenticated")
    if not secrets.compare_digest(x_jobs_key, expected.get_secret_value()):
        raise ApiError("unauthenticated")
    record_access(container, request, uid=None)
