"""Ingestão incremental do catálogo Marvel (Comic Vine + complementos) em `characters/`."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.catalog.comicvine import (
    ComicVineBudgetExceededError,
    ComicVineClient,
    ComicVineError,
)
from app.catalog.fandom import SOURCE_LABEL as FANDOM_SOURCE_LABEL
from app.catalog.fandom import FandomClient
from app.catalog.mapping import Mappings, normalize
from app.catalog.superhero_api import SOURCE_LABEL as SUPERHERO_SOURCE_LABEL
from app.catalog.superhero_api import SOURCE_URL as SUPERHERO_SOURCE_URL
from app.catalog.superhero_api import (
    SuperheroMatch,
    SuperheroMatcher,
    clean_entry,
    group_affiliations,
)
from app.catalog.text import html_to_text, slugify
from app.clock import Clock
from app.domain.enums import Team
from app.repositories import CharacterRepository
from app.store.base import DocumentStore

COMIC_VINE = "Comic Vine"
PUBLISHER = "Marvel"
TIER_A = "A"
TIER_B = "B"
STATE_PATH = "jobState/ingest"
NO_TEAM_MARKERS = {"none", "noaffiliation"}
REVIEW_QUEUE_MAX = 200
FACT_SOURCE_COMIC_VINE = "ComicVine"
FACT_SOURCE_SUPERHERO_API = "SuperheroApi"
COMIC_VINE_FACTS = ("realName", "origin", "powers", "firstAppearance", "issueAppearances", "bio")
BLANK_IMAGE_MARKER = "blank"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestSettings:
    tier_b_min_appearances: int
    refresh_days: int
    bio_max_chars: int


@dataclass
class IngestReport:
    ingested: list[str] = field(default_factory=list)
    unresolved_tier_a: list[str] = field(default_factory=list)
    errors: int = 0
    budget_exhausted: bool = False
    superhero_matched: list[str] = field(default_factory=list)
    superhero_review: dict[str, dict[str, Any]] = field(default_factory=dict)


def compute_tier(doc: dict[str, Any], curated: bool, min_appearances: int) -> str | None:
    if curated:
        return TIER_A
    has_data = all(doc.get(key) for key in ("imageUrl", "bio", "personality"))
    if has_data and (doc.get("issueAppearances") or 0) >= min_appearances:
        return TIER_B
    return None


class IngestService:
    def __init__(
        self,
        comicvine: ComicVineClient,
        fandom: FandomClient,
        superhero: SuperheroMatcher,
        characters: CharacterRepository,
        store: DocumentStore,
        mappings: Mappings,
        clock: Clock,
        settings: IngestSettings,
    ) -> None:
        self._cv = comicvine
        self._fandom = fandom
        self._superhero = superhero
        self._characters = characters
        self._store = store
        self._mappings = mappings
        self._clock = clock
        self._settings = settings

    def run(self) -> IngestReport:
        report = IngestReport()
        state = self._store.get(STATE_PATH) or {"offset": 0, "tierA": {}}
        try:
            self._ingest_tier_a(state, report)
            self._ingest_incremental(state, report)
        except ComicVineBudgetExceededError:
            report.budget_exhausted = True
        finally:
            _update_review_queue(state, report)
            self._store.set(STATE_PATH, state)
        logger.info(
            "Ingestão: %d gravados, %d erros, limite atingido=%s",
            len(report.ingested),
            report.errors,
            report.budget_exhausted,
        )
        return report

    def _ingest_tier_a(self, state: dict[str, Any], report: IngestReport) -> None:
        resolved: dict[str, int] = state.setdefault("tierA", {})
        for name in self._mappings.tier_a_names:
            comicvine_id = resolved.get(name)
            if comicvine_id is None:
                candidates = [
                    c
                    for c in self._cv.find_marvel_characters_by_name(name)
                    if normalize(c.get("name", "")) == normalize(name)
                ]
                if not candidates:
                    report.unresolved_tier_a.append(name)
                    continue
                best = max(candidates, key=lambda c: c.get("count_of_issue_appearances") or 0)
                comicvine_id = best["id"]
                resolved[name] = comicvine_id
            character_id = slugify(name)
            if self._is_fresh(character_id):
                continue
            self._ingest_one(character_id, comicvine_id, curated=True, report=report)

    def _ingest_incremental(self, state: dict[str, Any], report: IngestReport) -> None:
        curated_ids = set(state.get("tierA", {}).values())
        while True:
            offset = state.get("offset", 0)
            page, total = self._cv.list_marvel_characters(offset)
            for summary in page:
                appearances = summary.get("count_of_issue_appearances") or 0
                if summary["id"] in curated_ids:
                    continue
                if appearances < self._settings.tier_b_min_appearances:
                    continue
                character_id = f"{slugify(summary['name'])}-{summary['id']}"
                if self._is_fresh(character_id):
                    continue
                self._ingest_one(character_id, summary["id"], curated=False, report=report)
            next_offset = offset + len(page)
            state["offset"] = 0 if not page or next_offset >= total else next_offset
            if not page:
                return

    def _is_fresh(self, character_id: str) -> bool:
        existing = self._characters.get(character_id)
        if existing is None or "fetchedAt" not in existing:
            return False
        if existing.get("mappingVersion") != self._mappings.version:
            return False
        age = self._clock.now() - existing["fetchedAt"]
        return age < timedelta(days=self._settings.refresh_days)

    def _ingest_one(
        self, character_id: str, comicvine_id: int, curated: bool, report: IngestReport
    ) -> None:
        try:
            detail = self._cv.character(comicvine_id)
            first_appearance = self._first_appearance(detail.get("first_appeared_in_issue"))
        except ComicVineError as exc:
            logger.warning("Comic Vine falhou para %s: %s", character_id, exc)
            report.errors += 1
            return
        if not detail.get("name"):
            report.errors += 1
            return
        doc = self._build_document(
            character_id, detail, first_appearance, curated, self._clock.now(), report
        )
        existing = self._characters.get(character_id) or {}
        for preserved in ("ingestedAt", "styles"):
            if preserved in existing:
                doc[preserved] = existing[preserved]
        self._characters.replace(character_id, doc)
        report.ingested.append(character_id)

    def _first_appearance(self, issue_ref: dict[str, Any] | None) -> str | None:
        if not issue_ref or not issue_ref.get("id"):
            return None
        issue = self._cv.issue(issue_ref["id"])
        volume = (issue.get("volume") or {}).get("name")
        number = issue.get("issue_number")
        if not volume or not number:
            return None
        return f"{volume} #{number}"

    def _build_document(
        self,
        character_id: str,
        detail: dict[str, Any],
        first_appearance: str | None,
        curated: bool,
        now: datetime,
        report: IngestReport,
    ) -> dict[str, Any]:
        name = detail["name"]
        real_name = detail.get("real_name") or None
        personality = self._fandom.personality(name, real_name)
        superhero = self._superhero.match(character_id, name, real_name)
        teams, teams_source = self._teams(detail, superhero)
        sources = [{"name": COMIC_VINE, "url": detail.get("site_detail_url")}]
        if personality is not None:
            sources.append({"name": FANDOM_SOURCE_LABEL, "url": personality.url})

        facts: dict[str, Any] = {
            "name": name,
            "realName": real_name,
            "origin": self._origin(detail),
            "powers": [p.value for p in self._powers(detail)],
            "teams": [t.value for t in teams],
            "firstAppearance": first_appearance,
            "issueAppearances": detail.get("count_of_issue_appearances"),
            "imageUrl": image_url(detail.get("image")),
            "bio": html_to_text(detail.get("description"), self._settings.bio_max_chars)
            or html_to_text(detail.get("deck"), self._settings.bio_max_chars),
            "personality": personality.text if personality else None,
            "sourceUrl": detail.get("site_detail_url"),
        }
        doc = {key: value for key, value in facts.items() if value not in (None, "")}
        fact_sources = {key: FACT_SOURCE_COMIC_VINE for key in COMIC_VINE_FACTS if doc.get(key)}
        if teams:
            fact_sources["teams"] = teams_source
        if superhero.entry is not None:
            enrichment = clean_entry(superhero.entry)
            doc.update(enrichment)
            fact_sources.update({key: FACT_SOURCE_SUPERHERO_API for key in enrichment})
            doc.update(
                {
                    "superheroId": int(superhero.entry["id"]),
                    "superheroMatch": superhero.method,
                    "enrichedAt": now,
                }
            )
            sources.append({"name": SUPERHERO_SOURCE_LABEL, "url": SUPERHERO_SOURCE_URL})
            report.superhero_matched.append(character_id)
        else:
            report.superhero_review[character_id] = {
                "name": name,
                "realName": real_name,
                "candidates": superhero.candidates,
            }
        doc["factSources"] = fact_sources
        doc.update(
            {
                "comicVineId": detail["id"],
                "publisher": PUBLISHER,
                "source": COMIC_VINE,
                "sources": sources,
                "fetchedAt": now,
                "ingestedAt": now,
                "mappingVersion": self._mappings.version,
            }
        )
        doc["tier"] = compute_tier(doc, curated, self._settings.tier_b_min_appearances)
        return doc

    def _origin(self, detail: dict[str, Any]) -> str | None:
        origin = self._mappings.origin((detail.get("origin") or {}).get("name"))
        return origin.value if origin else None

    def _powers(self, detail: dict[str, Any]):
        names = [p.get("name", "") for p in detail.get("powers") or []]
        return self._mappings.power_families(names)

    def _teams(self, detail: dict[str, Any], superhero: SuperheroMatch) -> tuple[list[Team], str]:
        """Equipes da Comic Vine; afiliações da Superhero API só com personagem casado."""
        source_teams = [t.get("name", "") for t in detail.get("teams") or []]
        if source_teams or superhero.entry is None:
            return self._mappings.team_list(source_teams), FACT_SOURCE_COMIC_VINE
        groups = group_affiliations(superhero.entry)
        if groups and all(normalize(group) in NO_TEAM_MARKERS for group in groups):
            return [Team.Solo], FACT_SOURCE_SUPERHERO_API
        return self._mappings.team_list(groups), FACT_SOURCE_SUPERHERO_API


def _update_review_queue(state: dict[str, Any], report: IngestReport) -> None:
    """Personagens sem par seguro na Superhero API ficam para revisão humana."""
    queue: dict[str, Any] = state.setdefault("superheroReview", {})
    for character_id in report.superhero_matched:
        queue.pop(character_id, None)
    for character_id, item in report.superhero_review.items():
        if character_id in queue or len(queue) < REVIEW_QUEUE_MAX:
            queue[character_id] = item


def image_url(image: dict[str, Any] | None) -> str | None:
    if not image:
        return None
    url = image.get("original_url") or image.get("super_url")
    if not url or BLANK_IMAGE_MARKER in url.rsplit("/", 1)[-1]:
        return None
    return url
