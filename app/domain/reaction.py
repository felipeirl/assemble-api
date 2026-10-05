"""Rodada de reação do cadastro: poucos personagens conhecidos e diferentes entre si.

Cada Curti/Pular ensina o gosto aprendido; por isso os cards cobrem o máximo de origens,
equipes, estilos e alinhamentos distintos, em vez de repetir o mesmo perfil.
"""

import random

from app.domain import taste
from app.domain.models import CharacterTraits

REACTION_CARDS = 12
# Só os mais conhecidos entram: reagir a quem a pessoa não reconhece ensina pouco.
REACTION_POOL = 36
COVERED_PREFIXES = ("origin:", "team:", "style:", "alignment:")


def covered_keys(traits: CharacterTraits) -> set[str]:
    return {key for key in taste.trait_keys(traits) if key.startswith(COVERED_PREFIXES)}


def select_reaction_cards(
    candidates: dict[str, CharacterTraits], size: int, rng: random.Random
) -> list[str]:
    """A cada passo, o personagem que traz mais características ainda não vistas."""
    famous = sorted(
        candidates, key=lambda cid: candidates[cid].issueAppearances or 0, reverse=True
    )[:REACTION_POOL]
    rng.shuffle(famous)
    seen: set[str] = set()
    chosen: list[str] = []
    while famous and len(chosen) < size:
        best = max(famous, key=lambda cid: len(covered_keys(candidates[cid]) - seen))
        famous.remove(best)
        chosen.append(best)
        seen |= covered_keys(candidates[best])
    return chosen
