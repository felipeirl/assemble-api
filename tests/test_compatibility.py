import pytest
from pydantic import ValidationError

from app.domain.compatibility import breakdown, character_fame, score, traits_in_common
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


def test_any_everywhere_with_equal_fame_is_100():
    assert score(Preferences(fame=0.5), character()) == 100


def test_nothing_in_common_scores_only_fame():
    prefs = Preferences(
        origins=[Origin.Mutant],
        powers=[PowerFamily.Mind],
        teams=[Team.XMen],
        styles=[Style.Leadership],
        fame=0.5,
    )

    assert score(prefs, character()) == 10


def test_chosen_category_with_empty_character_field_is_zero():
    prefs = Preferences(teams=[Team.XMen], fame=0.5)

    assert score(prefs, character(teams=[])) == 25 + 30 + 20 + 10


def test_chosen_origin_with_unknown_character_origin_is_zero():
    prefs = Preferences(origins=[Origin.Mutant], fame=0.5)

    assert score(prefs, character(origin=None)) == 30 + 15 + 20 + 10


def test_divisor_is_the_smaller_set():
    prefs = Preferences(
        powers=[PowerFamily.Mind, PowerFamily.TechGadgets, PowerFamily.Flight], fame=0.5
    )

    assert score(prefs, character(powers=[PowerFamily.Flight])) == 100


def test_partial_overlap_uses_smaller_set_as_divisor():
    prefs = Preferences(powers=[PowerFamily.Mind, PowerFamily.Flight], fame=0.5)
    owned = [PowerFamily.Mind, PowerFamily.Energy, PowerFamily.Speed]

    # 30 × 1/min(2, 3) = 15
    assert score(prefs, character(powers=owned)) == 25 + 15 + 15 + 20 + 10


def test_rounds_half_up():
    prefs = Preferences(teams=[Team.Avengers, Team.XMen])
    owned = character(teams=[Team.Avengers, Team.Guardians], issueAppearances=None)

    # 25 + 30 + 15 × 1/2 + 20 + 0 = 82.5 → 83 (round() do Python daria 82)
    assert score(prefs, owned) == 83


def test_unknown_appearances_gives_zero_fame_points():
    assert score(Preferences(fame=0.5), character(issueAppearances=None)) == 90


@pytest.mark.parametrize(
    ("appearances", "expected"),
    [(10_000, 0.0), (50_000, 0.0), (100, 1.0), (5, 1.0), (1_000, 0.5)],
)
def test_character_fame_log_scale(appearances, expected):
    assert character_fame(appearances) == pytest.approx(expected)


def test_fame_opposite_extremes_give_zero_fame_points():
    assert score(Preferences(fame=1.0), character(issueAppearances=10_000)) == 90


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
