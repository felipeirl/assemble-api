"""Superhero API (akabab): afiliações de grupo, usadas só quando a Comic Vine não traz equipes."""

import logging
import re

import httpx

from app.catalog.mapping import normalize

ALL_URL = "https://akabab.github.io/superhero-api/api/all.json"
MARVEL_PUBLISHER = "Marvel Comics"

logger = logging.getLogger(__name__)


class SuperheroApiClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http
        self._affiliations: dict[str, list[str]] | None = None

    def group_affiliations(self, name: str) -> list[str] | None:
        """Grupos do personagem; None quando a fonte não tem o personagem ou está fora."""
        affiliations = self._load()
        return affiliations.get(normalize(name))

    def _load(self) -> dict[str, list[str]]:
        if self._affiliations is not None:
            return self._affiliations
        try:
            response = self._http.get(ALL_URL)
            response.raise_for_status()
            entries = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Superhero API indisponível: %s", type(exc).__name__)
            entries = []
        self._affiliations = {
            normalize(entry["name"]): split_groups(
                entry.get("connections", {}).get("groupAffiliation", "")
            )
            for entry in entries
            if entry.get("biography", {}).get("publisher") == MARVEL_PUBLISHER
        }
        return self._affiliations


def split_groups(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", text or "") if part.strip()]
