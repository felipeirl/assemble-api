from fastapi import APIRouter, BackgroundTasks, Depends, Response

from app.auth import require_jobs_key
from app.container import ContainerDep
from app.errors import ApiError

ACCEPTED = 202
# Fichas e traduções usam o mesmo modelo: um job por vez evita estourar limite e tempo.
LLM_BATCH = "llm-batch"

router = APIRouter(prefix="/jobs", dependencies=[Depends(require_jobs_key)])


@router.post("/ingest", status_code=ACCEPTED)
def ingest(background: BackgroundTasks, container: ContainerDep) -> Response:
    if container.ingest is None:
        raise ApiError("provider_unavailable")
    background.add_task(container.job_runner.run_exclusive, "ingest", container.ingest.run)
    return Response(status_code=ACCEPTED)


@router.post("/personas", status_code=ACCEPTED)
def personas(background: BackgroundTasks, container: ContainerDep) -> Response:
    service = container.persona_service
    if service is None:
        raise ApiError("provider_unavailable")
    background.add_task(
        container.job_runner.run_exclusive, "personas", service.run, serialize_with=LLM_BATCH
    )
    return Response(status_code=ACCEPTED)


@router.post("/purge", status_code=ACCEPTED)
def purge(background: BackgroundTasks, container: ContainerDep) -> Response:
    service = container.account_service
    background.add_task(container.job_runner.run_exclusive, "purge", service.purge)
    return Response(status_code=ACCEPTED)


@router.post("/translations", status_code=ACCEPTED)
def translations(background: BackgroundTasks, container: ContainerDep) -> Response:
    service = container.translation_service
    if service is None:
        raise ApiError("provider_unavailable")
    background.add_task(
        container.job_runner.run_exclusive, "translations", service.run, serialize_with=LLM_BATCH
    )
    return Response(status_code=ACCEPTED)
