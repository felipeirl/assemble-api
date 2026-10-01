from fastapi import APIRouter, Response

from app.api.schemas import DeactivationResult
from app.auth import ActiveUid, AnyStatusUid
from app.container import ContainerDep

NO_CONTENT = 204

router = APIRouter(prefix="/v2")


@router.post("/chats/hide", status_code=NO_CONTENT)
def hide_chats(uid: ActiveUid, container: ContainerDep) -> Response:
    container.account_service.hide_chats(uid)
    return Response(status_code=NO_CONTENT)


@router.post("/account/deactivate", response_model=DeactivationResult)
def deactivate(uid: ActiveUid, container: ContainerDep) -> DeactivationResult:
    return DeactivationResult(purgeAt=container.account_service.deactivate(uid))


@router.post("/account/reactivate", status_code=NO_CONTENT)
def reactivate(uid: AnyStatusUid, container: ContainerDep) -> Response:
    container.account_service.reactivate(uid)
    return Response(status_code=NO_CONTENT)
