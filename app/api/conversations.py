from fastapi import APIRouter, Response

from app.api.schemas import (
    CharacterIdPath,
    CharacterReply,
    CharacterView,
    RegeneratedReply,
    RewindRequest,
    SendMessageRequest,
    UserStats,
)
from app.auth import ActiveUid
from app.container import ContainerDep
from app.request_context import IdempotencyKey, Locale

NO_CONTENT = 204

router = APIRouter(prefix="/v2")


@router.get(
    "/characters/{character_id}",
    response_model=CharacterView,
    response_model_exclude_none=True,
)
def get_character(
    character_id: CharacterIdPath, uid: ActiveUid, locale: Locale, container: ContainerDep
) -> CharacterView:
    return container.profile_service.character(uid, character_id, locale)


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


@router.post(
    "/connections/{connection_id}/messages/regenerate",
    response_model=RegeneratedReply,
    response_model_exclude_none=True,
)
def regenerate_message(
    connection_id: CharacterIdPath, uid: ActiveUid, locale: Locale, container: ContainerDep
) -> RegeneratedReply:
    return container.conversation_service.regenerate(uid, connection_id, locale)


@router.post("/connections/{connection_id}/messages/rewind", status_code=NO_CONTENT)
def rewind_conversation(
    connection_id: CharacterIdPath,
    body: RewindRequest,
    uid: ActiveUid,
    locale: Locale,
    container: ContainerDep,
) -> Response:
    container.conversation_service.rewind(uid, connection_id, body.messageId, locale)
    return Response(status_code=NO_CONTENT)


@router.get("/me/stats", response_model=UserStats)
def get_stats(uid: ActiveUid, container: ContainerDep) -> UserStats:
    return container.profile_service.stats(uid)
