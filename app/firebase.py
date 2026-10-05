import json

import firebase_admin
from firebase_admin import auth, credentials, firestore

from app.identity import Identity, InvalidTokenError

APP_NAME = "assemble"


def init_firebase(service_account_json: str) -> firebase_admin.App:
    try:
        return firebase_admin.get_app(APP_NAME)
    except ValueError:
        info = json.loads(service_account_json)
        return firebase_admin.initialize_app(credentials.Certificate(info), name=APP_NAME)


def firestore_client(app: firebase_admin.App):
    return firestore.client(app)


class FirebaseTokenVerifier:
    def __init__(self, app: firebase_admin.App) -> None:
        self._app = app

    def verify(self, token: str) -> Identity:
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
        provider = (decoded.get("firebase") or {}).get("sign_in_provider")
        return Identity(
            uid=decoded["uid"],
            email=decoded.get("email"),
            email_verified=bool(decoded.get("email_verified")),
            password_login=provider == "password",
        )

    def email_verification_link(self, email: str) -> str:
        try:
            return auth.generate_email_verification_link(email, app=self._app)
        except (auth.UserNotFoundError, ValueError, auth.AuthError) as exc:
            raise InvalidTokenError(type(exc).__name__) from exc

    def delete_user(self, uid: str) -> None:
        try:
            auth.delete_user(uid, app=self._app)
        except auth.UserNotFoundError:
            return
