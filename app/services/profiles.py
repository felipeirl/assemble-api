"""Pré-visualização / perfil completo do personagem e estatísticas do usuário."""

from typing import Any

from app.api.schemas import (
    CharacterFacts,
    CharacterView,
    CompareWith,
    SourceCredit,
    Teammate,
    UserStats,
    WhyYouMatch,
)
from app.catalog.catalog import CharacterCatalog
from app.domain.compatibility import traits_in_common
from app.domain.enums import Team
from app.domain.models import CharacterTraits
from app.errors import ApiError
from app.repositories import (
    CharacterRepository,
    DecisionRepository,
    MatchRepository,
    UserRepository,
)

FACT_KEYS = (
    "realName",
    "aliases",
    "origin",
    "powers",
    "teams",
    "alignment",
    "placeOfBirth",
    "occupation",
    "base",
    "firstAppearance",
    "issueAppearances",
    "bio",
    "relatives",
    "powerstats",
    "appearance",
)
COMIC_VINE = "Comic Vine"
TEAMMATES_MAX = 8


class ProfileService:
    def __init__(
        self,
        catalog: CharacterCatalog,
        characters: CharacterRepository,
        users: UserRepository,
        decisions: DecisionRepository,
        matches: MatchRepository,
    ) -> None:
        self._catalog = catalog
        self._characters = characters
        self._users = users
        self._decisions = decisions
        self._matches = matches

    def character(self, uid: str, character_id: str) -> CharacterView:
        match = self._matches.get(uid, character_id)
        if match is not None:
            doc = self._characters.get(character_id)
            if doc is None:
                raise ApiError("not_found")
            return self._full_profile(uid, character_id, doc, match)
        doc = self._catalog.get(character_id)
        if doc is None:
            raise ApiError("not_found")
        # Sem conexão: nada de bio, fatos, atributos, colegas nem compatibilidade.
        return CharacterView(
            characterId=character_id,
            name=doc["name"],
            imageUrl=doc.get("imageUrl"),
            connected=False,
            traitsInCommon=traits_in_common(
                self._users.preferences(uid), CharacterTraits.model_validate(doc)
            ),
        )

    def stats(self, uid: str) -> UserStats:
        matches = self._matches.for_user(uid)
        teams: set[str] = set()
        for character_id, _ in matches:
            doc = self._lookup(character_id) or {}
            teams.update(team for team in doc.get("teams") or [] if team != Team.Solo.value)
        return UserStats(
            connections=len(matches),
            messagesSent=sum(int(m.get("userMessageCount") or 0) for _, m in matches),
            charactersSeen=self._decisions.count(uid),
            distinctTeams=len(teams),
        )

    def _full_profile(
        self, uid: str, character_id: str, doc: dict[str, Any], match: dict[str, Any]
    ) -> CharacterView:
        facts = {key: doc[key] for key in FACT_KEYS if doc.get(key)}
        connected_ids = {cid for cid, _ in self._matches.for_user(uid)}
        return CharacterView(
            characterId=character_id,
            name=doc["name"],
            imageUrl=doc.get("imageUrl"),
            connected=True,
            connectionId=character_id,
            score=match["score"],
            whyYouMatch=[WhyYouMatch(**item) for item in match.get("whyYouMatch", [])],
            facts=CharacterFacts(**facts),
            factSources={
                key: source
                for key, source in (doc.get("factSources") or {}).items()
                if key in facts
            },
            sources=source_credits(doc),
            teammates=self._teammates(character_id, doc, connected_ids),
            compareWith=self._compare_with(character_id, connected_ids),
        )

    def _teammates(
        self, character_id: str, doc: dict[str, Any], connected_ids: set[str]
    ) -> list[Teammate]:
        teams = {team for team in doc.get("teams") or [] if team != Team.Solo.value}
        if not teams:
            return []
        mates = [
            Teammate(
                characterId=other_id,
                name=other["name"],
                imageUrl=other.get("imageUrl"),
                connected=other_id in connected_ids,
            )
            for other_id, other in self._catalog.eligible().items()
            if other_id != character_id and teams & set(other.get("teams") or [])
        ]
        mates.sort(key=lambda mate: (not mate.connected, mate.name.lower()))
        return mates[:TEAMMATES_MAX]

    def _compare_with(self, character_id: str, connected_ids: set[str]) -> list[CompareWith]:
        result = []
        for other_id in sorted(connected_ids - {character_id}):
            other = self._lookup(other_id)
            if other and other.get("powerstats"):
                result.append(
                    CompareWith(
                        characterId=other_id, name=other["name"], powerstats=other["powerstats"]
                    )
                )
        return result

    def _lookup(self, character_id: str) -> dict[str, Any] | None:
        return self._catalog.get(character_id) or self._characters.get(character_id)


def source_credits(doc: dict[str, Any]) -> list[SourceCredit]:
    credits = [
        SourceCredit(name=item["name"], url=item.get("url"))
        for item in doc.get("sources") or []
        if item.get("name")
    ]
    if not credits:
        credits.append(SourceCredit(name=doc.get("source", COMIC_VINE), url=doc.get("sourceUrl")))
    return credits
