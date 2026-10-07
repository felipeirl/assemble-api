"""O que o personagem sabe do usuário, montado a partir do perfil e das preferências."""

import re
from typing import Any

from app.ai.chat import UserContext
from app.domain.compatibility import traits_in_common
from app.domain.models import CharacterTraits, Preferences

FIRST_NAME_MAX_CHARS = 30
BIO_MAX_CHARS = 500
LOOKING_FOR_MAX_CHARS = 140
# Só letras (com acento), hífen e apóstrofo: o nome entra no prompt e não pode carregar instrução.
NAME_CHARS = re.compile(r"[^\w'\-]|[\d_]", re.UNICODE)


def first_name(display_name: Any) -> str | None:
    """Primeiro nome do perfil, sem números, símbolos nem quebras de linha."""
    words = str(display_name or "").split()
    if not words:
        return None
    name = NAME_CHARS.sub("", words[0])[:FIRST_NAME_MAX_CHARS]
    return name or None


def preference_labels(prefs: Preferences) -> dict[str, list[str]]:
    """Gostos declarados (lista vazia = qualquer um, então não diz nada)."""
    labels = {
        "origins": [item.value for item in prefs.origins],
        "powers": [item.value for item in prefs.powers],
        "teams": [item.value for item in prefs.teams],
        "styles": [item.value for item in prefs.styles],
    }
    return {key: value for key, value in labels.items() if value}


def build_user_context(user: dict[str, Any] | None, character: dict[str, Any]) -> UserContext:
    user = user or {}
    prefs = Preferences.model_validate(user.get("preferences") or {})
    return UserContext(
        first_name=first_name(user.get("displayName")),
        bio=str(user.get("bio") or "").strip()[:BIO_MAX_CHARS] or None,
        looking_for=str(user.get("lookingFor") or "").strip()[:LOOKING_FOR_MAX_CHARS] or None,
        preferences=preference_labels(prefs),
        in_common=traits_in_common(prefs, CharacterTraits.model_validate(character)),
    )
