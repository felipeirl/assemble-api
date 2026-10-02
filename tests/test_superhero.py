import httpx

from app.catalog.mapping import load_mappings
from app.catalog.superhero_api import (
    MATCH_AUTO,
    MATCH_MANUAL,
    SuperheroApiClient,
    SuperheroMatcher,
    clean_aliases,
    clean_appearance,
    clean_entry,
    clean_powerstats,
    group_affiliations,
)
from tests.superhero_samples import JEAN_GREY_356, ROCKET_566, STORM_638

IRON_MAN_346 = {
    "id": 346,
    "name": "Iron Man",
    "biography": {"fullName": "Tony Stark", "publisher": "Marvel Comics"},
}
IRON_FIST_345 = {
    "id": 345,
    "name": "Iron Fist",
    "biography": {"fullName": "Danny Rand", "publisher": "Marvel Comics"},
}
FORGE = {
    "id": 900,
    "name": "Forge",
    "biography": {"fullName": "Jonathan Silvercloud", "publisher": "Marvel Comics"},
}
FORGE_DC = {
    "id": 901,
    "name": "Forge",
    "biography": {"fullName": "Jonathan Silvercloud", "publisher": "DC Comics"},
}
ANGEL_A = {
    "id": 30,
    "name": "Angel",
    "biography": {"fullName": "Warren Worthington III", "publisher": "Marvel Comics"},
}
ANGEL_B = {
    "id": 31,
    "name": "Angel",
    "biography": {"fullName": "Warren Worthington III", "publisher": "Marvel Comics"},
}


def matcher(entries):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=entries)))
    return SuperheroMatcher(SuperheroApiClient(http), load_mappings())


ALL = [STORM_638, JEAN_GREY_356, ROCKET_566, IRON_MAN_346, IRON_FIST_345, FORGE, FORGE_DC]


def test_manual_table_wins_even_with_unexpected_publisher():
    result = matcher(ALL).match("jean-grey", "Jean Grey", None)

    assert result.entry["id"] == 356
    assert result.method == MATCH_MANUAL


def test_manual_table_does_not_confuse_neighbour_ids():
    assert matcher(ALL).match("iron-man", "Iron Man", "Anthony Stark").entry["id"] == 346
    assert matcher(ALL).match("iron-fist", "Iron Fist", None).entry["id"] == 345


def test_auto_match_requires_name_real_name_publisher_and_single_candidate():
    result = matcher(ALL).match("forge-77", "Forge", "Jonathan Silvercloud")

    assert result.entry["id"] == 900
    assert result.method == MATCH_AUTO


def test_auto_match_refuses_homonyms():
    result = matcher([ANGEL_A, ANGEL_B]).match("angel-9", "Angel", "Warren Worthington III")

    assert result.entry is None
    assert result.candidates == [30, 31]


def test_auto_match_needs_real_name():
    result = matcher(ALL).match("forge-77", "Forge", None)

    assert result.entry is None
    assert result.candidates == [900, 901]


def test_unavailable_source_means_no_enrichment():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    result = SuperheroMatcher(SuperheroApiClient(http), load_mappings()).match(
        "storm", "Storm", "Ororo Munroe"
    )

    assert result.entry is None


def test_clean_storm_entry():
    cleaned = clean_entry(STORM_638)

    assert cleaned["alignment"] == "Good"
    assert cleaned["placeOfBirth"] == "New York, New York"
    assert cleaned["occupation"] == "Adventurer"
    assert cleaned["powerstats"] == STORM_638["powerstats"]
    assert cleaned["appearance"] == {
        "gender": "Female",
        "race": "Mutant",
        "heightCm": 180,
        "weightKg": 57,
        "eyeColor": "Blue",
        "hairColor": "White",
    }
    assert cleaned["aliases"] == [
        "Ororo Iqadi T'Challa",
        "Queen Ororo",
        "Ororo Komo Wakandas",
        "White Queen",
        "Weather Witch",
        "Windrider",
    ]
    assert len(cleaned["relatives"]) <= 301
    assert cleaned["relatives"].endswith("…")


def test_absent_markers_are_dropped():
    cleaned = clean_entry(JEAN_GREY_356)

    assert "placeOfBirth" not in cleaned


def test_aliases_drop_sentences_long_values_and_duplicates():
    aliases = ["has impersonated Daredevil", "A" * 41, "Goddess", "goddess", "-"]

    assert clean_aliases(aliases) == ["Goddess"]


def test_incomplete_powerstats_are_not_saved():
    stats = {**STORM_638["powerstats"], "combat": None}

    assert clean_powerstats(stats) is None
    assert clean_powerstats({**STORM_638["powerstats"], "power": 120}) is None
    assert clean_powerstats({**STORM_638["powerstats"], "speed": "47"})["speed"] == 47


def test_zero_height_and_weight_are_absent():
    appearance = {"height": ["-", "0 cm"], "weight": ["- lb", "0 kg"], "gender": "-"}

    assert clean_appearance(appearance) is None


def test_group_affiliations_keep_only_current_groups():
    assert group_affiliations(STORM_638) == ["X-Men"]
    assert group_affiliations(JEAN_GREY_356) == []
    assert group_affiliations(ROCKET_566) == ["Guardians of the Galaxy"]
