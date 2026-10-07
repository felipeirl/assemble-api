import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.access_log import route_label, save_access_after
from app.api import account, conversations, deck, jobs, onboarding
from app.config import get_settings
from app.container import Container, build_container
from app.errors import install_error_handlers
from app.services.overtures import run_overtures_every

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
QUEUE_LOG_INTERVAL_SECONDS = 60
SERVICE_UNAVAILABLE = 503

# O uvicorn só configura os próprios loggers; sem isto, o progresso dos jobs não aparece.
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
for noisy in ("httpx", "httpcore", "LiteLLM", "litellm", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def laya_state(container: Container) -> str:
    if container.guardrail is None:
        return "off"
    return "warm" if getattr(container.guardrail, "is_warm", True) else "loading"


def log_queues(container: Container, stop: threading.Event) -> None:
    """A cada minuto, registra as filas com trabalho: mostra quando o servidor satura."""
    logger = logging.getLogger("app.queues")
    while not stop.wait(QUEUE_LOG_INTERVAL_SECONDS):
        busy = {
            name: stats
            for name, stats in ((n, q.stats()) for n, q in container.queues().items())
            if stats["waiting"] or stats["running"]
        }
        if busy:
            logger.info(
                "filas: %s",
                ", ".join(
                    f"{name} {s['waiting']} esperando e {s['running']} rodando"
                    for name, s in busy.items()
                ),
            )


def create_app(container_factory: Callable[[], Container] | None = None) -> FastAPI:
    factory = container_factory or (lambda: build_container(get_settings()))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = factory()
        app.state.container = container
        warm_up = getattr(container.guardrail, "warm_up", None)
        if warm_up is not None:
            # O Laya é pesado: carrega em segundo plano para não atrasar o boot do Space.
            threading.Thread(target=warm_up, name="laya-warm-up", daemon=True).start()
        stop = threading.Event()
        threading.Thread(
            target=log_queues, args=(container, stop), name="queue-log", daemon=True
        ).start()
        interval = container.settings.overture_interval_minutes
        if interval > 0:
            threading.Thread(
                target=run_overtures_every,
                args=(
                    interval,
                    lambda: container.job_runner.run_exclusive(
                        "overtures", container.overture_service.run
                    ),
                    stop,
                ),
                name="overtures",
                daemon=True,
            ).start()
        yield
        stop.set()

    app = FastAPI(title="Assemble Backend", lifespan=lifespan)
    install_error_handlers(app)

    @app.middleware("http")
    async def log_request_time(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        save_access_after(request.app.state.container, request, response)
        logging.getLogger("app.timing").info(
            "tempo requisicao %s -> %d: %d ms",
            route_label(request),
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    app.include_router(deck.router)
    app.include_router(onboarding.router)
    app.include_router(conversations.router)
    app.include_router(account.router)
    app.include_router(jobs.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request) -> JSONResponse:
        """Pronto para atender: Laya aquecido (503 enquanto carrega) e o estado das filas."""
        container = request.app.state.container
        laya = laya_state(container)
        body = {
            "laya": laya,
            "queues": {name: queue.stats() for name, queue in container.queues().items()},
        }
        return JSONResponse(
            status_code=SERVICE_UNAVAILABLE if laya == "loading" else 200, content=body
        )

    return app


app = create_app()
