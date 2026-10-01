import threading
from datetime import datetime, timedelta
from typing import Any

from app.clock import Clock
from app.repositories import CharacterRepository

TRAIT_FIELDS = ("origin", "powers", "teams")


def has_enough_data(doc: dict[str, Any]) -> bool:
    """Elegível para o baralho: nome e ao menos uma categoria de traços."""
    return bool(doc.get("name")) and any(doc.get(field) for field in TRAIT_FIELDS)


class CharacterCatalog:
    """Cache em memória dos personagens elegíveis (tier A/B), para não reler a coleção."""

    def __init__(self, characters: CharacterRepository, clock: Clock, ttl: timedelta) -> None:
        self._characters = characters
        self._clock = clock
        self._ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] | None = None
        self._loaded_at: datetime | None = None

    def eligible(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            now = self._clock.now()
            if self._cache is None or self._loaded_at is None or now - self._loaded_at > self._ttl:
                self._cache = {
                    character_id: doc
                    for character_id, doc in self._characters.eligible()
                    if has_enough_data(doc)
                }
                self._loaded_at = now
            return self._cache

    def get(self, character_id: str) -> dict[str, Any] | None:
        """Personagem elegível; lê do banco quando não está no cache."""
        cached = self.eligible().get(character_id)
        if cached is not None:
            return cached
        doc = self._characters.get(character_id)
        if doc is None or doc.get("tier") is None or not has_enough_data(doc):
            return None
        return doc

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
