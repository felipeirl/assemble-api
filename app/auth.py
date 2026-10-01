import secrets
from typing import Annotated, Protocol

from fastapi import Depends, Header, Request

from app.access_log import record_access
from app.container import ContainerDep
from app.errors import ApiError

BEARER_PREFIX = "bearer "


class InvalidTokenError(Exception):
    pass


class TokenVerifier(Protocol):
    def verify(self, token: str) -> str:
        """Valida o ID token do Firebase e devolve o uid; levanta InvalidTokenError."""
        ...

    def delete_user(self, uid: str) -> None: ...


def authenticated_uid(
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """uid do token, sem checar o status da conta (usado só por /v2/account/reactivate)."""
    if not authorization or not authorization.lower().startswith(BEARER_PREFIX):
        raise ApiError("unauthenticated")
    token = authorization[len(BEARER_PREFIX) :].strip()
    if not token:
        raise ApiError("unauthenticated")
    try:
        uid = container.token_verifier.verify(token)
    except InvalidTokenError as exc:
        raise ApiError("unauthenticated") from exc
    record_access(container, request, uid)
    return uid


AnyStatusUid = Annotated[str, Depends(authenticated_uid)]


def active_uid(uid: AnyStatusUid, container: ContainerDep) -> str:
    """uid de uma conta ativa; conta em carência recebe 403 account_deactivated."""
    user = container.store.get(f"users/{uid}")
    if user is not None and user.get("status") == "deactivated":
        raise ApiError("account_deactivated")
    return uid


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
