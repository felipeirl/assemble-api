"""Objetos do contrato da API V2 (campos em camelCase, ausentes não são enviados)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Choice

CHARACTER_ID_MAX_LENGTH = 200


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
