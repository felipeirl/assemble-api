"""Superhero API (akabab): enriquece personagens que já existem; nunca cria personagem.

Casamento (Assemble-perfis-e-fontes.md §3.1): tabela manual → automático restrito → revisão.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.catalog.mapping import Mappings, normalize
from app.catalog.text import truncate

ALL_URL = "https://akabab.github.io/superhero-api/api/all.json"
SOURCE_LABEL = "Superhero API"
SOURCE_URL = "https://akabab.github.io/superhero-api/"

MATCH_MANUAL = "manual"
MATCH_AUTO = "auto"

ABSENT_VALUES = {"", "-", "null", "0 cm", "0 kg", "no alter egos found."}
POWERSTAT_KEYS = ("intelligence", "strength", "speed", "durability", "power", "combat")
POWERSTAT_MAX = 100
ALIGNMENTS = {"good": "Good", "bad": "Bad", "neutral": "Neutral"}
ALIAS_MAX_CHARS = 40
ALIASES_MAX = 6
RELATIVES_MAX_CHARS = 300
# Apelido com verbo é frase descritiva ("has impersonated Daredevil…"), não apelido.
ALIAS_VERBS = {"has", "have", "had", "is", "was", "were", "impersonated", "posed", "used"}

logger = logging.getLogger(__name__)


class SuperheroApiClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http
        self._entries: dict[int, dict[str, Any]] | None = None

    def entries(self) -> dict[int, dict[str, Any]]:
        """Todas as entradas por id; vazio quando a fonte está fora (enriquecimento é opcional)."""
        if self._entries is not None:
            return self._entries
        try:
            response = self._http.get(ALL_URL)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Superhero API indisponível: %s", type(exc).__name__)
            data = []
        self._entries = {int(entry["id"]): entry for entry in data if "id" in entry}
        return self._entries


@dataclass(frozen=True)
class SuperheroMatch:
    entry: dict[str, Any] | None
    method: str | None
    candidates: list[int]


class SuperheroMatcher:
    def __init__(self, client: SuperheroApiClient, mappings: Mappings) -> None:
        self._client = client
        self._mappings = mappings

    def match(self, character_id: str, name: str, real_name: str | None) -> SuperheroMatch:
        entries = self._client.entries()
        if character_id in self._mappings.superhero_matches:
            superhero_id = self._mappings.superhero_matches[character_id]
            entry = entries.get(superhero_id) if superhero_id is not None else None
            return SuperheroMatch(entry, MATCH_MANUAL if entry else None, [])

        same_name = [
            entry_id
            for entry_id, entry in entries.items()
            if normalize(entry.get("name", "")) == normalize(name)
        ]
        if real_name:
            strict = [
                entry_id
                for entry_id in same_name
                if normalize(entries[entry_id].get("biography", {}).get("fullName") or "")
                == normalize(real_name)
                and entries[entry_id].get("biography", {}).get("publisher")
                in self._mappings.accepted_publishers
            ]
            if len(strict) == 1:
                return SuperheroMatch(entries[strict[0]], MATCH_AUTO, [])
        return SuperheroMatch(None, None, sorted(same_name))


def group_affiliations(entry: dict[str, Any]) -> list[str]:
    """Grupos atuais: sem parênteses, notas "[3]" e tudo o que vem depois de "formerly"."""
    text = entry.get("connections", {}).get("groupAffiliation") or ""
    if _absent(text):
        return []
    text = re.sub(r"\([^)]*\)|\[\d+\]", "", text)
    current = re.split(r"\bformerly\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return [part.strip() for part in re.split(r"[,;]", current) if part.strip()]


def clean_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Campos novos de `characters/{id}` (§3.3), sem os valores que querem dizer ausente."""
    biography = entry.get("biography", {})
    work = entry.get("work", {})
    connections = entry.get("connections", {})
    fields: dict[str, Any] = {
        "aliases": clean_aliases(biography.get("aliases") or []),
        "alignment": ALIGNMENTS.get(str(biography.get("alignment") or "").lower()),
        "placeOfBirth": _text(biography.get("placeOfBirth")),
        "occupation": _text(work.get("occupation")),
        "base": _text(work.get("base")),
        "relatives": _relatives(connections.get("relatives")),
        "powerstats": clean_powerstats(entry.get("powerstats") or {}),
        "appearance": clean_appearance(entry.get("appearance") or {}),
    }
    return {key: value for key, value in fields.items() if value}


def clean_aliases(aliases: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in aliases:
        for alias in str(raw).split(","):
            alias = alias.strip()
            words = {word.lower() for word in alias.split()}
            if _absent(alias) or len(alias) > ALIAS_MAX_CHARS or words & ALIAS_VERBS:
                continue
            if normalize(alias) in seen:
                continue
            seen.add(normalize(alias))
            result.append(alias)
    return result[:ALIASES_MAX]


def clean_powerstats(stats: dict[str, Any]) -> dict[str, int] | None:
    """Os 6 atributos de 0 a 100, ou nada: radar incompleto engana."""
    cleaned = {}
    for key in POWERSTAT_KEYS:
        value = stats.get(key)
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        if not 0 <= value <= POWERSTAT_MAX:
            return None
        cleaned[key] = value
    return cleaned


def clean_appearance(appearance: dict[str, Any]) -> dict[str, Any] | None:
    fields = {
        "gender": _text(appearance.get("gender")),
        "race": _text(appearance.get("race")),
        "heightCm": _metric(appearance.get("height"), "cm"),
        "weightKg": _metric(appearance.get("weight"), "kg"),
        "eyeColor": _text(appearance.get("eyeColor")),
        "hairColor": _text(appearance.get("hairColor")),
    }
    cleaned = {key: value for key, value in fields.items() if value}
    return cleaned or None


def _metric(pair: Any, unit: str) -> int | None:
    for value in pair or []:
        match = re.fullmatch(rf"\s*([\d,]+)\s*{unit}\s*", str(value))
        if match:
            number = int(match.group(1).replace(",", ""))
            return number or None
    return None


def _relatives(text: Any) -> str | None:
    cleaned = _text(text)
    return truncate(cleaned, RELATIVES_MAX_CHARS) if cleaned else None


def _text(value: Any) -> str | None:
    if value is None or _absent(str(value)):
        return None
    return str(value).strip()


def _absent(text: str) -> bool:
    return text.strip().lower() in ABSENT_VALUES
