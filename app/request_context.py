"""Cabeçalhos do contrato: Accept-Language, X-Timezone e Idempotency-Key."""

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, Header

from app.container import ContainerDep
from app.errors import ApiError
from app.i18n import resolve_locale

IDEMPOTENCY_KEY_MAX_LENGTH = 128


def user_timezone(
    container: ContainerDep, x_timezone: Annotated[str | None, Header()] = None
) -> ZoneInfo:
    """Fuso IANA enviado pelo app; ausente ou inválido usa o padrão."""
    for name in (x_timezone, container.settings.default_timezone):
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    raise RuntimeError("DEFAULT_TIMEZONE inválido.")


def locale(accept_language: Annotated[str | None, Header()] = None) -> str:
    return resolve_locale(accept_language)


def idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str | None:
    if idempotency_key is None:
        return None
    key = idempotency_key.strip()
    if not key or len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ApiError("invalid_request")
    return key


UserTimezone = Annotated[ZoneInfo, Depends(user_timezone)]
Locale = Annotated[str, Depends(locale)]
IdempotencyKey = Annotated[str | None, Depends(idempotency_key)]
