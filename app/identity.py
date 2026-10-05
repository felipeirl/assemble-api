"""Identidade do usuário lida do ID token do Firebase (módulo sem dependências do container)."""

from dataclasses import dataclass


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    """Quem fez a chamada."""

    uid: str
    email: str | None = None
    email_verified: bool = True
    # Login por e-mail e senha: só nele o e-mail precisa ser confirmado (o Google já confirma).
    password_login: bool = False
