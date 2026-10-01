"""Decisão de match (seção 7): compatibilidade + afinidade da persona + acaso."""

import hashlib
import random
from dataclasses import dataclass

DECISION_VERSION = "match-v1"
DECISION_VERSION_DEGRADED = "match-v1-degraded"


@dataclass(frozen=True)
class MatchWeights:
    compatibility: float
    affinity: float
    chance: float
    cutoff: float


@dataclass(frozen=True)
class MatchDecision:
    matched: bool
    chance: float
    version: str


def seeded_chance(uid: str, character_id: str) -> float:
    """Acaso determinístico por par (uid, characterId), em [0, 1)."""
    digest = hashlib.sha256(f"{uid}:{character_id}".encode()).digest()
    return random.Random(digest).random()


def decide_match(
    score: int, affinity: float | None, luck: float, weights: MatchWeights
) -> MatchDecision:
    """Sem afinidade (Laya indisponível), usa só compatibilidade + acaso, no modo degradado."""
    chance = weights.compatibility * (score / 100) + weights.chance * luck
    if affinity is None:
        version = DECISION_VERSION_DEGRADED
    else:
        chance += weights.affinity * affinity
        version = DECISION_VERSION
    return MatchDecision(matched=chance >= weights.cutoff, chance=round(chance, 4), version=version)
