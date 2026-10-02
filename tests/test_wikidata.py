from urllib.parse import parse_qs, urlparse

import httpx

from app.catalog.mapping import load_mappings, normalize
from app.catalog.superhero_api import MATCH_WIKIDATA, SuperheroApiClient, SuperheroMatcher
from app.catalog.wikidata import WikidataBridge

IRON_MAN_CV = 1455
SPARQL_ROWS = {
    "results": {
        "bindings": [
            {"label": {"value": "Iron Man"}, "alias": {"value": "Tony Stark"}},
            {"label": {"value": "Iron Man"}, "alias": {"value": "Anthony Edward Stark"}},
        ]
    }
}
OTHER_IRON_MAN = {
    "id": 9001,
    "name": "Iron Man",
    "biography": {"fullName": "Tony Stark", "publisher": "Marvel Comics"},
}
IRON_MAN_2020 = {
    "id": 9002,
    "name": "Iron Man",
    "biography": {"fullName": "Arno Stark", "publisher": "Marvel Comics"},
}


def bridge(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return WikidataBridge(http, interval_seconds=0.0, sleep=lambda s: None)


def test_bridge_queries_comic_vine_property_and_normalizes_names():
    queries = []

    def handler(request):
        queries.append(parse_qs(urlparse(str(request.url)).query)["query"][0])
        assert "AssembleBackend" in request.headers["User-Agent"]
        return httpx.Response(200, json=SPARQL_ROWS)

    names = bridge(handler).names(IRON_MAN_CV)

    assert 'wdt:P5905 "4005-1455"' in queries[0]
    assert names == {
        normalize("Iron Man"),
        normalize("Tony Stark"),
        normalize("Anthony Edward Stark"),
    }


def test_bridge_caches_per_run():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=SPARQL_ROWS)

    wikidata = bridge(handler)
    wikidata.names(IRON_MAN_CV)
    wikidata.names(IRON_MAN_CV)

    assert len(calls) == 1


def test_bridge_outage_returns_no_names():
    assert bridge(lambda r: httpx.Response(503)).names(IRON_MAN_CV) == frozenset()


class FixedBridge:
    def __init__(self, names):
        self._names = frozenset(normalize(n) for n in names)

    def names(self, comicvine_id):
        return self._names


def matcher(entries, names):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=entries)))
    return SuperheroMatcher(SuperheroApiClient(http), load_mappings(), FixedBridge(names))


def test_wikidata_bridges_real_name_variants():
    result = matcher([OTHER_IRON_MAN, IRON_MAN_2020], ["Iron Man", "Tony Stark"]).match(
        "iron-man-1455", "Iron Man", "Anthony Edward Stark", IRON_MAN_CV
    )

    assert result.entry["id"] == 9001
    assert result.method == MATCH_WIKIDATA


def test_wikidata_ambiguity_is_refused():
    result = matcher(
        [OTHER_IRON_MAN, IRON_MAN_2020], ["Iron Man", "Tony Stark", "Arno Stark"]
    ).match("iron-man-1455", "Iron Man", "Anthony Edward Stark", IRON_MAN_CV)

    assert result.entry is None
    assert result.candidates == [9001, 9002]


def test_manual_table_still_wins_over_wikidata():
    result = matcher([OTHER_IRON_MAN], ["Iron Man", "Tony Stark"]).match(
        "iron-man", "Iron Man", None, IRON_MAN_CV
    )

    # A tabela manual aponta 346, ausente desta amostra: não cai para o Wikidata.
    assert result.entry is None
    assert result.method is None
