from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from app.clock import Clock
from app.config import Settings
from app.store.base import DocumentStore

if TYPE_CHECKING:
    from app.auth import TokenVerifier


@dataclass
class Container:
    """Dependências do processo, montadas uma vez e lidas pelas rotas."""

    settings: Settings
    store: DocumentStore
    token_verifier: "TokenVerifier"
    clock: Clock


def build_container(settings: Settings) -> Container:
    from app.firebase import FirebaseTokenVerifier, firestore_client, init_firebase
    from app.store.firestore import FirestoreStore

    if settings.firebase_service_account_json is None:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON não configurada.")
    firebase_app = init_firebase(settings.firebase_service_account_json.get_secret_value())
    return Container(
        settings=settings,
        store=FirestoreStore(firestore_client(firebase_app)),
        token_verifier=FirebaseTokenVerifier(firebase_app),
        clock=Clock(),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]
