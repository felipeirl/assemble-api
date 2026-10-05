"""Baralho diário (seção 8): até 40 por dia, sem reposição, Undo do último Pass."""

import random
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
    ) -> None:
        self._catalog = catalog
        self._users = users
        self._decisions = decisions
        self._decks = decks
        self._clock = clock
        self._deck_size = deck_size

    def today(self, tz: ZoneInfo) -> str:
        return deck_rules.local_date(self._clock.now(), tz).isoformat()

    def ensure_deck(self, uid: str, tz: ZoneInfo) -> tuple[str, dict[str, Any]]:
        """Baralho do dia; gerado e gravado na primeira chamada."""
        date = self.today(tz)
        existing = self._decks.get(uid, date)
        if existing is not None:
            return date, existing
        deck = {
            "characterIds": self._select(uid, date),
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
        cards = []
        for character_id in deck["characterIds"]:
            if character_id in decided:
                continue
            doc = self._catalog.get(character_id)
            if doc is not None:
                cards.append(build_card(character_id, doc, prefs, locale))
        random.shuffle(cards)
        return Deck(
            date=date,
            cards=cards,
            remaining=len(cards),
            total=len(deck["characterIds"]),
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

    def _select(self, uid: str, date: str) -> list[str]:
        prefs = self._users.preferences(uid)
        decided = self._decisions.decided_ids(uid)
        now = self._clock.now()
        candidates = [
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
        rng = random.Random(f"{uid}:{date}")
        return deck_rules.select_deck(candidates, self._deck_size, rng)


def build_card(character_id: str, doc: dict[str, Any], prefs: Preferences, locale: str) -> DeckCard:
    return DeckCard(
        characterId=character_id,
        name=display_name(character_id, doc["name"], locale),
        imageUrl=doc.get("imageUrl"),
        tagline=tagline(doc, locale),
        traitsInCommon=traits_in_common(prefs, CharacterTraits.model_validate(doc)),
    )
