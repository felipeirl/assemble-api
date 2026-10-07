from fastapi import APIRouter, Response

from app.api.schemas import AssembleAccepted, DecisionRequest, Deck, DeckCard
from app.auth import ActiveUid
from app.container import ContainerDep
from app.request_context import IdempotencyKey, Locale, UserTimezone

NO_CONTENT = 204
ACCEPTED = 202

router = APIRouter(prefix="/v2")


@router.get("/deck", response_model=Deck, response_model_exclude_none=True)
def get_deck(uid: ActiveUid, tz: UserTimezone, locale: Locale, container: ContainerDep) -> Deck:
    # Abrir o baralho retoma os Assembles que se perderam num reinício ou falharam.
    container.decision_service.resume_unresolved(uid, locale)
    return container.deck_service.get_deck(uid, tz, locale)


@router.post(
    "/decisions",
    status_code=ACCEPTED,
    response_model=AssembleAccepted,
    responses={NO_CONTENT: {"description": "PASS gravado"}},
)
def post_decision(
    body: DecisionRequest,
    uid: ActiveUid,
    tz: UserTimezone,
    key: IdempotencyKey,
    locale: Locale,
    container: ContainerDep,
):
    result = container.decision_service.decide(uid, body.characterId, body.choice, key, tz, locale)
    if result is None:
        return Response(status_code=NO_CONTENT)
    return result


@router.post("/decisions/undo", response_model=DeckCard, response_model_exclude_none=True)
def undo_decision(
    uid: ActiveUid, tz: UserTimezone, locale: Locale, container: ContainerDep
) -> DeckCard:
    return container.deck_service.undo(uid, tz, locale)
