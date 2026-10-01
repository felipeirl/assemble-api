from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Origin, PowerFamily, Style, Team

FAME_ICONS = 0.0
FAME_HIDDEN_GEMS = 1.0


class Preferences(BaseModel):
    """Preferências do usuário; lista vazia = "Any"."""

    model_config = ConfigDict(extra="ignore")

    origins: list[Origin] = Field(default_factory=list)
    powers: list[PowerFamily] = Field(default_factory=list)
    teams: list[Team] = Field(default_factory=list)
    styles: list[Style] = Field(default_factory=list)
    fame: float = Field(default=0.5, ge=FAME_ICONS, le=FAME_HIDDEN_GEMS)


class CharacterTraits(BaseModel):
    """Traços mapeados de um personagem, usados na compatibilidade."""

    model_config = ConfigDict(extra="ignore")

    origin: Origin | None = None
    powers: list[PowerFamily] = Field(default_factory=list)
    teams: list[Team] = Field(default_factory=list)
    styles: list[Style] = Field(default_factory=list)
    issueAppearances: int | None = None
