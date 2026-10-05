"""Compatibilidade usuário × personagem. Função pura, idêntica à do app Android."""

import math
from dataclasses import dataclass
from enum import StrEnum

from app.domain.enums import Category, Origin, PowerFamily, Style, Team
from app.domain.models import CharacterTraits, Preferences

WEIGHT_ORIGIN = 25
WEIGHT_POWERS = 30
WEIGHT_TEAMS = 15
WEIGHT_STYLE = 20
WEIGHT_FAME = 10

FAME_ICON_APPEARANCES = 10_000
FAME_HIDDEN_GEM_APPEARANCES = 100

# "Qualquer" é neutro: metade do peso, para não combinar com todo mundo.
ANY_FACTOR = 0.5
# Sem nada em comum e com um traço rival do que o usuário escolheu: perde metade do peso.
RIVAL_PENALTY = 0.5
SCORE_MIN = 0
SCORE_MAX = 100

# Tolerância de ponto flutuante para o arredondamento "meio para cima".
ROUNDING_EPSILON = 1e-9

# Rivalidades (simétricas). Equipes e origens só com conflito documentado nas HQs:
# - Avengers x X-Men: "Avengers vs. X-Men" (2012).
# - Avengers x Defenders: "The Avengers/Defenders War" (1973).
# - X-Men x S.H.I.E.L.D.: a S.H.I.E.L.D. caça os X-Men de Ciclope (Uncanny X-Men, 2013).
# - Mutante x Humano: o preconceito anti-mutante, tema central dos X-Men.
# - Mutante x Robô: os Sentinelas, robôs feitos para caçar mutantes.
# Estilos: opostos diretos de atitude. Poderes não têm rivalidade.
RIVALRIES: tuple[tuple[StrEnum, StrEnum], ...] = (
    (Team.Avengers, Team.XMen),
    (Team.Avengers, Team.Defenders),
    (Team.XMen, Team.Shield),
    (Origin.Mutant, Origin.Human),
    (Origin.Mutant, Origin.Robot),
    (Style.Leadership, Style.Loner),
    (Style.Leadership, Style.Rebel),
    (Style.Idealist, Style.Dark),
)
_RIVALS = {pair for a, b in RIVALRIES for pair in ((a, b), (b, a))}


@dataclass(frozen=True)
class CategoryMatch:
    category: Category
    traits: list[str]


def character_fame(issue_appearances: int | None) -> float | None:
    """Fama em escala log: 10.000+ aparições = 0 (Icons), ≤100 = 1 (Hidden gems)."""
    if issue_appearances is None:
        return None
    clamped = min(max(issue_appearances, FAME_HIDDEN_GEM_APPEARANCES), FAME_ICON_APPEARANCES)
    low = math.log10(FAME_HIDDEN_GEM_APPEARANCES)
    high = math.log10(FAME_ICON_APPEARANCES)
    return (high - math.log10(clamped)) / (high - low)


def score(prefs: Preferences, character: CharacterTraits) -> int:
    total = sum(
        _set_points(weight, chosen, owned)
        for weight, chosen, owned, _ in _categories(prefs, character)
    )
    total += _fame_points(prefs.fame, character.issueAppearances)
    return min(max(_round_half_up(total), SCORE_MIN), SCORE_MAX)


def breakdown(prefs: Preferences, character: CharacterTraits) -> list[CategoryMatch]:
    """Itens em comum por categoria, só das categorias com algum item em comum."""
    matches = []
    for _, chosen, owned, (category, enum_type) in _categories(prefs, character):
        common = [item.value for item in enum_type if item in chosen and item in owned]
        if common:
            matches.append(CategoryMatch(category=category, traits=common))
    return matches


def traits_in_common(prefs: Preferences, character: CharacterTraits) -> list[str]:
    """Traços em comum na ordem Origin → Powers → Teams → Style."""
    return [trait for match in breakdown(prefs, character) for trait in match.traits]


def _categories(prefs: Preferences, character: CharacterTraits):
    character_origin = {character.origin} if character.origin is not None else set()
    return [
        (WEIGHT_ORIGIN, set(prefs.origins), character_origin, (Category.origin, Origin)),
        (WEIGHT_POWERS, set(prefs.powers), set(character.powers), (Category.powers, PowerFamily)),
        (WEIGHT_TEAMS, set(prefs.teams), set(character.teams), (Category.teams, Team)),
        (WEIGHT_STYLE, set(prefs.styles), set(character.styles), (Category.style, Style)),
    ]


def are_rivals(a: StrEnum, b: StrEnum) -> bool:
    return (a, b) in _RIVALS


def _set_points(weight: int, chosen: set[StrEnum], owned: set[StrEnum]) -> float:
    if not chosen:
        return weight * ANY_FACTOR
    if not owned:
        return 0.0
    common = len(chosen & owned)
    if common == 0:
        rival = any(are_rivals(mine, theirs) for mine in chosen for theirs in owned)
        return -weight * RIVAL_PENALTY if rival else 0.0
    return weight * common / min(len(chosen), len(owned))


def _fame_points(fame_preference: float, issue_appearances: int | None) -> float:
    fame = character_fame(issue_appearances)
    if fame is None:
        return 0.0
    return WEIGHT_FAME * (1 - abs(fame_preference - fame))


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5 + ROUNDING_EPSILON)
