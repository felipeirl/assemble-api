"""Pré-visualização / perfil completo do personagem e estatísticas do usuário."""

from typing import Any

from app.api.schemas import CharacterFacts, CharacterView, UserStats, WhyYouMatch
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

FACT_KEYS = ("realName", "origin", "powers", "teams", "firstAppearance", "bio")
DEFAULT_SOURCE = "Comic Vine"


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
            return full_profile(character_id, doc, match)
        doc = self._catalog.get(character_id)
        if doc is None:
            raise ApiError("not_found")
        # Sem conexão: nada de bio, poderes, equipes, primeira aparição nem compatibilidade.
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
            doc = self._catalog.get(character_id) or self._characters.get(character_id) or {}
            teams.update(team for team in doc.get("teams") or [] if team != Team.Solo.value)
        return UserStats(
            connections=len(matches),
            messagesSent=sum(int(m.get("userMessageCount") or 0) for _, m in matches),
            charactersSeen=self._decisions.count(uid),
            distinctTeams=len(teams),
        )


def full_profile(character_id: str, doc: dict[str, Any], match: dict[str, Any]) -> CharacterView:
    facts = {key: doc[key] for key in FACT_KEYS if doc.get(key)}
    return CharacterView(
        characterId=character_id,
        name=doc["name"],
        imageUrl=doc.get("imageUrl"),
        connected=True,
        connectionId=character_id,
        score=match["score"],
        whyYouMatch=[WhyYouMatch(**item) for item in match.get("whyYouMatch", [])],
        facts=CharacterFacts(**facts),
        source=doc.get("source", DEFAULT_SOURCE),
        sourceUrl=doc.get("sourceUrl"),
    )
