"""Seção "Personality" da Marvel Database (Fandom, licença CC BY-SA). Complemento opcional."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.catalog.text import html_to_text

API_URL = "https://marvel.fandom.com/api.php"
WIKI_URL = "https://marvel.fandom.com/wiki/"
SOURCE_LABEL = "Marvel Database (CC BY-SA)"
MAIN_UNIVERSE = "(Earth-616)"
PERSONALITY_SECTION = "Personality"
USER_AGENT = "AssembleBackend/0.1 (academic project)"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Personality:
    text: str
    url: str


class FandomClient:
    def __init__(
        self,
        http: httpx.Client,
        max_chars: int,
        interval_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._max_chars = max_chars
        self._interval = interval_seconds
        self._sleep = sleep

    def personality(self, name: str, real_name: str | None) -> Personality | None:
        try:
            title = self._find_page(real_name or name)
            if title is None:
                return None
            html = self._personality_html(title)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning("Fandom indisponível para %s: %s", name, type(exc).__name__)
            return None
        text = html_to_text(html, self._max_chars)
        if text is None:
            return None
        return Personality(text=text, url=WIKI_URL + quote(title.replace(" ", "_")))

    def _find_page(self, query: str) -> str | None:
        body = self._api(
            {
                "action": "query",
                "list": "search",
                "srsearch": f"{query} {MAIN_UNIVERSE}",
                "srlimit": 1,
            }
        )
        results = body["query"]["search"]
        if not results or MAIN_UNIVERSE not in results[0]["title"]:
            return None
        return results[0]["title"]

    def _personality_html(self, title: str) -> str | None:
        sections = self._api({"action": "parse", "page": title, "prop": "sections"})
        index = next(
            (
                s["index"]
                for s in sections["parse"]["sections"]
                if s.get("line") == PERSONALITY_SECTION
            ),
            None,
        )
        if index is None:
            return None
        body = self._api({"action": "parse", "page": title, "section": index, "prop": "text"})
        return body["parse"]["text"]["*"]

    def _api(self, params: dict) -> dict:
        self._sleep(self._interval)
        response = self._http.get(
            API_URL,
            params={**params, "format": "json"},
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return response.json()
