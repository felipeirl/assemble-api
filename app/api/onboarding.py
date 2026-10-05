from fastapi import APIRouter, Response

from app.api.schemas import CharacterIdPath, ReactionCards, TasteSignalRequest
from app.auth import ActiveUid
from app.container import ContainerDep
from app.request_context import Locale

NO_CONTENT = 204

router = APIRouter(prefix="/v2")


@router.get(
    "/onboarding/reaction-cards", response_model=ReactionCards, response_model_exclude_none=True
)
def reaction_cards(uid: ActiveUid, locale: Locale, container: ContainerDep) -> ReactionCards:
    return ReactionCards(cards=container.onboarding_service.reaction_cards(uid, locale))


@router.put("/taste-signals/{character_id}", status_code=NO_CONTENT)
def put_taste_signal(
    character_id: CharacterIdPath,
    body: TasteSignalRequest,
    uid: ActiveUid,
    container: ContainerDep,
) -> Response:
    container.onboarding_service.record_signal(uid, character_id, body.liked)
    return Response(status_code=NO_CONTENT)
