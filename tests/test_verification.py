from datetime import timedelta

import pytest

from app.identity import Identity
from app.mailer import (
    HERO_RED,
    LOGO_RED,
    MIDNIGHT,
    MailerError,
    VerificationMailer,
    render_verification,
)
from tests.conftest import auth_header
from tests.factories import seed_characters, seed_user

UID = "u1"
VERIFIED = auth_header(UID)
UNVERIFIED = auth_header(f"{UID}!unverified")
LINK = "https://example.test/verify?email=u1@example.com"


class FakeSmtp:
    """Servidor SMTP de mentira: guarda a mensagem enviada."""

    sent: list = []
    logins: list = []

    def __init__(self, host, port):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        FakeSmtp.logins.append((user, password))

    def send_message(self, message):
        FakeSmtp.sent.append(message)


class BrokenSmtp(FakeSmtp):
    def send_message(self, message):
        raise OSError("sem rede")


@pytest.fixture
def smtp(container):
    FakeSmtp.sent, FakeSmtp.logins = [], []
    container.mailer = VerificationMailer(
        "smtp.test", 587, "assemble@test.dev", "senha-de-app", "Assemble", smtp_factory=FakeSmtp
    )
    return FakeSmtp


@pytest.fixture
def seeded(container):
    seed_characters(container.store)
    seed_user(container.store, UID)
    return container


# --- o e-mail em HTML ----------------------------------------------------------------------


def test_the_html_uses_the_design_system_and_escapes_the_name():
    subject, text, page = render_verification("<b>Tony</b>", LINK, "pt-BR")

    assert subject == "Confirme o seu e-mail no Assemble"
    for token in (HERO_RED, LOGO_RED, MIDNIGHT, "Barlow Condensed", "Inter"):
        assert token in page
    assert "&lt;b&gt;Tony&lt;/b&gt;" in page and "<b>Tony</b>" not in page
    assert f'href="{LINK}"' in page
    assert LINK in text and "Tony" in text


def test_the_html_has_an_english_version_and_loads_nothing_external():
    subject, _, page = render_verification("Tony", LINK, "en")

    assert subject == "Confirm your email on Assemble"
    assert "Confirm email" in page
    assert "http://" not in page.replace(LINK, "") and "<img" not in page
    assert "<link" not in page and "@import" not in page


def test_the_mailer_sends_text_and_html_through_smtp(smtp):
    mailer = VerificationMailer(
        "smtp.test", 587, "assemble@test.dev", "senha-de-app", "Assemble", smtp_factory=smtp
    )

    mailer.send_verification("ana@example.com", "Ana", LINK, "pt-BR")

    message = smtp.sent[0]
    assert smtp.logins == [("assemble@test.dev", "senha-de-app")]
    assert message["To"] == "ana@example.com"
    assert message["From"] == "Assemble <assemble@test.dev>"
    kinds = {part.get_content_type() for part in message.iter_parts()}
    assert kinds == {"text/plain", "text/html"}


def test_an_smtp_failure_becomes_a_mailer_error():
    mailer = VerificationMailer("smtp.test", 587, "a@b.c", "x", "Assemble", smtp_factory=BrokenSmtp)

    with pytest.raises(MailerError):
        mailer.send_verification("ana@example.com", "Ana", LINK, "en")


# --- a rota --------------------------------------------------------------------------------


def test_the_route_sends_the_link_to_the_users_email(client, seeded, smtp):
    response = client.post(
        "/v2/account/email-verification",
        headers={**UNVERIFIED, "Accept-Language": "pt-BR"},
    )

    assert response.status_code == 204
    message = smtp.sent[0]
    assert message["To"] == "u1@example.com"
    html = message.get_body(("html",)).get_content()
    assert LINK in html and "Ana" in html  # o nome vem do perfil


def test_an_already_verified_account_gets_no_email(client, seeded, smtp):
    response = client.post("/v2/account/email-verification", headers=VERIFIED)

    assert response.status_code == 204
    assert smtp.sent == []


def test_resending_too_fast_is_rate_limited(client, seeded, smtp, clock):
    assert client.post("/v2/account/email-verification", headers=UNVERIFIED).status_code == 204

    again = client.post("/v2/account/email-verification", headers=UNVERIFIED)

    assert again.status_code == 429
    assert int(again.headers["Retry-After"]) >= 1
    clock.current += timedelta(seconds=61)
    assert client.post("/v2/account/email-verification", headers=UNVERIFIED).status_code == 204
    assert len(smtp.sent) == 2


def test_without_smtp_the_route_asks_the_app_to_use_the_firebase_email(client, seeded):
    response = client.post("/v2/account/email-verification", headers=UNVERIFIED)

    assert response.status_code == 503
    assert response.json()["error"] == "provider_unavailable"


def test_an_smtp_failure_is_a_503_so_the_app_can_fall_back(client, seeded, container):
    container.mailer = VerificationMailer(
        "smtp.test", 587, "a@b.c", "x", "Assemble", smtp_factory=BrokenSmtp
    )

    response = client.post("/v2/account/email-verification", headers=UNVERIFIED)

    assert response.status_code == 503


# --- o bloqueio das rotas até confirmar ----------------------------------------------------


def test_an_unverified_password_account_is_blocked_with_a_clear_error(client, seeded):
    response = client.get("/v2/deck", headers=UNVERIFIED)

    assert response.status_code == 403
    assert response.json()["error"] == "email_not_verified"


def test_a_verified_account_and_a_google_login_are_not_blocked(client, seeded, container):
    assert client.get("/v2/deck", headers=VERIFIED).status_code == 200
    # Login com Google: o provedor confirma o e-mail, então nunca fica "pendente".
    google = Identity("g1", "g@example.com", email_verified=False, password_login=False)
    container.token_verifier.verify = lambda token: google
    seed_user(container.store, "g1")

    assert client.get("/v2/deck", headers=auth_header("g1")).status_code == 200


def test_the_block_can_be_turned_off(client, seeded, container):
    container.settings.require_email_verification = False

    assert client.get("/v2/deck", headers=UNVERIFIED).status_code == 200


def test_reactivating_an_account_does_not_need_a_verified_email(client, seeded):
    response = client.post("/v2/account/reactivate", headers=UNVERIFIED)

    assert response.status_code == 204
