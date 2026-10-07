"""Fila de trabalho em segundo plano, com um número fixo de consumidores.

O trabalho pesado (modelo e Laya) roda fora da requisição: o proxy da Discloud corta a conexão em
cerca de 30 s. Vários consumidores deixam as chamadas ao modelo, que é remoto, correrem em
paralelo; o Laya continua uma inferência por vez pelo lock dele.
"""

import logging
import queue
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

Task = Callable[[], None]


class WorkQueue:
    def __init__(self, name: str, capacity: int, workers: int = 1) -> None:
        self._name = name
        self._capacity = capacity
        self._workers = workers
        self._tasks: queue.Queue[Task] = queue.Queue(maxsize=capacity)
        self._running = 0
        self._running_guard = threading.Lock()
        self._threads = [
            threading.Thread(target=self._run, name=f"{name}-{index}", daemon=True)
            for index in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, task: Task) -> bool:
        """Põe a tarefa na fila; devolve False se a fila estiver cheia."""
        try:
            self._tasks.put_nowait(task)
        except queue.Full:
            logger.warning("Fila %s cheia; tarefa recusada.", self._name)
            return False
        return True

    def stats(self) -> dict[str, int]:
        """Tarefas esperando e rodando agora, para o `/ready` e o log de saturação."""
        with self._running_guard:
            running = self._running
        return {
            "waiting": self._tasks.qsize(),
            "running": running,
            "capacity": self._capacity,
            "workers": self._workers,
        }

    def wait_idle(self) -> None:
        """Espera a fila esvaziar e as tarefas em andamento terminarem."""
        self._tasks.join()

    def _run(self) -> None:
        while True:
            task = self._tasks.get()
            with self._running_guard:
                self._running += 1
            try:
                task()
            except Exception:
                logger.exception("Tarefa da fila %s falhou.", self._name)
            finally:
                with self._running_guard:
                    self._running -= 1
                self._tasks.task_done()
