"""Baralho (seção 8): até 40 decisões por dia, sem reposição, Undo do último Pass.

O baralho é sorteado de novo a cada chamada: abrir o app gira os personagens que ainda não foram
decididos. A cota do dia é fixa; o que muda é quais personagens aparecem.
"""

import random
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from app.api.schemas import Deck, DeckCard
from app.catalog.catalog import CharacterCatalog
from app.catalog.names import display_name
from app.catalog.summary import tagline
from app.clock import Clock
from app.domain import deck as deck_rules
from app.domain.compatibility import score, traits_in_common
from app.domain.enums import Choice
from app.domain.models import CharacterTraits, Preferences
from app.errors import ApiError
from app.repositories import DecisionRepository, DeckRepository, UserRepository
from app.store.base import DELETE_FIELD

LAST_PASS_FIELD = "lastPassCharacterId"


class DeckService:
    def __init__(
        self,
        catalog: CharacterCatalog,
        users: UserRepository,
        decisions: DecisionRepository,
        decks: DeckRepository,
        clock: Clock,
        deck_size: int,
        rng_factory: Callable[[], random.Random] = random.Random,
    ) -> None:
        self._catalog = catalog
        self._users = users
        self._decisions = decisions
        self._decks = decks
        self._clock = clock
        self._deck_size = deck_size
        self._rng_factory = rng_factory

    def today(self, tz: ZoneInfo) -> str:
        return deck_rules.local_date(self._clock.now(), tz).isoformat()

    def ensure_deck(self, uid: str, tz: ZoneInfo) -> tuple[str, dict[str, Any]]:
        """Documento do dia (Undo e metadados); criado na primeira chamada, sem os cards."""
        date = self.today(tz)
        existing = self._decks.get(uid, date)
        if existing is not None:
            return date, existing
        deck = {
            "generatedAt": self._clock.now(),
            "algorithmVersion": deck_rules.ALGORITHM_VERSION,
        }
        if not self._decks.create(uid, date, deck):
            deck = self._decks.get(uid, date)
        return date, deck

    def get_deck(self, uid: str, tz: ZoneInfo, locale: str) -> Deck:
        date, deck = self.ensure_deck(uid, tz)
        prefs = self._users.preferences(uid)
        decided = self._decisions.decided_ids(uid)
        decided_today = self._decisions.count_on_date(uid, date)
        pool = self._candidates(prefs, decided)
        rng = self._rng_factory()
        chosen = deck_rules.select_deck(pool, max(0, self._deck_size - decided_today), rng)
        rng.shuffle(chosen)
        cards = []
        for character_id in chosen:
            doc = self._catalog.get(character_id)
            if doc is not None:
                cards.append(build_card(character_id, doc, prefs, locale))
        return Deck(
            date=date,
            cards=cards,
            remaining=len(cards),
            total=min(self._deck_size, decided_today + len(pool)),
            nextDeckAt=deck_rules.next_deck_at(self._clock.now(), tz),
            canUndo=self._undo_target(uid, date, deck) is not None,
        )

    def record_pass(self, uid: str, date: str, character_id: str) -> None:
        self._decks.update(uid, date, {LAST_PASS_FIELD: character_id})

    def undo(self, uid: str, tz: ZoneInfo, locale: str) -> DeckCard:
        date, deck = self.ensure_deck(uid, tz)
        character_id = self._undo_target(uid, date, deck)
        if character_id is None:
            raise ApiError("nothing_to_undo")
        doc = self._catalog.get(character_id)
        if doc is None:
            raise ApiError("not_found")
        self._decisions.delete(uid, character_id)
        self._decks.update(uid, date, {LAST_PASS_FIELD: DELETE_FIELD})
        return build_card(character_id, doc, self._users.preferences(uid), locale)

    def _undo_target(self, uid: str, date: str, deck: dict[str, Any]) -> str | None:
        character_id = deck.get(LAST_PASS_FIELD)
        if not character_id:
            return None
        decision = self._decisions.get(uid, character_id)
        if decision is None or decision.get("choice") != Choice.PASS.value:
            return None
        if decision.get("deckDate") != date:
            return None
        return character_id

    def _candidates(self, prefs: Preferences, decided: set[str]) -> list[deck_rules.Candidate]:
        """Personagens elegíveis que o usuário ainda não decidiu, com a nota de cada um."""
        now = self._clock.now()
        return [
            deck_rules.Candidate(
                character_id=character_id,
                score=score(prefs, CharacterTraits.model_validate(doc)),
                origin=doc.get("origin"),
                teams=tuple(doc.get("teams") or ()),
                is_new=deck_rules.is_new(doc.get("ingestedAt"), now),
            )
            for character_id, doc in self._catalog.eligible().items()
            if character_id not in decided
        ]


def build_card(character_id: str, doc: dict[str, Any], prefs: Preferences, locale: str) -> DeckCard:
    return DeckCard(
        characterId=character_id,
        name=display_name(character_id, doc["name"], locale),
        imageUrl=doc.get("imageUrl"),
        tagline=tagline(doc, locale),
        traitsInCommon=traits_in_common(prefs, CharacterTraits.model_validate(doc)),
    )
