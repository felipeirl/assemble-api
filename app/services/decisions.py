"""Pass/Assemble: decisão única por par (uid, characterId), idempotente por Idempotency-Key."""

import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.guardrail import Guardrail, GuardrailUnavailableError
from app.api.schemas import MatchCharacter, MatchResult
from app.catalog.catalog import CharacterCatalog
from app.catalog.names import display_name, pt_br_name
from app.clock import Clock
from app.domain.compatibility import breakdown, score
from app.domain.enums import Choice
from app.domain.match import MatchWeights, decide_match, seeded_chance
from app.domain.models import CharacterTraits, Preferences
from app.errors import ApiError
from app.repositories import (
    DecisionRepository,
    MatchRepository,
    PersonaRepository,
    UserRepository,
)
from app.services.conversation import ConversationService
from app.services.deck import DeckService
from app.timing import timed

PERSONA_AFFINITY_KEYS = ("voice", "values", "relationships", "boundaries", "styles")
USER_BIO_MAX_CHARS = 500

logger = logging.getLogger(__name__)


class DecisionService:
    def __init__(
        self,
        catalog: CharacterCatalog,
        users: UserRepository,
        decisions: DecisionRepository,
        matches: MatchRepository,
        deck: DeckService,
        conversation: ConversationService,
        personas: PersonaRepository,
        guardrail: Guardrail | None,
        clock: Clock,
        weights: MatchWeights,
    ) -> None:
        self._catalog = catalog
        self._users = users
        self._decisions = decisions
        self._matches = matches
        self._deck = deck
        self._conversation = conversation
        self._personas = personas
        self._guardrail = guardrail
        self._clock = clock
        self._weights = weights

    def decide(
        self,
        uid: str,
        character_id: str,
        choice: Choice,
        idempotency_key: str | None,
        tz: ZoneInfo,
        locale: str,
    ) -> MatchResult | None:
        """PASS devolve None (204); ASSEMBLE devolve o MatchResult."""
        character = self._catalog.get(character_id)
        if character is None:
            raise ApiError("not_found")
        if self._decisions.get(uid, character_id) is not None:
            return self._replay(uid, character_id, character, idempotency_key, locale)

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
                return self._replay(uid, character_id, character, idempotency_key, locale)
            self._deck.record_pass(uid, date, character_id)
            return None

        prefs = self._users.preferences(uid)
        traits = CharacterTraits.model_validate(character)
        compatibility = score(prefs, traits)
        outcome = decide_match(
            compatibility,
            affinity=self._timed_affinity(uid, character_id, prefs),
            luck=seeded_chance(uid, character_id),
            weights=self._weights,
        )
        decision["matched"] = outcome.matched
        if outcome.matched:
            # Guardado na decisão para refazer a conexão se a fala de abertura falhar.
            decision["match"] = {
                "score": compatibility,
                "matchChance": outcome.chance,
                "decisionVersion": outcome.version,
                "whyYouMatch": [
                    {"category": m.category.value, "traits": m.traits}
                    for m in breakdown(prefs, traits)
                ],
            }
        if not self._decisions.create(uid, character_id, decision):
            return self._replay(uid, character_id, character, idempotency_key, locale)
        if not outcome.matched:
            return MatchResult(matched=False)
        with timed("conexao e abertura (total)"):
            match = self._ensure_match(uid, character_id, character, decision["match"], locale)
        return match_result(character_id, character, match, locale)

    def _timed_affinity(self, uid: str, character_id: str, prefs: Preferences) -> float | None:
        with timed("afinidade (Laya)"):
            return self._affinity(uid, character_id, prefs)

    def _affinity(self, uid: str, character_id: str, prefs: Preferences) -> float | None:
        """Afinidade da persona pelo usuário (Laya); None = modo degradado, sem inventar."""
        persona = self._personas.get(character_id)
        if self._guardrail is None or persona is None:
            return None
        user = self._users.get(uid) or {}
        profile = {"preferences": prefs.model_dump(mode="json")}
        sheet = {key: persona[key] for key in PERSONA_AFFINITY_KEYS if persona.get(key)}
        try:
            # A bio é escrita pelo usuário: dado não confiável, truncado e checado antes do uso.
            bio = str(user.get("bio") or "").strip()[:USER_BIO_MAX_CHARS]
            if bio and not self._guardrail.check_source(bio).blocked:
                profile["bio"] = bio
            return self._guardrail.affinity(
                json.dumps(profile, ensure_ascii=False), json.dumps(sheet, ensure_ascii=False)
            )
        except GuardrailUnavailableError:
            logger.warning("Laya indisponível; decisão de match no modo degradado.")
            return None

    def _ensure_match(
        self,
        uid: str,
        character_id: str,
        character: dict[str, Any],
        decided: dict[str, Any],
        locale: str,
    ) -> dict[str, Any]:
        """Cria a conexão com a fala de abertura antes de responder (idempotente)."""
        existing = self._matches.get(uid, character_id)
        if existing is not None:
            return existing
        opener = self._conversation.generate_opener(character_id, character, locale)
        match: dict[str, Any] = {
            **decided,
            "createdAt": self._clock.now(),
            "characterName": character["name"],
            **_pt_br_name_field(character_id),
            "userMessageCount": 0,
            "hidden": False,
            **self._conversation.save_opener(uid, character_id, opener),
        }
        if character.get("imageUrl"):
            match["imageUrl"] = character["imageUrl"]
        if not self._matches.create(uid, character_id, match):
            return self._matches.get(uid, character_id) or match
        return match

    def _replay(
        self,
        uid: str,
        character_id: str,
        character: dict[str, Any],
        idempotency_key: str | None,
        locale: str,
    ) -> MatchResult | None:
        decision = self._decisions.get(uid, character_id) or {}
        if idempotency_key is None or decision.get("idempotencyKey") != idempotency_key:
            raise ApiError("already_decided")
        if decision.get("choice") == Choice.PASS.value:
            return None
        if not decision.get("matched"):
            return MatchResult(matched=False)
        match = self._ensure_match(uid, character_id, character, decision["match"], locale)
        return match_result(character_id, character, match, locale)


def _pt_br_name_field(character_id: str) -> dict[str, str]:
    """O app lê `characterName` direto do Firestore; o nome em português vai em campo próprio."""
    name = pt_br_name(character_id)
    return {"characterNamePtBR": name} if name else {}


def match_result(
    character_id: str, character: dict[str, Any], match: dict[str, Any], locale: str
) -> MatchResult:
    reasons = [trait for item in match.get("whyYouMatch", []) for trait in item["traits"]]
    return MatchResult(
        matched=True,
        connectionId=character_id,
        character=MatchCharacter(
            characterId=character_id,
            name=display_name(character_id, character["name"], locale),
            imageUrl=character.get("imageUrl"),
        ),
        score=match["score"],
        reasons=reasons,
    )
