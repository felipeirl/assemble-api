from dataclasses import dataclass, field
from datetime import timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from app.ai.chat import ChatEngine
from app.ai.memory import MemorySummarizer
from app.ai.personas import PersonaService
from app.ai.translations import TranslationService
from app.catalog.catalog import CharacterCatalog
from app.clock import Clock
from app.config import Settings
from app.domain.match import MatchWeights
from app.jobs import JobRunner
from app.rate_limit import SlidingWindowLimiter
from app.repositories import (
    AccessLogRepository,
    CharacterRepository,
    DecisionRepository,
    DeckRepository,
    MatchRepository,
    MessageRepository,
    PersonaRepository,
    TasteSignalRepository,
    UserRepository,
)
from app.services.account import AccountService
from app.services.conversation import ConversationService
from app.services.decisions import DecisionService
from app.services.deck import DeckService
from app.services.onboarding import OnboardingService
from app.services.profiles import ProfileService
from app.store.base import DocumentStore

if TYPE_CHECKING:
    from app.ai.guardrail import Guardrail
    from app.ai.llm import LlmClient
    from app.auth import TokenVerifier
    from app.catalog.ingest import IngestService

HTTP_TIMEOUT_SECONDS = 30.0
MESSAGE_LIMIT_WINDOW = timedelta(hours=1)


@dataclass
class Container:
    """Dependências do processo, montadas uma vez e lidas pelas rotas."""

    settings: Settings
    store: DocumentStore
    token_verifier: "TokenVerifier"
    clock: Clock
    ingest: "IngestService | None" = None
    llm: "LlmClient | None" = None
    guardrail: "Guardrail | None" = None
    job_runner: JobRunner = field(default_factory=JobRunner)

    @cached_property
    def chat_engine(self) -> ChatEngine | None:
        models = [m for m in (self.settings.chat_model, self.settings.chat_fallback_model) if m]
        if self.llm is None or self.guardrail is None or not models:
            return None
        return ChatEngine(
            self.llm, self.guardrail, models, reasoning_efforts=self.settings.chat_reasoning_efforts
        )

    @cached_property
    def memory_summarizer(self) -> MemorySummarizer | None:
        model = self.settings.memory_model
        if self.llm is None or self.guardrail is None or not model:
            return None
        return MemorySummarizer(
            self.llm, self.guardrail, model, self.settings.chat_reasoning_efforts
        )

    @cached_property
    def conversation_service(self) -> ConversationService:
        return ConversationService(
            chat=self.chat_engine,
            personas=self.personas,
            characters=self.characters,
            matches=self.matches,
            messages=MessageRepository(self.store),
            users=self.users,
            limiter=SlidingWindowLimiter(
                self.settings.messages_per_hour, MESSAGE_LIMIT_WINDOW, self.clock
            ),
            clock=self.clock,
            history_limit=self.settings.chat_history_limit,
            memory=self.memory_summarizer,
            memory_batch=self.settings.memory_batch_size,
            memory_chunk=self.settings.memory_chunk_size,
        )

    @cached_property
    def account_service(self) -> AccountService:
        return AccountService(
            users=self.users,
            matches=self.matches,
            messages=MessageRepository(self.store),
            access_logs=AccessLogRepository(self.store),
            auth_admin=self.token_verifier,
            clock=self.clock,
        )

    @cached_property
    def profile_service(self) -> ProfileService:
        return ProfileService(
            catalog=self.catalog,
            characters=self.characters,
            users=self.users,
            decisions=self.decisions,
            matches=self.matches,
        )

    @cached_property
    def personas(self) -> PersonaRepository:
        return PersonaRepository(self.store)

    @cached_property
    def translation_service(self) -> TranslationService | None:
        if self.llm is None or not self.settings.persona_model:
            return None
        return TranslationService(
            llm=self.llm,
            model=self.settings.persona_model,
            characters=self.characters,
            catalog=self.catalog,
            clock=self.clock,
            batch_size=self.settings.translation_batch_size,
            timeout_seconds=self.settings.batch_llm_timeout_seconds,
            concurrency=self.settings.translation_concurrency,
        )

    @cached_property
    def persona_service(self) -> PersonaService | None:
        if self.llm is None or not self.settings.persona_model:
            return None
        return PersonaService(
            llm=self.llm,
            model=self.settings.persona_model,
            characters=self.characters,
            personas=self.personas,
            catalog=self.catalog,
            clock=self.clock,
            batch_size=self.settings.persona_batch_size,
            timeout_seconds=self.settings.batch_llm_timeout_seconds,
        )

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
    def taste_signals(self) -> TasteSignalRepository:
        return TasteSignalRepository(self.store)

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
            signals=self.taste_signals,
            clock=self.clock,
            deck_size=self.settings.deck_size,
        )

    @cached_property
    def onboarding_service(self) -> OnboardingService:
        return OnboardingService(
            catalog=self.catalog,
            users=self.users,
            decisions=self.decisions,
            signals=self.taste_signals,
            clock=self.clock,
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
            conversation=self.conversation_service,
            personas=self.personas,
            guardrail=self.guardrail,
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
        llm=_build_llm(settings),
        guardrail=_build_guardrail(settings),
    )


def _build_guardrail(settings: Settings):
    from app.ai.guardrail import LayaGuardrail

    if not settings.guardrail_enabled:
        return None
    return LayaGuardrail(threshold=settings.guardrail_threshold)


def _build_llm(settings: Settings):
    from app.ai.llm import LiteLlmClient

    if settings.commandcode_api_key is None or not settings.commandcode_base_url:
        return None
    return LiteLlmClient(
        api_key=settings.commandcode_api_key.get_secret_value(),
        base_url=settings.commandcode_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _build_ingest(settings: Settings, store: DocumentStore, clock: Clock):
    import httpx

    from app.catalog.comicvine import ComicVineClient
    from app.catalog.fandom import FandomClient
    from app.catalog.ingest import IngestService, IngestSettings
    from app.catalog.mapping import load_mappings
    from app.catalog.superhero_api import SuperheroApiClient, SuperheroMatcher
    from app.catalog.wikidata import WikidataBridge
    from app.repositories import CharacterRepository

    if settings.comicvine_api_key is None:
        return None
    http = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)
    mappings = load_mappings()
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
        superhero=SuperheroMatcher(
            SuperheroApiClient(http),
            mappings,
            WikidataBridge(http, settings.ingest_request_interval_seconds),
        ),
        characters=CharacterRepository(store),
        store=store,
        mappings=mappings,
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
