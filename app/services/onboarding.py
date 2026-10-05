"""Rodada de reação do cadastro: Curti/Pular só para ensinar o gosto, sem virar decisão.

O personagem continua no baralho e pode virar conexão depois; o sinal só alimenta as
sugestões aprendidas (`DeckService._taste`).
"""

import random
from collections.abc import Callable

from app.api.schemas import DeckCard
from app.catalog.catalog import CharacterCatalog
from app.clock import Clock
from app.domain import reaction
from app.domain.models import CharacterTraits
from app.errors import ApiError
from app.repositories import DecisionRepository, TasteSignalRepository, UserRepository
from app.services.deck import build_card


class OnboardingService:
    def __init__(
        self,
        catalog: CharacterCatalog,
        users: UserRepository,
        decisions: DecisionRepository,
        signals: TasteSignalRepository,
        clock: Clock,
        rng_factory: Callable[[], random.Random] = random.Random,
    ) -> None:
        self._catalog = catalog
        self._users = users
        self._decisions = decisions
        self._signals = signals
        self._clock = clock
        self._rng_factory = rng_factory

    def reaction_cards(self, uid: str, locale: str) -> list[DeckCard]:
        decided = self._decisions.decided_ids(uid)
        eligible = self._catalog.eligible()
        candidates = {
            character_id: CharacterTraits.model_validate(doc)
            for character_id, doc in eligible.items()
            if character_id not in decided
        }
        chosen = reaction.select_reaction_cards(
            candidates, reaction.REACTION_CARDS, self._rng_factory()
        )
        prefs = self._users.preferences(uid)
        return [build_card(cid, eligible[cid], prefs, locale) for cid in chosen]

    def record_signal(self, uid: str, character_id: str, liked: bool) -> None:
        if self._catalog.get(character_id) is None:
            raise ApiError("not_found")
        self._signals.save(uid, character_id, {"liked": liked, "at": self._clock.now()})
