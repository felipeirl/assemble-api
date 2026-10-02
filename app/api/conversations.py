from fastapi import APIRouter

from app.api.schemas import (
    CharacterIdPath,
    CharacterReply,
    CharacterView,
    SendMessageRequest,
    UserStats,
)
from app.auth import ActiveUid
from app.container import ContainerDep
from app.request_context import IdempotencyKey, Locale

router = APIRouter(prefix="/v2")


@router.get(
    "/characters/{character_id}",
    response_model=CharacterView,
    response_model_exclude_none=True,
)
def get_character(
    character_id: CharacterIdPath, uid: ActiveUid, container: ContainerDep
) -> CharacterView:
    return container.profile_service.character(uid, character_id)


@router.post(
    "/connections/{connection_id}/messages",
    response_model=CharacterReply,
    response_model_exclude_none=True,
)
def send_message(
    connection_id: CharacterIdPath,
    body: SendMessageRequest,
    uid: ActiveUid,
    key: IdempotencyKey,
    locale: Locale,
    container: ContainerDep,
) -> CharacterReply:
    return container.conversation_service.send(uid, connection_id, body.text, key, locale)


@router.get("/me/stats", response_model=UserStats)
def get_stats(uid: ActiveUid, container: ContainerDep) -> UserStats:
    return container.profile_service.stats(uid)
