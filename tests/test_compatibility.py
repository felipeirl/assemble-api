import pytest
from pydantic import ValidationError

from app.domain.compatibility import (
    RIVALRIES,
    are_rivals,
    breakdown,
    character_fame,
    score,
    traits_in_common,
)
from app.domain.enums import Category, Origin, PowerFamily, Style, Team
from app.domain.models import CharacterTraits, Preferences

MID_FAME_APPEARANCES = 1_000  # fama 0.5 na escala log


def character(**overrides) -> CharacterTraits:
    base = {
        "origin": Origin.Human,
        "powers": [PowerFamily.Strength],
        "teams": [Team.Avengers],
        "styles": [Style.Humor],
        "issueAppearances": MID_FAME_APPEARANCES,
    }
    return CharacterTraits(**{**base, **overrides})


def test_any_everywhere_is_neutral_not_a_full_match():
    # Metade de cada peso (12,5 + 15 + 7,5 + 10) + fama igual (10).
    assert score(Preferences(fame=0.5), character()) == 55


def test_rivals_everywhere_floor_at_zero():
    prefs = Preferences(
        origins=[Origin.Mutant],
        powers=[PowerFamily.Mind],
        teams=[Team.XMen],
        styles=[Style.Leadership],
        fame=0.5,
    )

    # Mutant x Human (-12,5), X-Men x Avengers (-7,5), Mind e Leadership sem rival (0), fama 10.
    assert score(prefs, character()) == 0


def test_chosen_category_with_empty_character_field_is_zero():
    prefs = Preferences(teams=[Team.XMen], fame=0.5)

    # 12,5 + 15 + 0 + 10 + 10 = 47,5
    assert score(prefs, character(teams=[])) == 48


def test_chosen_origin_with_unknown_character_origin_is_zero():
    prefs = Preferences(origins=[Origin.Mutant], fame=0.5)

    # 0 + 15 + 7,5 + 10 + 10 = 42,5
    assert score(prefs, character(origin=None)) == 43


def test_divisor_is_the_smaller_set():
    prefs = Preferences(
        powers=[PowerFamily.Mind, PowerFamily.TechGadgets, PowerFamily.Flight], fame=0.5
    )

    # 12,5 + 30 + 7,5 + 10 + 10
    assert score(prefs, character(powers=[PowerFamily.Flight])) == 70


def test_partial_overlap_uses_smaller_set_as_divisor():
    prefs = Preferences(powers=[PowerFamily.Mind, PowerFamily.Flight], fame=0.5)
    owned = [PowerFamily.Mind, PowerFamily.Energy, PowerFamily.Speed]

    # 30 × 1/min(2, 3) = 15
    assert score(prefs, character(powers=owned)) == 12.5 + 15 + 7.5 + 10 + 10


def test_rounds_half_up():
    prefs = Preferences(origins=[Origin.Human], powers=[PowerFamily.Strength])
    owned = character(issueAppearances=None)

    # 25 + 30 + 7,5 + 10 + 0 = 72,5 → 73 (round() do Python daria 72)
    assert score(prefs, owned) == 73


def test_unknown_appearances_gives_zero_fame_points():
    assert score(Preferences(fame=0.5), character(issueAppearances=None)) == 45


@pytest.mark.parametrize(
    ("appearances", "expected"),
    [(10_000, 0.0), (50_000, 0.0), (100, 1.0), (5, 1.0), (1_000, 0.5)],
)
def test_character_fame_log_scale(appearances, expected):
    assert character_fame(appearances) == pytest.approx(expected)


def test_fame_opposite_extremes_give_zero_fame_points():
    assert score(Preferences(fame=1.0), character(issueAppearances=10_000)) == 45


def test_breakdown_lists_common_traits_by_category_in_order():
    prefs = Preferences(
        origins=[Origin.Mutant, Origin.Human],
        powers=[PowerFamily.Mind],
        teams=[Team.XMen],
        styles=[Style.Leadership, Style.Idealist],
    )
    storm = CharacterTraits(
        origin=Origin.Mutant,
        powers=[PowerFamily.Energy, PowerFamily.Flight],
        teams=[Team.XMen],
        styles=[Style.Idealist, Style.Leadership],
        issueAppearances=4_000,
    )

    result = breakdown(prefs, storm)

    assert [(m.category, m.traits) for m in result] == [
        (Category.origin, ["Mutant"]),
        (Category.teams, ["XMen"]),
        (Category.style, ["Leadership", "Idealist"]),
    ]
    assert traits_in_common(prefs, storm) == ["Mutant", "XMen", "Leadership", "Idealist"]


def test_initial_mock_preferences_against_storm():
    prefs = Preferences(
        origins=[Origin.Mutant, Origin.Human],
        powers=[PowerFamily.Mind, PowerFamily.TechGadgets],
        teams=[Team.XMen],
        styles=[Style.Leadership],
        fame=0.5,
    )
    storm = CharacterTraits(
        origin=Origin.Mutant,
        powers=[PowerFamily.Energy, PowerFamily.Flight],
        teams=[Team.XMen],
        styles=[Style.Leadership, Style.Idealist],
        issueAppearances=4_000,
    )

    # 25 + 0 + 15 + 20 + 6.99 = 66.99 → 67
    assert score(prefs, storm) == 67


def test_unknown_enum_is_rejected():
    with pytest.raises(ValidationError):
        Preferences(origins=["Wizard"])


def test_fame_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        Preferences(fame=1.5)


def test_rival_trait_without_overlap_loses_half_the_weight():
    prefs = Preferences(teams=[Team.XMen], fame=0.5)
    # 12,5 + 15 - 7,5 + 10 + 10 = 40
    assert score(prefs, character(teams=[Team.Avengers])) == 40
    # Sem rival (Guardians), a categoria só não pontua: 47,5
    assert score(prefs, character(teams=[Team.Guardians])) == 48


def test_shared_trait_cancels_the_rivalry():
    prefs = Preferences(teams=[Team.XMen], fame=0.5)
    # X-Men em comum: 15 × 1/1, sem penalidade pelos Avengers. 62,5
    assert score(prefs, character(teams=[Team.Avengers, Team.XMen])) == 63


def test_rivalries_are_symmetric_and_curated():
    assert are_rivals(Origin.Human, Origin.Mutant)
    assert are_rivals(Origin.Mutant, Origin.Human)
    assert are_rivals(Origin.Robot, Origin.Mutant)
    assert not are_rivals(Origin.Mutant, Origin.Alien)
    assert not are_rivals(Team.FantasticFour, Team.Avengers)
    assert not any(isinstance(item, PowerFamily) for pair in RIVALRIES for item in pair)
