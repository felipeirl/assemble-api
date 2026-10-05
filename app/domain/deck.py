"""Sorteio do baralho: compatibilidade + variedade + novidade + muita sorte. Funções puras."""

import random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ALGORITHM_VERSION = "deck-v2"
NOVELTY_WINDOW = timedelta(days=14)
NOVELTY_BONUS = 0.45  # na escala da nota já multiplicada por SCORE_WEIGHT (0,15 × 3)
# Penalidade pela fração do baralho já ocupada pela mesma origem e equipes (cresce de 0 a ~2 vezes
# este valor). Somada por repetição, ela passava de 2,0 no meio da seleção e fazia os personagens
# de origem rara entrarem sempre: o baralho saía quase igual para todo mundo.
VARIETY_PENALTY = 0.4
# Peso da nota de compatibilidade (0 a 1) frente à variedade e à sorte. Com 1, a variedade engolia a
# nota: entravam 15 dos 25 mais compatíveis e a nota média do baralho era quase a do conjunto todo.
# Com 3, entram cerca de 20 dos 25 melhores e os baralhos seguem diferentes.
SCORE_WEIGHT = 3.0
# Sorte do sorteio, na mesma escala da nota (0 a 1). Com 0,1 duas contas de gosto parecido recebiam
# quase os mesmos personagens; com 0,6, quem combina mais ainda tende a entrar, e o resto
# varia de pessoa para pessoa e de abertura para abertura.
JITTER = 0.6


@dataclass(frozen=True)
class Candidate:
    character_id: str
    score: int
    origin: str | None
    teams: tuple[str, ...]
    is_new: bool


def select_deck(
    candidates: list[Candidate], size: int, rng: random.Random, luck: float = JITTER
) -> list[str]:
    """Escolhe até `size` personagens, penalizando origens e equipes já escolhidas.

    `luck` é a sorte somada à nota de cada personagem (0 a `luck`).
    """
    jitter = {c.character_id: rng.random() * luck for c in candidates}
    origin_counts: Counter[str] = Counter()
    team_counts: Counter[str] = Counter()
    pool = list(candidates)
    selected: list[str] = []

    def value(candidate: Candidate) -> tuple[float, str]:
        repeats = sum(team_counts[team] for team in candidate.teams)
        if candidate.origin is not None:
            repeats += origin_counts[candidate.origin]
        repeat_share = repeats / max(1, len(selected))
        total = (
            candidate.score / 100 * SCORE_WEIGHT
            + (NOVELTY_BONUS if candidate.is_new else 0.0)
            - VARIETY_PENALTY * repeat_share
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
