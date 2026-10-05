import os

# Antes de qualquer import do app: o litellm não pode carregar o .env do desenvolvedor.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container
from app.identity import Identity, InvalidTokenError
from app.main import create_app
from app.store.memory import MemoryStore
from tests.fakes import FakeGuardrail, FakeLlm, chat_reply

JOBS_KEY = "jobs-secret"


class FakeTokenVerifier:
    """Aceita tokens no formato `token-<uid>`."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def verify(self, token: str) -> Identity:
        if not token.startswith("token-"):
            raise InvalidTokenError("token inválido")
        uid = token.removeprefix("token-")
        # `token-<uid>!unverified`: login por e-mail e senha ainda sem o e-mail confirmado.
        if uid.endswith("!unverified"):
            uid = uid.removesuffix("!unverified")
            return Identity(uid, f"{uid}@example.com", email_verified=False, password_login=True)
        return Identity(uid, f"{uid}@example.com", email_verified=True, password_login=True)

    def email_verification_link(self, email: str) -> str:
        return f"https://example.test/verify?email={email}"

    def delete_user(self, uid: str) -> None:
        self.deleted.append(uid)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 10, 1, 15, 0, tzinfo=UTC))


@pytest.fixture
def container(clock: FixedClock) -> Container:
    settings = Settings(
        _env_file=None,
        jobs_key=JOBS_KEY,
        chat_model="chat-main",
        chat_fallback_model="chat-reserve",
    )
    return Container(
        settings=settings,
        store=MemoryStore(),
        token_verifier=FakeTokenVerifier(),
        clock=clock,
        llm=FakeLlm(chat_reply),
        guardrail=FakeGuardrail(),
    )


@pytest.fixture
def app(container: Container):
    return create_app(lambda: container)


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def auth_header(uid: str) -> dict[str, str]:
    return {"Authorization": f"Bearer token-{uid}"}
