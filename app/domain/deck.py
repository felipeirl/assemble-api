"""Seleção do baralho diário: compatibilidade + variedade + novidade. Funções puras."""

import random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ALGORITHM_VERSION = "deck-v1"
NOVELTY_WINDOW = timedelta(days=14)
NOVELTY_BONUS = 0.15
VARIETY_PENALTY = 0.1
JITTER = 0.1


@dataclass(frozen=True)
class Candidate:
    character_id: str
    score: int
    origin: str | None
    teams: tuple[str, ...]
    is_new: bool


def select_deck(candidates: list[Candidate], size: int, rng: random.Random) -> list[str]:
    """Escolhe até `size` personagens, penalizando origens e equipes já escolhidas."""
    jitter = {c.character_id: rng.random() * JITTER for c in candidates}
    origin_counts: Counter[str] = Counter()
    team_counts: Counter[str] = Counter()
    pool = list(candidates)
    selected: list[str] = []

    def value(candidate: Candidate) -> tuple[float, str]:
        repeats = sum(team_counts[team] for team in candidate.teams)
        if candidate.origin is not None:
            repeats += origin_counts[candidate.origin]
        total = (
            candidate.score / 100
            + (NOVELTY_BONUS if candidate.is_new else 0.0)
            - VARIETY_PENALTY * repeats
            + jitter[candidate.character_id]
        )
        return total, candidate.character_id

    while pool and len(selected) < size:
        best = max(pool, key=value)
        pool.remove(best)
        selected.append(best.character_id)
        if best.origin is not None:
            origin_counts[best.origin] += 1
        team_counts.update(best.teams)
    return selected


def local_date(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


def next_deck_at(now: datetime, tz: ZoneInfo) -> datetime:
    """Meia-noite do próximo dia no fuso do usuário, em UTC."""
    tomorrow = local_date(now, tz) + timedelta(days=1)
    return datetime.combine(tomorrow, time(0), tzinfo=tz).astimezone(UTC)


def is_new(ingested_at: datetime | None, now: datetime) -> bool:
    return ingested_at is not None and now - ingested_at <= NOVELTY_WINDOW
