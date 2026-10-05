"""Objetos do contrato da API V2 (campos em camelCase, ausentes não são enviados)."""

from datetime import datetime
from typing import Annotated

from fastapi import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import Author, Category, Choice

# IDs viram parte de caminhos do Firestore: só letras, números, "-" e "_" (sem "/").
ID_PATTERN = r"^[A-Za-z0-9_-]{1,200}$"
MESSAGE_MAX_LENGTH = 1000


CharacterIdPath = Annotated[str, Path(pattern=ID_PATTERN)]


class DeckCard(BaseModel):
    characterId: str
    name: str
    imageUrl: str | None = None
    tagline: str | None = None
    traitsInCommon: list[str]


class Deck(BaseModel):
    date: str
    cards: list[DeckCard]
    remaining: int
    total: int
    nextDeckAt: datetime
    canUndo: bool


class MatchCharacter(BaseModel):
    characterId: str
    name: str
    imageUrl: str | None = None


class MatchResult(BaseModel):
    matched: bool
    connectionId: str | None = None
    character: MatchCharacter | None = None
    score: int | None = None
    reasons: list[str] | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    characterId: str = Field(pattern=ID_PATTERN)
    choice: Choice


class Message(BaseModel):
    id: str
    connectionId: str
    author: Author
    text: str
    createdAt: datetime
    fictional: bool
    blocked: bool


class CharacterReply(BaseModel):
    userMessage: Message
    reply: Message
    suggestions: list[str]


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=MESSAGE_MAX_LENGTH)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("texto vazio")
        return stripped


class WhyYouMatch(BaseModel):
    category: Category
    traits: list[str]


class Powerstats(BaseModel):
    intelligence: int
    strength: int
    speed: int
    durability: int
    power: int
    combat: int


class Appearance(BaseModel):
    gender: str | None = None
    race: str | None = None
    heightCm: int | None = None
    weightKg: int | None = None
    eyeColor: str | None = None
    hairColor: str | None = None


class CharacterFacts(BaseModel):
    realName: str | None = None
    aliases: list[str] | None = None
    origin: str | None = None
    powers: list[str] | None = None
    teams: list[str] | None = None
    alignment: str | None = None
    placeOfBirth: str | None = None
    occupation: str | None = None
    base: str | None = None
    firstAppearance: str | None = None
    issueAppearances: int | None = None
    bio: str | None = None
    relatives: str | None = None
    powerstats: Powerstats | None = None
    appearance: Appearance | None = None


class SourceCredit(BaseModel):
    name: str
    url: str | None = None


class Teammate(BaseModel):
    characterId: str
    name: str
    imageUrl: str | None = None
    connected: bool


class CompareWith(BaseModel):
    characterId: str
    name: str
    powerstats: Powerstats


class CharacterView(BaseModel):
    """CharacterPreview (sem conexão) ou CharacterProfile (com conexão)."""

    characterId: str
    name: str
    imageUrl: str | None = None
    connected: bool
    traitsInCommon: list[str] | None = None
    connectionId: str | None = None
    score: int | None = None
    whyYouMatch: list[WhyYouMatch] | None = None
    facts: CharacterFacts | None = None
    factSources: dict[str, str] | None = None
    translatedFields: list[str] | None = None
    sources: list[SourceCredit] | None = None
    teammates: list[Teammate] | None = None
    compareWith: list[CompareWith] | None = None


class UserStats(BaseModel):
    connections: int
    messagesSent: int
    charactersSeen: int
    distinctTeams: int


class DeactivationResult(BaseModel):
    purgeAt: datetime
