import math
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta

from app.clock import Clock


class SlidingWindowLimiter:
    """Limite por chave numa janela deslizante, em memória (um único processo no Space)."""

    def __init__(self, limit: int, window: timedelta, clock: Clock) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> int | None:
        """Registra o uso; devolve os segundos de espera se o limite já foi atingido."""
        now = self._clock.now()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                wait = (hits[0] + self._window - now).total_seconds()
                return max(1, math.ceil(wait))
            hits.append(now)
            return None
