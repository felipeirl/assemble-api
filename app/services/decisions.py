"""Pass/Assemble: decisão única por par (uid, characterId), idempotente por Idempotency-Key.

O Pass é gravado na hora. O Assemble é gravado como pendente e resolvido numa fila (afinidade
no Laya, decisão de match, conexão e fala de abertura): o proxy da Discloud corta em ~30 s.
"""

import json
import logging
import random
import threading
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.guardrail import Guardrail, GuardrailUnavailableError
from app.api.schemas import AssembleAccepted
from app.catalog.catalog import CharacterCatalog
from app.catalog.names import pt_br_name
from app.clock import Clock
from app.domain.compatibility import breakdown, score
from app.domain.enums import Choice
from app.domain.match import MatchWeights, decide_match, seeded_chance
from app.domain.models import CharacterTraits, Preferences
from app.errors import ApiError
from app.rate_limit import SlidingWindowLimiter
from app.repositories import (
    DecisionRepository,
    MatchRepository,
    OvertureRepository,
    PersonaRepository,
    UserRepository,
)
from app.services.conversation import ConversationService
from app.services.deck import DeckService
from app.store.base import DELETE_FIELD, DocumentNotFoundError, Increment
from app.timing import timed
from app.work_queue import WorkQueue

PERSONA_AFFINITY_KEYS = ("voice", "values", "relationships", "boundaries", "styles")
USER_BIO_MAX_CHARS = 500

STATUS_PENDING = "pending"
STATUS_MATCHED = "matched"
STATUS_NOT_MATCHED = "not_matched"
STATUS_FAILED = "failed"
OVERTURE_PENDING = "pending"
OVERTURE_SKIPPED = "skipped"
OVERTURE_ACCEPTED = "accepted"
OVERTURE_DECLINED = "declined"
# Assembles que falharam são retomados sozinhos (ao abrir o baralho) até este número de tentativas.
MAX_AUTOMATIC_ATTEMPTS = 3
# Fila cheia: o app tenta de novo depois deste tempo, com a mesma Idempotency-Key.
QUEUE_FULL_RETRY_AFTER = 10

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
        assemble_limiter: SlidingWindowLimiter,
        assembles: WorkQueue,
        overtures: OvertureRepository,
        rng: random.Random | None = None,
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
        self._assemble_limiter = assemble_limiter
        self._assembles = assembles
        self._overtures = overtures
        self._rng = rng or random.Random()
        # (uid, characterId) dos Assembles que estão na fila.
        self._queued: set[tuple[str, str]] = set()
        self._queued_guard = threading.Lock()

    def decide(
        self,
        uid: str,
        character_id: str,
        choice: Choice,
        idempotency_key: str | None,
        tz: ZoneInfo,
        locale: str,
    ) -> AssembleAccepted | None:
        """PASS devolve None (204); ASSEMBLE grava a decisão pendente e devolve o estado (202)."""
        character = self._catalog.get(character_id)
        if character is None:
            raise ApiError("not_found")
        if self._decisions.get(uid, character_id) is not None:
            return self._replay(uid, character_id, idempotency_key, locale)

        date, _ = self._deck.ensure_deck(uid, tz)
        decision: dict[str, Any] = {
            "choice": choice.value,
            "decidedAt": self._clock.now(),
            "deckDate": date,
        }
        if idempotency_key is not None:
            decision["idempotencyKey"] = idempotency_key

        overture = self._pending_overture(uid, character_id)
        if choice is Choice.PASS:
            if not self._decisions.create(uid, character_id, decision):
                return self._replay(uid, character_id, idempotency_key, locale)
            self._deck.record_pass(uid, date, character_id)
            if overture is not None:
                self._overtures.update(uid, character_id, {"status": OVERTURE_DECLINED})
            return None

        decision.update({"status": STATUS_PENDING, "attempts": 1})
        if overture is not None:
            # O personagem já quis: o match está decidido e não gasta Laya nem cota de Assembles.
            decision.update({"matched": True, "match": overture["match"], "overture": True})
        else:
            # Cada Assemble usa o Laya e o modelo: o limite protege a capacidade de todos.
            self._hit_assemble_limit(uid)
        if not self._decisions.create(uid, character_id, decision):
            return self._replay(uid, character_id, idempotency_key, locale)
        if overture is not None:
            self._overtures.update(uid, character_id, {"status": OVERTURE_ACCEPTED})
        self._enqueue_or_fail(uid, character_id, locale)
        return AssembleAccepted(characterId=character_id, status=STATUS_PENDING)

    def _pending_overture(self, uid: str, character_id: str) -> dict[str, Any] | None:
        found = self._overtures.get(uid, character_id)
        return found if found and found.get("status") == OVERTURE_PENDING else None

    def overture(self, uid: str) -> bool:
        """Sorteia um personagem que o usuário ainda não decidiu e "tenta um Assemble" com ele.

        Usa a mesma conta do Assemble do usuário (compatibilidade, afinidade no Laya e sorte). Com
        match, grava uma proposta pendente que o app mostra como "fulano quer dar assemble com
        você"; sem match, grava `skipped` só para o personagem não ser sorteado de novo.
        No máximo uma proposta pendente por usuário. Devolve True se criou uma proposta.
        """
        if self._overtures.pending(uid):
            return False
        taken = self._decisions.decided_ids(uid) | self._overtures.ids(uid)
        pool = sorted(set(self._catalog.eligible()) - taken)
        if not pool:
            return False
        character_id = self._rng.choice(pool)
        character = self._catalog.get(character_id)
        if character is None:
            return False
        outcome = self._outcome(uid, character_id, character)
        proposal: dict[str, Any] = {"createdAt": self._clock.now(), "status": OVERTURE_SKIPPED}
        if outcome["matched"]:
            proposal.update({"status": OVERTURE_PENDING, "match": outcome["match"]})
        self._overtures.create(uid, character_id, proposal)
        return bool(outcome["matched"])

    def resume_unresolved(self, uid: str, locale: str) -> None:
        """Retoma os Assembles do usuário que ficaram pendentes fora da fila (o servidor reiniciou)
        ou falharam, até MAX_AUTOMATIC_ATTEMPTS. Chamado ao abrir o baralho; nunca levanta."""
        for character_id, decision in self._decisions.unresolved(uid):
            if self._is_queued(uid, character_id):
                continue
            failed = decision.get("status") == STATUS_FAILED
            if failed and decision.get("attempts", 1) >= MAX_AUTOMATIC_ATTEMPTS:
                continue
            if failed:
                self._decisions.update(
                    uid,
                    character_id,
                    {"status": STATUS_PENDING, "attempts": Increment(1), "errorCode": DELETE_FIELD},
                )
            if not self._enqueue(uid, character_id, locale):
                logger.warning("Fila de Assembles cheia; retomada fica para a próxima abertura.")
                return

    def _hit_assemble_limit(self, uid: str) -> None:
        retry_after = self._assemble_limiter.hit(uid)
        if retry_after is not None:
            raise ApiError("rate_limited", headers={"Retry-After": str(retry_after)})

    def _is_queued(self, uid: str, character_id: str) -> bool:
        with self._queued_guard:
            return (uid, character_id) in self._queued

    def _enqueue(self, uid: str, character_id: str, locale: str) -> bool:
        key = (uid, character_id)
        with self._queued_guard:
            if key in self._queued:
                return True
            self._queued.add(key)
        if self._assembles.submit(lambda: self._resolve(uid, character_id, locale)):
            return True
        with self._queued_guard:
            self._queued.discard(key)
        return False

    def _enqueue_or_fail(self, uid: str, character_id: str, locale: str) -> None:
        if self._enqueue(uid, character_id, locale):
            return
        self._mark(
            uid, character_id, {"status": STATUS_FAILED, "errorCode": "provider_unavailable"}
        )
        raise ApiError("provider_unavailable", headers={"Retry-After": str(QUEUE_FULL_RETRY_AFTER)})

    def _resolve(self, uid: str, character_id: str, locale: str) -> None:
        """Roda na fila: decide o match e, com match, cria a conexão com a fala de abertura.

        Qualquer falha marca a decisão como `failed`: ela nunca fica pendente para sempre.
        """
        try:
            with timed("assemble na fila (total)"):
                self._resolve_pending(uid, character_id, locale)
        except (ApiError, GuardrailUnavailableError) as exc:
            logger.warning("Assemble falhou: %s", type(exc).__name__)
            self._mark(
                uid, character_id, {"status": STATUS_FAILED, "errorCode": "provider_unavailable"}
            )
        except Exception:
            logger.exception("Assemble falhou sem tratamento.")
            self._mark(
                uid, character_id, {"status": STATUS_FAILED, "errorCode": "provider_unavailable"}
            )
        finally:
            with self._queued_guard:
                self._queued.discard((uid, character_id))

    def _resolve_pending(self, uid: str, character_id: str, locale: str) -> None:
        decision = self._decisions.get(uid, character_id)
        if decision is None or decision.get("status") != STATUS_PENDING:
            return
        character = self._catalog.get(character_id)
        if character is None:
            logger.info("Assemble descartado: o personagem saiu do catálogo.")
            return
        if "matched" not in decision:
            outcome = self._outcome(uid, character_id, character)
            if not self._mark(uid, character_id, outcome):
                return
            decision.update(outcome)
        if decision["matched"]:
            with timed("conexao e abertura (total)"):
                self._ensure_match(uid, character_id, character, decision["match"], locale)
            self._mark(uid, character_id, {"status": STATUS_MATCHED})
        else:
            self._mark(uid, character_id, {"status": STATUS_NOT_MATCHED})

    def _outcome(self, uid: str, character_id: str, character: dict[str, Any]) -> dict[str, Any]:
        """Decisão de match; com match, guarda o que a conexão precisa para ser refeita."""
        prefs = self._users.preferences(uid)
        traits = CharacterTraits.model_validate(character)
        compatibility = score(prefs, traits)
        if character_id in self._users.force_match(uid):
            return self._forced_match(prefs, traits, compatibility)
        outcome = decide_match(
            compatibility,
            affinity=self._timed_affinity(uid, character_id, prefs),
            luck=seeded_chance(uid, character_id),
            weights=self._weights,
        )
        fields: dict[str, Any] = {"matched": outcome.matched}
        if outcome.matched:
            fields["match"] = {
                "score": compatibility,
                "matchChance": outcome.chance,
                "decisionVersion": outcome.version,
                "whyYouMatch": [
                    {"category": m.category.value, "traits": m.traits}
                    for m in breakdown(prefs, traits)
                ],
            }
        return fields

    @staticmethod
    def _forced_match(
        prefs: Preferences, traits: CharacterTraits, compatibility: int
    ) -> dict[str, Any]:
        """Match sem Laya nem sorteio, para a conta de demonstração (`forceMatch`)."""
        return {
            "matched": True,
            "match": {
                "score": compatibility,
                "matchChance": 1.0,
                "decisionVersion": "forced",
                "whyYouMatch": [
                    {"category": m.category.value, "traits": m.traits}
                    for m in breakdown(prefs, traits)
                ],
            },
        }

    def _mark(self, uid: str, character_id: str, fields: dict[str, Any]) -> bool:
        """Atualiza a decisão; False se ela já não existe (conta apagada)."""
        try:
            self._decisions.update(uid, character_id, fields)
        except DocumentNotFoundError:
            logger.info("Assemble descartado: a decisão foi apagada.")
            return False
        return True

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
            looking_for = self._users.looking_for(uid)
            if looking_for and not self._guardrail.check_source(looking_for).blocked:
                profile["lookingFor"] = looking_for
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
        opener = self._conversation.generate_opener(uid, character_id, character, locale)
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
        idempotency_key: str | None,
        locale: str,
    ) -> AssembleAccepted | None:
        """Mesma Idempotency-Key: devolve o estado gravado. Um Assemble que falhou, ou ficou
        pendente fora da fila, volta para a fila (e conta no limite por hora)."""
        decision = self._decisions.get(uid, character_id) or {}
        if idempotency_key is None or decision.get("idempotencyKey") != idempotency_key:
            raise ApiError("already_decided")
        if decision.get("choice") == Choice.PASS.value:
            return None
        status = assemble_status(decision)
        orphan = status == STATUS_PENDING and not self._is_queued(uid, character_id)
        if status == STATUS_FAILED or orphan:
            self._hit_assemble_limit(uid)
            self._mark(
                uid,
                character_id,
                {"status": STATUS_PENDING, "attempts": Increment(1), "errorCode": DELETE_FIELD},
            )
            self._enqueue_or_fail(uid, character_id, locale)
            status = STATUS_PENDING
        return AssembleAccepted(characterId=character_id, status=status)


def assemble_status(decision: dict[str, Any]) -> str:
    """Estado do Assemble; decisões gravadas antes da fila não têm `status` (já resolvidas)."""
    if "status" in decision:
        return decision["status"]
    return STATUS_MATCHED if decision.get("matched") else STATUS_NOT_MATCHED


def _pt_br_name_field(character_id: str) -> dict[str, str]:
    """O app lê `characterName` direto do Firestore; o nome em português vai em campo próprio."""
    name = pt_br_name(character_id)
    return {"characterNamePtBR": name} if name else {}
