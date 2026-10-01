"""Objetos do contrato da API V2 (campos em camelCase, ausentes não são enviados)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import Author, Category, Choice

CHARACTER_ID_MAX_LENGTH = 200
MESSAGE_MAX_LENGTH = 1000


class DeckCard(BaseModel):
    characterId: str
    name: str
    imageUrl: str | None = None
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

    characterId: str = Field(min_length=1, max_length=CHARACTER_ID_MAX_LENGTH)
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


class CharacterFacts(BaseModel):
    realName: str | None = None
    origin: str | None = None
    powers: list[str] | None = None
    teams: list[str] | None = None
    firstAppearance: str | None = None
    bio: str | None = None


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
    source: str | None = None
    sourceUrl: str | None = None


class UserStats(BaseModel):
    connections: int
    messagesSent: int
    charactersSeen: int
    distinctTeams: int


class DeactivationResult(BaseModel):
    purgeAt: datetime
