"""Ponte Wikidata: nomes (rótulo + apelidos) do item ligado a um ID da Comic Vine (P5905).

A Superhero API não tem propriedade no Wikidata; a ponte é pelos nomes do item.
"""

import logging
import time
from collections.abc import Callable

import httpx

from app.catalog.mapping import normalize

SPARQL_URL = "https://query.wikidata.org/sparql"
COMIC_VINE_CHARACTER_PREFIX = "4005-"
USER_AGENT = "AssembleBackend/0.1 (academic project; https://github.com/)"
QUERY = """SELECT ?label ?alias WHERE {
  ?item wdt:P5905 "%s" .
  OPTIONAL { ?item rdfs:label ?label FILTER(LANG(?label) = "en") }
  OPTIONAL { ?item skos:altLabel ?alias FILTER(LANG(?alias) = "en") }
}"""

logger = logging.getLogger(__name__)


class WikidataBridge:
    def __init__(
        self,
        http: httpx.Client,
        interval_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._interval = interval_seconds
        self._sleep = sleep
        self._cache: dict[int, frozenset[str]] = {}

    def names(self, comicvine_id: int) -> frozenset[str]:
        """Nomes normalizados do item; vazio quando não há item ou o Wikidata está fora."""
        if comicvine_id in self._cache:
            return self._cache[comicvine_id]
        self._sleep(self._interval)
        try:
            response = self._http.get(
                SPARQL_URL,
                params={"query": QUERY % f"{COMIC_VINE_CHARACTER_PREFIX}{comicvine_id}"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
            )
            response.raise_for_status()
            bindings = response.json()["results"]["bindings"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning("Wikidata indisponível para %s: %s", comicvine_id, type(exc).__name__)
            return frozenset()
        names = frozenset(
            normalize(row[key]["value"])
            for row in bindings
            for key in ("label", "alias")
            if key in row
        )
        self._cache[comicvine_id] = names
        return names
