import logging
import threading
from collections import defaultdict
from collections.abc import Callable

logger = logging.getLogger(__name__)


class JobRunner:
    """Executa cada job em segundo plano, no máximo uma instância por vez."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    def run_exclusive(
        self, name: str, job: Callable[[], object], serialize_with: str | None = None
    ) -> None:
        """Ignora a chamada se o job já roda. Com `serialize_with`, jobs do mesmo grupo
        esperam a vez em vez de rodar juntos (por exemplo, os que disputam o mesmo modelo)."""
        lock = self._locks[name]
        if not lock.acquire(blocking=False):
            logger.info("Job %s já está em execução; chamada ignorada.", name)
            return
        try:
            if serialize_with is None:
                job()
                return
            with self._locks[serialize_with]:
                job()
        finally:
            lock.release()
