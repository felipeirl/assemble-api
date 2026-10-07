from fastapi import APIRouter, Response

from app.api.schemas import (
    AcceptedMessage,
    CharacterIdPath,
    CharacterView,
    PhotoSignature,
    RegeneratedReply,
    RewindRequest,
    SendMessageRequest,
    UserStats,
)
from app.auth import ActiveUid
from app.container import ContainerDep
from app.errors import ApiError
from app.request_context import IdempotencyKey, Locale

NO_CONTENT = 204
ACCEPTED = 202

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
    status_code=ACCEPTED,
    response_model=AcceptedMessage,
    response_model_exclude_none=True,
)
def send_message(
    connection_id: CharacterIdPath,
    body: SendMessageRequest,
    uid: ActiveUid,
    key: IdempotencyKey,
    locale: Locale,
    container: ContainerDep,
) -> AcceptedMessage:
    # A resposta do personagem é gerada na fila e chega ao app pelo Firestore.
    message = container.conversation_service.send(uid, connection_id, body.text, key, locale)
    return AcceptedMessage(userMessage=message)


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


@router.post("/me/photo/signature", response_model=PhotoSignature)
def photo_signature(uid: ActiveUid, container: ContainerDep) -> PhotoSignature:
    if container.photos is None:
        raise ApiError("provider_unavailable")
    upload_url, fields = container.photos.upload_signature(uid)
    return PhotoSignature(uploadUrl=upload_url, fields=fields)


@router.get("/me/stats", response_model=UserStats)
def get_stats(uid: ActiveUid, container: ContainerDep) -> UserStats:
    return container.profile_service.stats(uid)
