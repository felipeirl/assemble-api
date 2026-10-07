import logging
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from fastapi import Request
from starlette.background import BackgroundTask
from starlette.responses import Response

if TYPE_CHECKING:
    from app.container import Container

ACCESS_LOG_RETENTION = timedelta(days=180)
ACCESS_LOGS = "accessLogs"
# Onde a dependência de autenticação deixa o registro para o middleware gravar.
ACCESS_ENTRY_STATE = "access_entry"

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    return f"{request.method} {path}"


def record_access(container: "Container", request: Request, uid: str | None) -> None:
    """Registro do Marco Civil (art. 15): uid, rota, IP e horário; retenção de 6 meses.

    Os dados são lidos agora; a gravação no Firestore fica para depois da resposta
    (ver `save_access_after`), inclusive quando a rota termina em erro.
    """
    now = container.clock.now()
    setattr(
        request.state,
        ACCESS_ENTRY_STATE,
        {
            "uid": uid,
            "route": route_label(request),
            "ip": client_ip(request),
            "timestamp": now,
            "expiresAt": now + ACCESS_LOG_RETENTION,
        },
    )


def save_access_after(container: "Container", request: Request, response: Response) -> None:
    """Agenda a gravação do registro para depois de enviar a resposta.

    A resposta vem do `call_next` do middleware, que nunca traz tarefa própria em `background`.
    """
    entry = getattr(request.state, ACCESS_ENTRY_STATE, None)
    if entry is not None:
        response.background = BackgroundTask(_save_access, container, entry)


def _save_access(container: "Container", entry: dict[str, Any]) -> None:
    try:
        container.store.create(f"{ACCESS_LOGS}/{uuid.uuid4().hex}", entry)
    except Exception:
        logger.exception("Registro de acesso não gravado (uid=%s).", entry["uid"])
