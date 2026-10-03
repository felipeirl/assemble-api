"""Nomes de personagens em português do Brasil: tabela curada em data/names_ptbr.json."""

import json
from functools import lru_cache

from app.catalog.mapping import DATA_DIR
from app.i18n import PT_BR

NAMES_FILE = DATA_DIR / "names_ptbr.json"


@lru_cache
def _table() -> dict[str, str]:
    with NAMES_FILE.open(encoding="utf-8") as file:
        return json.load(file)["names"]


def pt_br_name(character_id: str) -> str | None:
    return _table().get(character_id)


def display_name(character_id: str, original: str, locale: str) -> str:
    """Nome no idioma pedido; sem entrada na tabela, o nome original (nunca inventado)."""
    if locale == PT_BR:
        return pt_br_name(character_id) or original
    return original
