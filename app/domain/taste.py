"""Gosto aprendido pelas decisões: Assemble conta a favor das características, Pass contra.

Funções puras. O gosto não é gravado: é recalculado das decisões a cada baralho, então o Undo
e as decisões apagadas já se refletem sozinhos, e as preferências declaradas ficam intactas.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.compatibility import character_fame
from app.domain.models import CharacterTraits

# Suaviza poucas decisões: com 1 Assemble, o peso de uma característica é 1/(1+3), não 1.
SMOOTHING = 3.0
# Depois de tantas decisões o gosto aprendido vale por inteiro; antes, vale proporcionalmente.
CONFIDENT_AFTER_DECISIONS = 20
FAME_ICON_BELOW = 1 / 3
FAME_GEM_FROM = 2 / 3
NEUTRAL = 0.5


@dataclass(frozen=True)
class Taste:
    """Peso de cada característica, de -1 (sempre recusa) a +1 (sempre curte)."""

    weights: dict[str, float]
    decisions: int

    @property
    def confidence(self) -> float:
        return min(1.0, self.decisions / CONFIDENT_AFTER_DECISIONS)


def trait_keys(traits: CharacterTraits) -> list[str]:
    keys: list[str] = []
    if traits.origin is not None:
        keys.append(f"origin:{traits.origin.value}")
    keys += [f"power:{power.value}" for power in traits.powers]
    keys += [f"team:{team.value}" for team in traits.teams]
    keys += [f"style:{style.value}" for style in traits.styles]
    fame = character_fame(traits.issueAppearances)
    if fame is not None:
        keys.append(
            "fame:icon"
            if fame < FAME_ICON_BELOW
            else "fame:gem"
            if fame >= FAME_GEM_FROM
            else "fame:mid"
        )
    return keys


def learn(history: Iterable[tuple[CharacterTraits, bool]]) -> Taste:
    """`history`: cada decisão como (características do personagem, curtiu?)."""
    seen: Counter[str] = Counter()
    liked: Counter[str] = Counter()
    decisions = 0
    for traits, was_liked in history:
        decisions += 1
        for key in trait_keys(traits):
            seen[key] += 1
            if was_liked:
                liked[key] += 1
    weights = {key: (2 * liked[key] - count) / (count + SMOOTHING) for key, count in seen.items()}
    return Taste(weights=weights, decisions=decisions)


def affinity(taste: Taste, traits: CharacterTraits) -> float:
    """Quanto o gosto aprendido favorece o personagem, de 0 a 1 (0,5 = neutro)."""
    keys = trait_keys(traits)
    if not keys or not taste.weights:
        return NEUTRAL
    mean = sum(taste.weights.get(key, 0.0) for key in keys) / len(keys)
    return (mean + 1) / 2
