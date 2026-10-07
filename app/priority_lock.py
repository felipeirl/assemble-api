"""Lock com fila de prioridade: entre os que esperam, passa primeiro a menor prioridade."""

import heapq
import itertools
import threading
from collections.abc import Iterator
from contextlib import contextmanager


class PriorityLock:
    """Exclusão mútua em que a vez é dada pela prioridade (menor primeiro) e, no empate, por ordem
    de chegada. Quem tem prioridade baixa pode esperar enquanto houver pedidos mais urgentes."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._held = False
        self._waiting: list[tuple[int, int]] = []
        self._tickets = itertools.count()

    @contextmanager
    def hold(self, priority: int) -> Iterator[None]:
        with self._condition:
            entry = (priority, next(self._tickets))
            heapq.heappush(self._waiting, entry)
            while self._held or self._waiting[0] != entry:
                self._condition.wait()
            heapq.heappop(self._waiting)
            self._held = True
        try:
            yield
        finally:
            with self._condition:
                self._held = False
                self._condition.notify_all()
