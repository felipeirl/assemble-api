import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.container import Container

ACCESS_LOG_RETENTION = timedelta(days=180)
ACCESS_LOGS = "accessLogs"


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
    """Registro do Marco Civil (art. 15): uid, rota, IP e horário; retenção de 6 meses."""
    now = container.clock.now()
    container.store.create(
        f"{ACCESS_LOGS}/{uuid.uuid4().hex}",
        {
            "uid": uid,
            "route": route_label(request),
            "ip": client_ip(request),
            "timestamp": now,
            "expiresAt": now + ACCESS_LOG_RETENTION,
        },
    )
