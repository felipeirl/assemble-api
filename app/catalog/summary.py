"""Mini descrição do card: a primeira frase da bio, curta, no idioma pedido."""

import re
from typing import Any

from app.i18n import PT_BR

TAGLINE_MAX_CHARS = 140
# O Comic Vine abre a bio com o título da seção ("Origin Originally, ...").
SECTION_HEADINGS = (
    "Origin",
    "Origem",
    "Creation",
    "Criação",
    "History",
    "História",
    "Overview",
    "Biography",
    "Biografia",
)
_HEADING = re.compile(rf"^(?:{'|'.join(SECTION_HEADINGS)})\s+(?=[A-ZÀ-Ý])")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_ELLIPSIS = "…"


def tagline(doc: dict[str, Any], locale: str) -> str | None:
    """Primeira frase da bio (traduzida em pt-BR, quando existe), até TAGLINE_MAX_CHARS."""
    translations = (doc.get("translations") or {}).get(PT_BR) or {}
    translated = translations.get("bio") if locale == PT_BR else None
    text = _HEADING.sub("", " ".join((translated or doc.get("bio") or "").split()))
    if not text:
        return None
    for end in _SENTENCE_END.finditer(text):
        if end.end() > TAGLINE_MAX_CHARS:
            break
        return text[: end.end()]
    if len(text) <= TAGLINE_MAX_CHARS:
        return text
    cut = text[: TAGLINE_MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + _ELLIPSIS
