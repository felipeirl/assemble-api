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

# Tolerância de ponto flutuante para o arredondamento "meio para cima".
ROUNDING_EPSILON = 1e-9


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
    return _round_half_up(total)


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


def _set_points(weight: int, chosen: set[StrEnum], owned: set[StrEnum]) -> float:
    if not chosen:
        return float(weight)
    if not owned:
        return 0.0
    common = len(chosen & owned)
    return weight * common / min(len(chosen), len(owned))


def _fame_points(fame_preference: float, issue_appearances: int | None) -> float:
    fame = character_fame(issue_appearances)
    if fame is None:
        return 0.0
    return WEIGHT_FAME * (1 - abs(fame_preference - fame))


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5 + ROUNDING_EPSILON)
