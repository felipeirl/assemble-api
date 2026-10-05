from fastapi import APIRouter, Response

from app.api.schemas import DeactivationResult
from app.auth import ActiveUid, AnyStatusIdentity, AnyStatusUid
from app.container import ContainerDep
from app.request_context import Locale

NO_CONTENT = 204

router = APIRouter(prefix="/v2")


@router.post("/chats/hide", status_code=NO_CONTENT)
def hide_chats(uid: ActiveUid, container: ContainerDep) -> Response:
    container.account_service.hide_chats(uid)
    return Response(status_code=NO_CONTENT)


@router.post("/account/deactivate", response_model=DeactivationResult)
def deactivate(uid: ActiveUid, container: ContainerDep) -> DeactivationResult:
    return DeactivationResult(purgeAt=container.account_service.deactivate(uid))


@router.post("/account/email-verification", status_code=NO_CONTENT)
def send_email_verification(
    identity: AnyStatusIdentity, locale: Locale, container: ContainerDep
) -> Response:
    """Manda o e-mail de confirmação em HTML; 503 sem SMTP (o app usa o e-mail do Firebase)."""
    container.verification_service.send(identity, locale)
    return Response(status_code=NO_CONTENT)


@router.post("/account/reactivate", status_code=NO_CONTENT)
def reactivate(uid: AnyStatusUid, container: ContainerDep) -> Response:
    container.account_service.reactivate(uid)
    return Response(status_code=NO_CONTENT)
