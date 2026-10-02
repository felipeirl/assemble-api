"""Tabelas versionadas em data/ que traduzem nomes das fontes para os enums do app."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.enums import Origin, PowerFamily, Team

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def normalize(name: str) -> str:
    lowered = name.strip().lower()
    lowered = re.sub(r"^the\s+", "", lowered)
    return re.sub(r"[^a-z0-9]", "", lowered)


@dataclass(frozen=True)
class Mappings:
    origins: dict[str, Origin]
    powers: dict[str, PowerFamily]
    teams: dict[str, Team]
    tier_a_names: list[str]
    version: str
    superhero_matches: dict[str, int | None] = field(default_factory=dict)
    accepted_publishers: frozenset[str] = frozenset()

    def origin(self, source_name: str | None) -> Origin | None:
        if not source_name:
            return None
        return self.origins.get(normalize(source_name))

    def power_families(self, source_names: list[str]) -> list[PowerFamily]:
        found = {self.powers.get(normalize(name)) for name in source_names}
        return [family for family in PowerFamily if family in found]

    def team_list(self, source_names: list[str]) -> list[Team]:
        found = {self.teams.get(normalize(name)) for name in source_names}
        return [team for team in Team if team in found]


def load_mappings(data_dir: Path = DATA_DIR) -> Mappings:
    origins_file = _read(data_dir / "origins.json")
    powers_file = _read(data_dir / "power_families.json")
    teams_file = _read(data_dir / "teams.json")
    tier_a_file = _read(data_dir / "tier_a.json")
    superhero_file = _read(data_dir / "superhero_matches.json")

    origins = {normalize(name): Origin(value) for name, value in origins_file["origins"].items()}
    powers = {
        normalize(name): PowerFamily(family)
        for family, names in powers_file["families"].items()
        for name in names
    }
    teams = {
        normalize(name): Team(team) for team, names in teams_file["teams"].items() for name in names
    }
    version = (
        f"o{origins_file['version']}.p{powers_file['version']}"
        f".t{teams_file['version']}.a{tier_a_file['version']}.s{superhero_file['version']}"
    )
    return Mappings(
        origins=origins,
        powers=powers,
        teams=teams,
        tier_a_names=list(tier_a_file["names"]),
        version=version,
        superhero_matches=dict(superhero_file["matches"]),
        accepted_publishers=frozenset(superhero_file["acceptedPublishers"]),
    )


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)
