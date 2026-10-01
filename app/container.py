from dataclasses import dataclass, field
from datetime import timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from app.catalog.catalog import CharacterCatalog
from app.clock import Clock
from app.config import Settings
from app.domain.match import MatchWeights
from app.jobs import JobRunner
from app.repositories import (
    CharacterRepository,
    DecisionRepository,
    DeckRepository,
    MatchRepository,
    UserRepository,
)
from app.services.decisions import DecisionService
from app.services.deck import DeckService
from app.store.base import DocumentStore

if TYPE_CHECKING:
    from app.auth import TokenVerifier
    from app.catalog.ingest import IngestService

HTTP_TIMEOUT_SECONDS = 30.0


@dataclass
class Container:
    """Dependências do processo, montadas uma vez e lidas pelas rotas."""

    settings: Settings
    store: DocumentStore
    token_verifier: "TokenVerifier"
    clock: Clock
    ingest: "IngestService | None" = None
    job_runner: JobRunner = field(default_factory=JobRunner)

    @cached_property
    def users(self) -> UserRepository:
        return UserRepository(self.store)

    @cached_property
    def decisions(self) -> DecisionRepository:
        return DecisionRepository(self.store)

    @cached_property
    def matches(self) -> MatchRepository:
        return MatchRepository(self.store)

    @cached_property
    def characters(self) -> CharacterRepository:
        return CharacterRepository(self.store)

    @cached_property
    def catalog(self) -> CharacterCatalog:
        ttl = timedelta(seconds=self.settings.catalog_cache_seconds)
        return CharacterCatalog(self.characters, self.clock, ttl)

    @cached_property
    def deck_service(self) -> DeckService:
        return DeckService(
            catalog=self.catalog,
            users=self.users,
            decisions=self.decisions,
            decks=DeckRepository(self.store),
            clock=self.clock,
            deck_size=self.settings.deck_size,
        )

    @cached_property
    def decision_service(self) -> DecisionService:
        settings = self.settings
        return DecisionService(
            catalog=self.catalog,
            users=self.users,
            decisions=self.decisions,
            matches=self.matches,
            deck=self.deck_service,
            clock=self.clock,
            weights=MatchWeights(
                compatibility=settings.match_weight_compatibility,
                affinity=settings.match_weight_affinity,
                chance=settings.match_weight_chance,
                cutoff=settings.match_cutoff,
            ),
        )


def build_container(settings: Settings) -> Container:
    from app.firebase import FirebaseTokenVerifier, firestore_client, init_firebase
    from app.store.firestore import FirestoreStore

    if settings.firebase_service_account_json is None:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON não configurada.")
    firebase_app = init_firebase(settings.firebase_service_account_json.get_secret_value())
    store = FirestoreStore(firestore_client(firebase_app))
    clock = Clock()
    return Container(
        settings=settings,
        store=store,
        token_verifier=FirebaseTokenVerifier(firebase_app),
        clock=clock,
        ingest=_build_ingest(settings, store, clock),
    )


def _build_ingest(settings: Settings, store: DocumentStore, clock: Clock):
    import httpx

    from app.catalog.comicvine import ComicVineClient
    from app.catalog.fandom import FandomClient
    from app.catalog.ingest import IngestService, IngestSettings
    from app.catalog.mapping import load_mappings
    from app.catalog.superhero_api import SuperheroApiClient
    from app.repositories import CharacterRepository

    if settings.comicvine_api_key is None:
        return None
    http = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)
    return IngestService(
        comicvine=ComicVineClient(
            http,
            settings.comicvine_api_key.get_secret_value(),
            max_requests_per_resource=settings.ingest_max_requests_per_resource,
            interval_seconds=settings.ingest_request_interval_seconds,
        ),
        fandom=FandomClient(
            http,
            max_chars=settings.personality_max_chars,
            interval_seconds=settings.ingest_request_interval_seconds,
        ),
        superhero=SuperheroApiClient(http),
        characters=CharacterRepository(store),
        store=store,
        mappings=load_mappings(),
        clock=clock,
        settings=IngestSettings(
            tier_b_min_appearances=settings.tier_b_min_appearances,
            refresh_days=settings.ingest_refresh_days,
            bio_max_chars=settings.bio_max_chars,
        ),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]
