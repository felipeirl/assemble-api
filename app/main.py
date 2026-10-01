import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import deck, jobs
from app.config import get_settings
from app.container import Container, build_container
from app.errors import install_error_handlers


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
    app.include_router(deck.router)
    app.include_router(jobs.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
