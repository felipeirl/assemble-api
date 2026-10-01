"""Cliente da Comic Vine com limite por recurso (~200 requisições/hora) e espaçamento."""

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import httpx

BASE_URL = "https://comicvine.gamespot.com/api"
USER_AGENT = "AssembleBackend/0.1 (academic project)"
MARVEL_PUBLISHER_ID = 31
PAGE_SIZE = 100
STATUS_OK = 1

LIST_FIELDS = "id,name,real_name,publisher,count_of_issue_appearances,date_last_updated"
DETAIL_FIELDS = (
    "id,name,real_name,origin,powers,teams,first_appeared_in_issue,count_of_issue_appearances,"
    "image,deck,description,publisher,site_detail_url,date_last_updated"
)

RESOURCE_CHARACTERS = "characters"
RESOURCE_CHARACTER = "character"
RESOURCE_ISSUE = "issue"


class ComicVineError(Exception):
    pass


class ComicVineBudgetExceededError(Exception):
    """O limite de requisições por recurso desta execução foi atingido."""


class ComicVineClient:
    def __init__(
        self,
        http: httpx.Client,
        api_key: str,
        max_requests_per_resource: int,
        interval_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._max_requests = max_requests_per_resource
        self._interval = interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._counts: dict[str, int] = defaultdict(int)
        self._last_request_at: float | None = None

    def list_marvel_characters(self, offset: int) -> tuple[list[dict[str, Any]], int]:
        body = self._get(
            RESOURCE_CHARACTERS,
            "characters",
            {
                "filter": f"publisher:{MARVEL_PUBLISHER_ID}",
                "sort": "count_of_issue_appearances:desc",
                "field_list": LIST_FIELDS,
                "offset": offset,
                "limit": PAGE_SIZE,
            },
        )
        results = [item for item in body.get("results") or [] if is_marvel(item)]
        return results, int(body.get("number_of_total_results") or 0)

    def find_marvel_characters_by_name(self, name: str) -> list[dict[str, Any]]:
        body = self._get(
            RESOURCE_CHARACTERS,
            "characters",
            {
                "filter": f"name:{name}",
                "sort": "count_of_issue_appearances:desc",
                "field_list": LIST_FIELDS,
                "limit": PAGE_SIZE,
            },
        )
        return [item for item in body.get("results") or [] if is_marvel(item)]

    def character(self, comicvine_id: int) -> dict[str, Any]:
        body = self._get(
            RESOURCE_CHARACTER, f"character/4005-{comicvine_id}", {"field_list": DETAIL_FIELDS}
        )
        return body.get("results") or {}

    def issue(self, issue_id: int) -> dict[str, Any]:
        body = self._get(
            RESOURCE_ISSUE, f"issue/4000-{issue_id}", {"field_list": "issue_number,volume"}
        )
        return body.get("results") or {}

    def _get(self, resource: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._counts[resource] >= self._max_requests:
            raise ComicVineBudgetExceededError(resource)
        self._wait_interval()
        self._counts[resource] += 1
        try:
            response = self._http.get(
                f"{BASE_URL}/{path}/",
                params={"api_key": self._api_key, "format": "json", **params},
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ComicVineError(f"{resource}: {type(exc).__name__}") from exc
        if body.get("status_code") != STATUS_OK:
            raise ComicVineError(f"{resource}: {body.get('error')}")
        return body

    def _wait_interval(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self._interval - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()


def is_marvel(item: dict[str, Any]) -> bool:
    publisher = item.get("publisher") or {}
    return publisher.get("id") == MARVEL_PUBLISHER_ID
