from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.catalog.comicvine import ComicVineBudgetExceededError, ComicVineClient, ComicVineError
from app.catalog.fandom import FandomClient
from app.catalog.ingest import IngestService, IngestSettings, compute_tier, image_url
from app.catalog.mapping import Mappings, load_mappings, normalize
from app.catalog.superhero_api import SuperheroApiClient, SuperheroMatcher
from app.catalog.text import html_to_text, slugify
from app.domain.enums import PowerFamily, Team
from app.repositories import CharacterRepository
from app.store.memory import MemoryStore
from tests.conftest import JOBS_KEY
from tests.superhero_samples import STORM_638

STORM_ID = 1468
ISSUE_ID = 9001
FANDOM_TITLE = "Ororo Munroe (Earth-616)"


def cv_ok(results, total=None):
    body = {"status_code": 1, "error": "OK", "results": results}
    if total is not None:
        body["number_of_total_results"] = total
    return httpx.Response(200, json=body)


STORM_SUMMARY = {
    "id": STORM_ID,
    "name": "Storm",
    "publisher": {"id": 31, "name": "Marvel"},
    "count_of_issue_appearances": 4000,
}
STORM_DETAIL = {
    **STORM_SUMMARY,
    "real_name": "Ororo Munroe",
    "origin": {"id": 1, "name": "Mutant"},
    "powers": [{"name": "Weather Control"}, {"name": "Flight"}, {"name": "Unmapped Power"}],
    "teams": [{"name": "X-Men"}, {"name": "Hellfire Club"}],
    "first_appeared_in_issue": {"id": ISSUE_ID, "name": "Deadly Genesis", "issue_number": "1"},
    "image": {"original_url": "https://cv/storm.jpg"},
    "description": "<p>Ororo is a <b>mutant</b>.</p><table><tr><td>lixo</td></tr></table>",
    "deck": "Weather goddess",
    "site_detail_url": "https://comicvine.gamespot.com/storm/4005-1468/",
}


class FakeSource:
    """Responde Comic Vine, Fandom e Superhero API a partir de um roteiro."""

    def __init__(self, detail=None, list_pages=None, fandom=True, superheroes=None):
        self.detail = detail or STORM_DETAIL
        self.superheroes = superheroes or []
        self.list_pages = list_pages or {0: ([], 0)}
        self.fandom = fandom
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.calls.append(url.path)
        if url.netloc == "comicvine.gamespot.com":
            return self._comicvine(url.path, params)
        if url.netloc == "marvel.fandom.com":
            return self._fandom(params)
        if url.netloc == "akabab.github.io":
            return httpx.Response(200, json=self.superheroes)
        raise AssertionError(f"URL inesperada: {request.url}")

    def _comicvine(self, path, params):
        if path == "/api/characters/" and params["filter"].startswith("name:"):
            return cv_ok([STORM_SUMMARY, {**STORM_SUMMARY, "id": 1, "publisher": {"id": 10}}])
        if path == "/api/characters/":
            results, total = self.list_pages[int(params["offset"])]
            return cv_ok(results, total)
        if path.startswith("/api/character/4005-"):
            return cv_ok(self.detail)
        if path == f"/api/issue/4000-{ISSUE_ID}/":
            return cv_ok({"issue_number": "1", "volume": {"name": "Giant-Size X-Men"}})
        raise AssertionError(path)

    def _fandom(self, params):
        if not self.fandom:
            return httpx.Response(200, json={"query": {"search": []}})
        if params["action"] == "query":
            return httpx.Response(200, json={"query": {"search": [{"title": FANDOM_TITLE}]}})
        if params.get("prop") == "sections":
            sections = [{"line": "History", "index": "1"}, {"line": "Personality", "index": "2"}]
            return httpx.Response(200, json={"parse": {"sections": sections}})
        return httpx.Response(200, json={"parse": {"text": {"*": "<p>Calm and regal.</p>"}}})


def mappings(tier_a_names=("Storm",)) -> Mappings:
    loaded = load_mappings()
    return Mappings(
        origins=loaded.origins,
        powers=loaded.powers,
        teams=loaded.teams,
        tier_a_names=list(tier_a_names),
        version=loaded.version,
        superhero_matches=loaded.superhero_matches,
        accepted_publishers=loaded.accepted_publishers,
    )


def build_service(source, store, clock, tier_a_names=("Storm",), budget=50):
    http = httpx.Client(transport=httpx.MockTransport(source))
    no_sleep = lambda seconds: None  # noqa: E731
    loaded = mappings(tier_a_names)
    return IngestService(
        comicvine=ComicVineClient(http, "key", budget, 0.0, sleep=no_sleep),
        fandom=FandomClient(http, max_chars=500, interval_seconds=0.0, sleep=no_sleep),
        superhero=SuperheroMatcher(SuperheroApiClient(http), loaded),
        characters=CharacterRepository(store),
        store=store,
        mappings=loaded,
        clock=clock,
        settings=IngestSettings(tier_b_min_appearances=50, refresh_days=30, bio_max_chars=500),
    )


def test_normalize_ignores_case_punctuation_and_article():
    assert normalize("The S.H.I.E.L.D.") == normalize("shield")


def test_powers_map_to_families_in_enum_order_and_ignore_unknown():
    result = load_mappings().power_families(["Flight", "Super Strength", "Unknown Power"])

    assert result == [PowerFamily.Strength, PowerFamily.Flight]


def test_html_to_text_cleans_and_truncates():
    html = "<p>Um <b>texto</b> &amp; mais</p><script>x()</script><p>fim de frase longa</p>"

    assert html_to_text(html, 1000) == "Um texto & mais fim de frase longa"
    assert html_to_text(html, 12) == "Um texto &…"
    assert html_to_text("<p> </p>", 100) is None


def test_slugify():
    assert slugify("Spider-Man") == "spider-man"
    assert slugify("Drax the Destroyer") == "drax-the-destroyer"


def test_blank_image_is_treated_as_missing():
    assert image_url({"original_url": "https://cv/6373148-blank.png"}) is None
    assert image_url({"original_url": "https://cv/storm.jpg"}) == "https://cv/storm.jpg"


def test_tier_rules():
    complete = {"imageUrl": "x", "bio": "x", "personality": "x", "issueAppearances": 60}

    assert compute_tier({}, curated=True, min_appearances=50) == "A"
    assert compute_tier(complete, curated=False, min_appearances=50) == "B"
    assert compute_tier({**complete, "issueAppearances": 10}, False, 50) is None
    assert compute_tier({**complete, "personality": None}, False, 50) is None


def test_comicvine_budget_per_resource():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: cv_ok({})))
    client = ComicVineClient(http, "key", 1, 0.0, sleep=lambda s: None)

    client.character(1)
    with pytest.raises(ComicVineBudgetExceededError):
        client.character(2)
    client.issue(1)  # outro recurso, outro limite


def test_comicvine_error_status_raises():
    body = {"status_code": 100, "error": "Invalid API Key"}
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))

    with pytest.raises(ComicVineError):
        ComicVineClient(http, "key", 5, 0.0, sleep=lambda s: None).character(1)


def test_comicvine_waits_interval_between_requests():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: cv_ok({})))
    waits = []
    client = ComicVineClient(http, "key", 5, 1.0, sleep=waits.append, monotonic=lambda: 10.0)

    client.character(1)
    client.character(2)

    assert waits == [1.0]


def test_tier_a_character_is_ingested_with_mapped_facts(clock):
    store = MemoryStore()

    report = build_service(FakeSource(), store, clock).run()

    assert report.ingested == ["storm"]
    doc = store.get("characters/storm")
    assert doc["tier"] == "A"
    assert doc["comicVineId"] == STORM_ID
    assert doc["realName"] == "Ororo Munroe"
    assert doc["origin"] == "Mutant"
    assert doc["powers"] == ["Flight", "Energy"]
    assert doc["teams"] == ["XMen"]
    assert doc["firstAppearance"] == "Giant-Size X-Men #1"
    assert doc["bio"] == "Ororo is a mutant."
    assert doc["personality"] == "Calm and regal."
    assert doc["sources"][1] == {
        "name": "Marvel Database (CC BY-SA)",
        "url": "https://marvel.fandom.com/wiki/Ororo_Munroe_%28Earth-616%29",
    }
    assert doc["fetchedAt"] == clock.now()
    assert None not in doc.values()


def test_missing_facts_are_omitted_not_null(clock):
    store = MemoryStore()
    detail = {**STORM_DETAIL, "real_name": None, "origin": None, "first_appeared_in_issue": None}

    build_service(FakeSource(detail=detail, fandom=False), store, clock).run()

    doc = store.get("characters/storm")
    for absent in ("realName", "origin", "firstAppearance", "personality"):
        assert absent not in doc


def test_fresh_characters_are_not_refetched(clock):
    store = MemoryStore()
    source = FakeSource()
    build_service(source, store, clock).run()
    calls_after_first_run = len(source.calls)

    clock.current += timedelta(days=1)
    build_service(source, store, clock).run()

    detail_calls = [c for c in source.calls[calls_after_first_run:] if "4005-" in c]
    assert detail_calls == []


def test_styles_from_persona_survive_reingestion(clock):
    store = MemoryStore()
    build_service(FakeSource(), store, clock).run()
    store.update("characters/storm", {"styles": ["Leadership"]})

    clock.current += timedelta(days=31)
    build_service(FakeSource(), store, clock).run()

    assert store.get("characters/storm")["styles"] == ["Leadership"]


def test_incremental_ingests_tier_b_candidates_and_advances_offset(clock):
    store = MemoryStore()
    other = {**STORM_SUMMARY, "id": 77, "name": "Forge", "count_of_issue_appearances": 300}
    rare = {**STORM_SUMMARY, "id": 78, "name": "Rare One", "count_of_issue_appearances": 3}
    source = FakeSource(
        detail={**STORM_DETAIL, "id": 77, "name": "Forge"},
        list_pages={0: ([other, rare], 2)},
    )

    report = build_service(source, store, clock, tier_a_names=()).run()

    assert report.ingested == ["forge-77"]
    assert store.get("characters/forge-77")["tier"] == "B"
    assert store.get("characters/rare-one-78") is None
    assert store.get("jobState/ingest")["offset"] == 0


def test_budget_exhaustion_stops_and_keeps_state(clock):
    store = MemoryStore()

    report = build_service(FakeSource(), store, clock, budget=1).run()

    assert report.budget_exhausted is True
    assert store.get("jobState/ingest")["tierA"] == {"Storm": STORM_ID}


def test_team_solo_only_when_source_says_no_team(clock):
    store = MemoryStore()
    detail = {**STORM_DETAIL, "teams": []}
    no_team = {**STORM_638, "connections": {"groupAffiliation": "None"}}
    build_service(FakeSource(detail=detail, superheroes=[no_team]), store, clock).run()

    assert store.get("characters/storm")["teams"] == [Team.Solo.value]


def test_matched_superhero_affiliations_fill_missing_teams(clock):
    store = MemoryStore()
    detail = {**STORM_DETAIL, "teams": []}

    build_service(FakeSource(detail=detail, superheroes=[STORM_638]), store, clock).run()

    doc = store.get("characters/storm")
    assert doc["teams"] == ["XMen"]
    assert doc["factSources"]["teams"] == "SuperheroApi"


def test_empty_source_teams_without_evidence_stay_empty(clock):
    store = MemoryStore()
    build_service(FakeSource(detail={**STORM_DETAIL, "teams": []}), store, clock).run()

    assert store.get("characters/storm")["teams"] == []


class FakeIngest:
    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1


def test_jobs_ingest_route_runs_in_background(client, container):
    container.ingest = FakeIngest()

    response = client.post("/jobs/ingest", headers={"X-Jobs-Key": JOBS_KEY})

    assert response.status_code == 202
    assert container.ingest.runs == 1


def test_jobs_ingest_without_comicvine_key_is_503(client):
    response = client.post("/jobs/ingest", headers={"X-Jobs-Key": JOBS_KEY})

    assert response.status_code == 503


def test_enrichment_from_matched_superhero_entry(clock):
    store = MemoryStore()

    build_service(FakeSource(superheroes=[STORM_638]), store, clock).run()

    doc = store.get("characters/storm")
    assert doc["superheroId"] == 638
    assert doc["superheroMatch"] == "manual"
    assert doc["enrichedAt"] == clock.now()
    assert doc["powerstats"]["power"] == 88
    assert doc["appearance"]["heightCm"] == 180
    assert doc["alignment"] == "Good"
    assert doc["factSources"]["realName"] == "ComicVine"
    assert doc["factSources"]["powerstats"] == "SuperheroApi"
    assert doc["factSources"]["teams"] == "ComicVine"
    assert {"name": "Superhero API", "url": "https://akabab.github.io/superhero-api/"} in doc[
        "sources"
    ]
    assert "storm" not in store.get("jobState/ingest")["superheroReview"]


def test_unmatched_character_goes_to_review_queue(clock):
    store = MemoryStore()

    build_service(FakeSource(), store, clock).run()

    doc = store.get("characters/storm")
    assert "superheroId" not in doc and "powerstats" not in doc
    review = store.get("jobState/ingest")["superheroReview"]
    assert review["storm"] == {"name": "Storm", "realName": "Ororo Munroe", "candidates": []}


def test_mapping_version_change_forces_refresh(clock):
    store = MemoryStore()
    source = FakeSource()
    build_service(source, store, clock).run()
    store.update("characters/storm", {"mappingVersion": "old"})
    calls = len(source.calls)

    build_service(source, store, clock).run()

    assert any("4005-" in c for c in source.calls[calls:])


def test_tier_a_search_name_and_fixed_id_overrides(clock):
    store = MemoryStore()
    service = build_service(FakeSource(), store, clock, tier_a_names=("Stormy", "Fixed"))
    service._mappings = Mappings(
        origins=service._mappings.origins,
        powers=service._mappings.powers,
        teams=service._mappings.teams,
        tier_a_names=["Stormy", "Fixed"],
        version=service._mappings.version,
        superhero_matches=service._mappings.superhero_matches,
        accepted_publishers=service._mappings.accepted_publishers,
        tier_a_search_names={"Stormy": "Storm"},
        tier_a_ids={"Fixed": STORM_ID},
    )

    report = service.run()

    assert report.unresolved_tier_a == []
    state = store.get("jobState/ingest")["tierA"]
    assert state == {"Stormy": STORM_ID, "Fixed": STORM_ID}
    assert store.get("characters/stormy") is not None
    assert store.get("characters/fixed") is not None


def test_names_match_accepts_identity_suffix_but_not_look_alikes():
    from app.catalog.ingest import names_match

    assert names_match("Ant-Man (Lang)", "Ant-Man")
    assert names_match("Ghost Rider (Blaze)", "Ghost Rider")
    assert names_match("Storm", "Storm")
    assert names_match("Mr. Fantastic", "Mr. Fantastic")
    assert not names_match("Green Goblin Construct", "Green Goblin")
    assert not names_match("Ghost Rider 2099", "Ghost Rider")
    assert not names_match("Cosmic Ghost Rider", "Ghost Rider")
    assert not names_match("Falcona", "Falcon")
