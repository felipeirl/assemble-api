import random
import statistics

import pytest

from app.domain import taste
from app.domain.deck import Candidate, select_mixed_deck
from app.domain.enums import Origin, PowerFamily, Style, Team
from app.domain.models import CharacterTraits


def traits(
    origin=Origin.Human, teams=(Team.Avengers,), powers=(PowerFamily.Strength,), appearances=1_000
):
    return CharacterTraits(
        origin=origin,
        powers=list(powers),
        teams=list(teams),
        styles=[Style.Humor],
        issueAppearances=appearances,
    )


MUTANT = traits(origin=Origin.Mutant, teams=(Team.XMen,), powers=(PowerFamily.Mind,))
HUMAN = traits()


def test_no_decisions_means_a_neutral_taste_with_no_confidence():
    empty = taste.learn([])

    assert empty.confidence == 0
    assert taste.affinity(empty, MUTANT) == taste.NEUTRAL


def test_liking_mutants_raises_affinity_for_mutants_and_lowers_it_for_humans():
    history = [(MUTANT, True)] * 8 + [(HUMAN, False)] * 8

    learned = taste.learn(history)

    assert taste.affinity(learned, MUTANT) > 0.6
    assert taste.affinity(learned, HUMAN) < 0.4


def test_few_decisions_barely_move_the_taste():
    one_like = taste.learn([(MUTANT, True)])

    assert taste.NEUTRAL < taste.affinity(one_like, MUTANT) < 0.7
    assert one_like.confidence == pytest.approx(1 / taste.CONFIDENT_AFTER_DECISIONS)


def test_confidence_saturates_after_enough_decisions():
    assert taste.learn([(MUTANT, True)] * 40).confidence == 1.0


def test_trait_keys_cover_origin_powers_teams_styles_and_fame():
    keys = taste.trait_keys(traits(appearances=10_000))

    assert {"origin:Human", "power:Strength", "team:Avengers", "style:Humor", "fame:icon"} <= set(
        keys
    )
    assert "fame:gem" in taste.trait_keys(traits(appearances=100))
    assert not any(key.startswith("fame:") for key in taste.trait_keys(traits(appearances=None)))


def pool(size=60):
    """Metade mutantes (origens/equipes distintas das dos humanos), notas declaradas iguais."""
    candidates, found = [], {}
    for i in range(size):
        mutant = i % 2 == 0
        candidates.append(
            Candidate(
                f"c{i}",
                50,
                "Mutant" if mutant else "Human",
                ("XMen",) if mutant else ("Avengers",),
                False,
            )
        )
        found[f"c{i}"] = MUTANT if mutant else HUMAN
    return candidates, found


def learned_for(found, decisions):
    history = [(found[cid], liked) for cid, liked in decisions]
    learned = taste.learn(history)
    return {cid: taste.affinity(learned, t) for cid, t in found.items()}, learned.confidence


def test_deck_has_half_declared_and_half_suggestions_and_no_repeats():
    candidates, found = pool()
    learned, confidence = learned_for(found, [])

    chosen = select_mixed_deck(candidates, 40, random.Random(1), learned, confidence)

    assert len(chosen) == 40
    assert len(set(chosen)) == 40


def test_the_declared_half_is_the_most_compatible():
    candidates = [Candidate(f"hi{i}", 95, f"O{i}", (), False) for i in range(10)] + [
        Candidate(f"lo{i}", 30, f"P{i}", (), False) for i in range(30)
    ]

    for seed in range(20):
        chosen = select_mixed_deck(candidates, 20, random.Random(seed), {}, 0.0)
        assert {f"hi{i}" for i in range(10)} <= set(chosen[:10])


def test_suggestions_follow_what_the_user_liked_once_there_are_enough_decisions():
    candidates, found = pool()
    liked_mutants = [(f"c{i}", True) for i in range(0, 20, 2)]
    passed_humans = [(f"c{i}", False) for i in range(1, 21, 2)]
    learned, confidence = learned_for(found, liked_mutants + passed_humans)
    fresh = [c for c in candidates if int(c.character_id[1:]) >= 20]

    shares = []
    for seed in range(30):
        chosen = select_mixed_deck(fresh, 20, random.Random(seed), learned, confidence)
        suggestions = chosen[10:]
        shares.append(sum(found[cid] is MUTANT for cid in suggestions) / len(suggestions))

    assert confidence == 1.0
    assert statistics.mean(shares) > 0.8


def test_without_decisions_suggestions_explore_instead_of_following_a_taste():
    candidates, found = pool()
    learned, confidence = learned_for(found, [])

    shares = []
    for seed in range(30):
        chosen = select_mixed_deck(candidates, 20, random.Random(seed), learned, confidence)
        suggestions = chosen[10:]
        shares.append(sum(found[cid] is MUTANT for cid in suggestions) / len(suggestions))

    assert 0.3 < statistics.mean(shares) < 0.7
