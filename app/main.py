from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import jobs
from app.config import get_settings
from app.container import Container, build_container
from app.errors import install_error_handlers


def create_app(container_factory: Callable[[], Container] | None = None) -> FastAPI:
    factory = container_factory or (lambda: build_container(get_settings()))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = factory()
        yield

    app = FastAPI(title="Assemble Backend", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(jobs.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
