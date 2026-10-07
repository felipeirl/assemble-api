import hashlib
import json
import threading
import time
from collections.abc import Callable

import firebase_admin
from firebase_admin import auth, credentials, firestore

from app.identity import Identity, InvalidTokenError

APP_NAME = "assemble"
# A checagem de revogação consulta o Google a cada pedido (1 a 2 s sob carga). Um token já
# verificado vale por este tempo sem nova consulta: revogar ou desativar leva até isso para valer.
VERIFIED_TOKEN_TTL_SECONDS = 300
VERIFIED_TOKEN_CACHE_LIMIT = 10_000


def init_firebase(service_account_json: str) -> firebase_admin.App:
    try:
        return firebase_admin.get_app(APP_NAME)
    except ValueError:
        info = json.loads(service_account_json)
        return firebase_admin.initialize_app(credentials.Certificate(info), name=APP_NAME)


def firestore_client(app: firebase_admin.App):
    return firestore.client(app)


class FirebaseTokenVerifier:
    def __init__(self, app: firebase_admin.App, now: Callable[[], float] = time.time) -> None:
        self._app = app
        self._now = now
        # sha256 do token -> (identidade, válido até, em segundos Unix): o token não fica guardado.
        self._verified: dict[str, tuple[Identity, float]] = {}
        self._verified_guard = threading.Lock()

    def verify(self, token: str) -> Identity:
        now = self._now()
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._verified_guard:
            cached = self._verified.get(digest)
        if cached is not None and now < cached[1]:
            return cached[0]
        decoded = self._verify_remote(token)
        identity = identity_from(decoded)
        valid_until = min(now + VERIFIED_TOKEN_TTL_SECONDS, float(decoded.get("exp", now)))
        with self._verified_guard:
            if len(self._verified) >= VERIFIED_TOKEN_CACHE_LIMIT:
                self._verified = {k: v for k, v in self._verified.items() if now < v[1]}
            self._verified[digest] = (identity, valid_until)
        return identity

    def forget_user(self, uid: str) -> None:
        with self._verified_guard:
            self._verified = {k: v for k, v in self._verified.items() if v[0].uid != uid}

    def _verify_remote(self, token: str) -> dict:
        try:
            decoded = auth.verify_id_token(token, app=self._app, check_revoked=True)
        except (
            auth.InvalidIdTokenError,
            auth.ExpiredIdTokenError,
            auth.RevokedIdTokenError,
            auth.UserDisabledError,
            ValueError,
        ) as exc:
            raise InvalidTokenError(str(exc)) from exc
        return decoded

    def email_verification_link(self, email: str) -> str:
        try:
            return auth.generate_email_verification_link(email, app=self._app)
        except (auth.UserNotFoundError, ValueError, auth.AuthError) as exc:
            raise InvalidTokenError(type(exc).__name__) from exc

    def delete_user(self, uid: str) -> None:
        self.forget_user(uid)
        try:
            auth.delete_user(uid, app=self._app)
        except auth.UserNotFoundError:
            return


def identity_from(decoded: dict) -> Identity:
    provider = (decoded.get("firebase") or {}).get("sign_in_provider")
    return Identity(
        uid=decoded["uid"],
        email=decoded.get("email"),
        email_verified=bool(decoded.get("email_verified")),
        password_login=provider == "password",
    )
