PT_BR = "pt-BR"
EN = "en"
DEFAULT_LOCALE = EN


def resolve_locale(accept_language: str | None) -> str:
    """Escolhe pt-BR ou en a partir do Accept-Language, na ordem enviada pelo app."""
    if not accept_language:
        return DEFAULT_LOCALE
    for part in accept_language.split(","):
        tag = part.split(";")[0].strip().lower()
        if tag.startswith("pt"):
            return PT_BR
        if tag.startswith("en"):
            return EN
    return DEFAULT_LOCALE
