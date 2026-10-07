"""Personagens que tentam um Assemble com o usuário, sem ele saber, de tempos em tempos."""

import logging
import threading

from app.repositories import UserRepository
from app.services.decisions import DecisionService

logger = logging.getLogger(__name__)


class OvertureService:
    def __init__(self, users: UserRepository, decisions: DecisionService) -> None:
        self._users = users
        self._decisions = decisions

    def run(self) -> int:
        """Uma rodada para todos os usuários ativos; devolve quantas propostas nasceram."""
        created = 0
        for uid in self._users.active_ids():
            try:
                created += self._decisions.overture(uid)
            except Exception:
                logger.exception("Tentativa de Assemble do personagem falhou (uid=%s).", uid)
        logger.info("Rodada de personagens: %d propostas novas.", created)
        return created


def run_overtures_every(interval_minutes: int, run: "callable", stop: threading.Event) -> None:
    """Repete `run` a cada `interval_minutes`, até `stop`. A primeira rodada vem depois de um
    intervalo inteiro, não no boot."""
    while not stop.wait(interval_minutes * 60):
        try:
            run()
        except Exception:
            logger.exception("Rodada de personagens falhou.")
