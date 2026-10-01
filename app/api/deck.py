from fastapi import APIRouter, Response

from app.api.schemas import DecisionRequest, Deck, DeckCard, MatchResult
from app.auth import ActiveUid
from app.container import ContainerDep
from app.request_context import IdempotencyKey, UserTimezone

NO_CONTENT = 204

router = APIRouter(prefix="/v2")


@router.get("/deck", response_model=Deck, response_model_exclude_none=True)
def get_deck(uid: ActiveUid, tz: UserTimezone, container: ContainerDep) -> Deck:
    return container.deck_service.get_deck(uid, tz)


@router.post(
    "/decisions",
    response_model=MatchResult,
    response_model_exclude_none=True,
    responses={NO_CONTENT: {"description": "PASS gravado"}},
)
def post_decision(
    body: DecisionRequest,
    uid: ActiveUid,
    tz: UserTimezone,
    key: IdempotencyKey,
    container: ContainerDep,
):
    result = container.decision_service.decide(uid, body.characterId, body.choice, key, tz)
    if result is None:
        return Response(status_code=NO_CONTENT)
    return result


@router.post("/decisions/undo", response_model=DeckCard, response_model_exclude_none=True)
def undo_decision(uid: ActiveUid, tz: UserTimezone, container: ContainerDep) -> DeckCard:
    return container.deck_service.undo(uid, tz)
