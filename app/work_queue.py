"""Fila de trabalho em segundo plano com um único consumidor.

O trabalho pesado (modelo e Laya) roda fora da requisição, uma tarefa de cada vez: o proxy da
Discloud corta a conexão em cerca de 30 s, e várias inferências do Laya juntas disputam a CPU.
"""

import logging
import queue
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

Task = Callable[[], None]


class WorkQueue:
    def __init__(self, name: str, capacity: int) -> None:
        self._name = name
        self._tasks: queue.Queue[Task] = queue.Queue(maxsize=capacity)
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, task: Task) -> bool:
        """Põe a tarefa na fila; devolve False se a fila estiver cheia."""
        try:
            self._tasks.put_nowait(task)
        except queue.Full:
            logger.warning("Fila %s cheia; tarefa recusada.", self._name)
            return False
        return True

    def wait_idle(self) -> None:
        """Espera a fila esvaziar e a tarefa em andamento terminar."""
        self._tasks.join()

    def _run(self) -> None:
        while True:
            task = self._tasks.get()
            try:
                task()
            except Exception:
                logger.exception("Tarefa da fila %s falhou.", self._name)
            finally:
                self._tasks.task_done()
