"""Pass/Assemble: decisão única por par (uid, characterId), idempotente por Idempotency-Key."""

from typing import Any
from zoneinfo import ZoneInfo

from app.api.schemas import MatchCharacter, MatchResult
from app.catalog.catalog import CharacterCatalog
from app.clock import Clock
from app.domain.compatibility import breakdown, score
from app.domain.enums import Choice
from app.domain.match import MatchWeights, decide_match, seeded_chance
from app.domain.models import CharacterTraits
from app.errors import ApiError
from app.repositories import DecisionRepository, MatchRepository, UserRepository
from app.services.deck import DeckService


class DecisionService:
    def __init__(
        self,
        catalog: CharacterCatalog,
        users: UserRepository,
        decisions: DecisionRepository,
        matches: MatchRepository,
        deck: DeckService,
        clock: Clock,
        weights: MatchWeights,
    ) -> None:
        self._catalog = catalog
        self._users = users
        self._decisions = decisions
        self._matches = matches
        self._deck = deck
        self._clock = clock
        self._weights = weights

    def decide(
        self,
        uid: str,
        character_id: str,
        choice: Choice,
        idempotency_key: str | None,
        tz: ZoneInfo,
    ) -> MatchResult | None:
        """PASS devolve None (204); ASSEMBLE devolve o MatchResult."""
        character = self._catalog.get(character_id)
        if character is None:
            raise ApiError("not_found")
        if self._decisions.get(uid, character_id) is not None:
            return self._replay(uid, character_id, character, idempotency_key)

        date, _ = self._deck.ensure_deck(uid, tz)
        decision: dict[str, Any] = {
            "choice": choice.value,
            "decidedAt": self._clock.now(),
            "deckDate": date,
        }
        if idempotency_key is not None:
            decision["idempotencyKey"] = idempotency_key

        if choice is Choice.PASS:
            if not self._decisions.create(uid, character_id, decision):
                return self._replay(uid, character_id, character, idempotency_key)
            self._deck.record_pass(uid, date, character_id)
            return None

        prefs = self._users.preferences(uid)
        traits = CharacterTraits.model_validate(character)
        compatibility = score(prefs, traits)
        outcome = decide_match(
            compatibility,
            affinity=None,
            luck=seeded_chance(uid, character_id),
            weights=self._weights,
        )
        decision["matched"] = outcome.matched
        if not self._decisions.create(uid, character_id, decision):
            return self._replay(uid, character_id, character, idempotency_key)
        if not outcome.matched:
            return MatchResult(matched=False)

        why = [{"category": m.category.value, "traits": m.traits} for m in breakdown(prefs, traits)]
        now = self._clock.now()
        match: dict[str, Any] = {
            "score": compatibility,
            "matchChance": outcome.chance,
            "decisionVersion": outcome.version,
            "whyYouMatch": why,
            "createdAt": now,
            "lastMessageAt": now,
            "characterName": character["name"],
            "userMessageCount": 0,
            "suggestions": [],
            "hidden": False,
        }
        if character.get("imageUrl"):
            match["imageUrl"] = character["imageUrl"]
        self._matches.create(uid, character_id, match)
        return match_result(character_id, character, self._matches.get(uid, character_id))

    def _replay(
        self,
        uid: str,
        character_id: str,
        character: dict[str, Any],
        idempotency_key: str | None,
    ) -> MatchResult | None:
        decision = self._decisions.get(uid, character_id) or {}
        if idempotency_key is None or decision.get("idempotencyKey") != idempotency_key:
            raise ApiError("already_decided")
        if decision.get("choice") == Choice.PASS.value:
            return None
        if not decision.get("matched"):
            return MatchResult(matched=False)
        match = self._matches.get(uid, character_id)
        if match is None:
            raise ApiError("already_decided")
        return match_result(character_id, character, match)


def match_result(
    character_id: str, character: dict[str, Any], match: dict[str, Any]
) -> MatchResult:
    reasons = [trait for item in match.get("whyYouMatch", []) for trait in item["traits"]]
    return MatchResult(
        matched=True,
        connectionId=character_id,
        character=MatchCharacter(
            characterId=character_id,
            name=character["name"],
            imageUrl=character.get("imageUrl"),
        ),
        score=match["score"],
        reasons=reasons,
    )
