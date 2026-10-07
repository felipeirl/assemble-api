import pytest
from firebase_admin import auth

from app.firebase import VERIFIED_TOKEN_TTL_SECONDS, FirebaseTokenVerifier
from app.identity import InvalidTokenError

NOW = 1_800_000_000.0
TOKEN_LIFETIME = 3600


class FakeClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def remote(monkeypatch):
    calls = []

    def verify_id_token(token, app=None, check_revoked=False):
        calls.append(token)
        if token == "revogado":
            raise auth.RevokedIdTokenError("revogado")
        return {
            "uid": f"uid-{token}",
            "exp": NOW + TOKEN_LIFETIME,
            "firebase": {"sign_in_provider": "password"},
            "email_verified": True,
        }

    monkeypatch.setattr(auth, "verify_id_token", verify_id_token)
    return calls


def test_verified_token_is_reused_without_asking_google_again(remote):
    verifier = FirebaseTokenVerifier(app=None, now=FakeClock())

    first = verifier.verify("t1")
    second = verifier.verify("t1")

    assert first == second
    assert first.uid == "uid-t1"
    assert first.password_login is True
    assert remote == ["t1"]


def test_verified_token_is_checked_again_after_the_ttl(remote):
    clock = FakeClock()
    verifier = FirebaseTokenVerifier(app=None, now=clock)

    verifier.verify("t1")
    clock.value += VERIFIED_TOKEN_TTL_SECONDS
    verifier.verify("t1")

    assert remote == ["t1", "t1"]


def test_cached_token_never_outlives_its_expiry(remote, monkeypatch):
    clock = FakeClock()
    verifier = FirebaseTokenVerifier(app=None, now=clock)
    monkeypatch.setattr(
        auth,
        "verify_id_token",
        lambda token, app=None, check_revoked=False: (
            remote.append(token) or {"uid": "u", "exp": NOW + 10}
        ),
    )

    verifier.verify("t1")
    clock.value += 10
    verifier.verify("t1")

    assert remote == ["t1", "t1"]


def test_rejected_token_is_not_cached(remote):
    verifier = FirebaseTokenVerifier(app=None, now=FakeClock())

    for _ in range(2):
        with pytest.raises(InvalidTokenError):
            verifier.verify("revogado")

    assert remote == ["revogado", "revogado"]


def test_deleting_the_user_forgets_its_tokens(remote, monkeypatch):
    monkeypatch.setattr(auth, "delete_user", lambda uid, app=None: None)
    verifier = FirebaseTokenVerifier(app=None, now=FakeClock())

    verifier.verify("t1")
    verifier.delete_user("uid-t1")
    verifier.verify("t1")

    assert remote == ["t1", "t1"]
