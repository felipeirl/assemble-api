import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.access_log import route_label, save_access_after
from app.api import account, conversations, deck, jobs, onboarding
from app.config import get_settings
from app.container import Container, build_container
from app.errors import install_error_handlers

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# O uvicorn só configura os próprios loggers; sem isto, o progresso dos jobs não aparece.
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
for noisy in ("httpx", "httpcore", "LiteLLM", "litellm", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


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
        yield

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

    return app


app = create_app()
